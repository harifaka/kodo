"""Async `/v1/systemone` client for the local Laya decision model.

Works with Ollama (``laya``), ``laya-serve`` and any other `/v1/systemone`-compatible endpoint. The
model never generates text: it answers a fixed, typed question set in a single forward pass, so the
response is parsed defensively instead of being fed back into a prompt.

API keys are attached to the outgoing request only — never logged, returned or persisted.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.decision.config import SystemOneConfig
from app.decision.errors import (
    SYSTEMONE_DISABLED,
    SYSTEMONE_INVALID_RESPONSE,
    SYSTEMONE_TIMEOUT,
    SYSTEMONE_UNAUTHORIZED,
    SYSTEMONE_UNREACHABLE,
    SystemOneError,
)
from app.decision.schemas import PING_QUESTIONS, SystemOneQuestion, question_payload
from app.decision.state_packer import MAX_STATE_BYTES, dumps_state

SYSTEMONE_PATH = "/v1/systemone"
MAX_REQUEST_BYTES = 64 * 1024

# Tests inject an httpx.MockTransport here so the whole suite runs without network access.
_transport_override: httpx.AsyncBaseTransport | None = None


def set_transport_override(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport_override
    _transport_override = transport


def get_transport_override() -> httpx.AsyncBaseTransport | None:
    return _transport_override


@dataclass(frozen=True)
class QuestionAnswer:
    answer: str | None
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0

    def to_payload(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "probabilities": dict(self.probabilities),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class SystemOneResponse:
    model: str
    answers: dict[str, QuestionAnswer]
    latency_ms: int
    usage: dict[str, Any] = field(default_factory=dict)
    abstain: bool = False
    route: str | None = None
    prediction_set: list[Any] | None = None

    def selected(self, question_id: str) -> str | None:
        answer = self.answers.get(question_id)
        return answer.answer if answer else None

    def confidence_of(self, question_id: str) -> float:
        answer = self.answers.get(question_id)
        return answer.confidence if answer else 0.0

    def answers_payload(self) -> dict[str, Any]:
        return {key: answer.to_payload() for key, answer in self.answers.items()}


@dataclass(frozen=True)
class ConnectionProbe:
    reachable: bool
    latency_ms: int
    model: str
    provider_hint: str
    warning: str | None = None
    error_code: str | None = None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _coerce_probabilities(raw: Any) -> dict[str, float]:
    if isinstance(raw, dict):
        result: dict[str, float] = {}
        for key, value in raw.items():
            number = _as_float(value)
            if number is not None:
                result[str(key)] = _clamp(number)
        return result
    if isinstance(raw, list):
        result = {}
        for item in raw:
            if isinstance(item, dict):
                key = item.get("key") or item.get("label") or item.get("choice")
                number = _as_float(item.get("probability", item.get("score")))
                if isinstance(key, str) and number is not None:
                    result[key] = _clamp(number)
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                key, number = item
                value = _as_float(number)
                if isinstance(key, str) and value is not None:
                    result[key] = _clamp(value)
        return result
    return {}


def _parse_answer(raw: Any) -> QuestionAnswer:
    if isinstance(raw, str):
        return QuestionAnswer(answer=raw or None, probabilities={}, confidence=0.0)
    if not isinstance(raw, dict):
        return QuestionAnswer(answer=None, probabilities={}, confidence=0.0)

    answer: Any = None
    for key in ("answer", "label", "choice", "prediction", "value", "selected"):
        if raw.get(key) is not None:
            answer = raw[key]
            break
    if isinstance(answer, dict):
        answer = answer.get("key") or answer.get("label") or answer.get("choice")
    if isinstance(answer, bool) or not isinstance(answer, (str, int, float)):
        answer = None
    answer_text = str(answer) if answer is not None else None

    probabilities = _coerce_probabilities(
        raw.get("probabilities") or raw.get("probs") or raw.get("scores") or raw.get("dist")
    )
    confidence = _as_float(raw.get("confidence"))
    if confidence is None:
        confidence = _as_float(raw.get("score"))
    if confidence is None and probabilities:
        if answer_text and answer_text in probabilities:
            confidence = probabilities[answer_text]
        elif answer_text is None:
            confidence = max(probabilities.values())
    return QuestionAnswer(
        answer=answer_text,
        probabilities=probabilities,
        confidence=_clamp(confidence or 0.0),
    )


def parse_systemone_response(
    body: Any,
    *,
    model_default: str,
    latency_ms: int,
) -> SystemOneResponse:
    """Parse `{ model, answers, usage }`, tolerating the optional `laya-serve` fields."""
    if not isinstance(body, dict):
        raise SystemOneError(
            SYSTEMONE_INVALID_RESPONSE, "System 1 returned a non-object JSON body.", 502
        )
    answers_raw = body.get("answers")
    if not isinstance(answers_raw, dict) or not answers_raw:
        raise SystemOneError(
            SYSTEMONE_INVALID_RESPONSE, "System 1 returned no typed answers.", 502
        )

    answers = {str(key): _parse_answer(value) for key, value in answers_raw.items()}
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    prediction_set = body.get("prediction_set", body.get("predictionSet"))
    if prediction_set is not None and not isinstance(prediction_set, list):
        prediction_set = None

    abstain = bool(body.get("abstain"))
    if not abstain:
        for raw_key, raw in answers_raw.items():
            if isinstance(raw, dict) and raw.get("abstain") is True:
                abstain = True
                break
            if (answers[str(raw_key)].answer or "").lower() in {"abstain", "uncertain"}:
                abstain = True
                break

    route = body.get("route")
    return SystemOneResponse(
        model=str(body.get("model") or model_default),
        answers=answers,
        latency_ms=max(0, latency_ms),
        usage=usage,
        abstain=abstain,
        route=str(route) if isinstance(route, str) and route else None,
        prediction_set=prediction_set,
    )


class SystemOneClient:
    def __init__(
        self,
        cfg: SystemOneConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._cfg = cfg
        self._transport = transport if transport is not None else _transport_override

    @property
    def config(self) -> SystemOneConfig:
        return self._cfg

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._cfg.api_key:
            headers["Authorization"] = f"Bearer {self._cfg.api_key}"
        return headers

    def _check_ready(self) -> None:
        if not self._cfg.enabled:
            raise SystemOneError(
                SYSTEMONE_DISABLED,
                "System 1 (Laya) is disabled. Kodo keeps working with deterministic rules and "
                "manual DeepSeek triggers.",
                503,
            )
        if not self._cfg.base_url.startswith(("http://", "https://")):
            raise SystemOneError(
                SYSTEMONE_UNREACHABLE,
                f"System 1 Base URL '{self._cfg.base_url}' must start with http:// or https://.",
                400,
            )

    def _client(self) -> httpx.AsyncClient:
        timeout = httpx.Timeout(self._cfg.timeout_seconds, connect=min(5.0, self._cfg.timeout_seconds))
        return httpx.AsyncClient(timeout=timeout, transport=self._transport, follow_redirects=False)

    def build_request_body(self, state: dict[str, Any], questions: tuple[SystemOneQuestion, ...]) -> bytes:
        """Deterministic request bytes: explicit key order, hard state/body ceilings."""
        state_json = dumps_state(state)
        if len(state_json.encode("utf-8")) > MAX_STATE_BYTES:
            raise SystemOneError(
                SYSTEMONE_INVALID_RESPONSE,
                f"The System 1 state exceeded the {MAX_STATE_BYTES} byte budget.",
                500,
            )
        payload = {
            "model": self._cfg.model,
            "state": state,
            "questions": question_payload(questions),
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
        encoded = body.encode("utf-8")
        if len(encoded) > MAX_REQUEST_BYTES:
            raise SystemOneError(
                SYSTEMONE_INVALID_RESPONSE,
                f"The System 1 request exceeded the {MAX_REQUEST_BYTES} byte budget.",
                500,
            )
        return encoded

    async def ask(
        self,
        state: dict[str, Any],
        questions: tuple[SystemOneQuestion, ...],
    ) -> SystemOneResponse:
        self._check_ready()
        body = self.build_request_body(state, questions)
        url = f"{self._cfg.base_url}{SYSTEMONE_PATH}"

        started = time.perf_counter()
        try:
            async with self._client() as client:
                response = await client.post(url, content=body, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise SystemOneError(
                SYSTEMONE_TIMEOUT,
                f"System 1 did not answer within {self._cfg.timeout_seconds:.0f}s. "
                "Local Laya should answer in milliseconds — check that Ollama/laya-serve is warm.",
                504,
            ) from exc
        except httpx.HTTPError as exc:
            raise SystemOneError(
                SYSTEMONE_UNREACHABLE,
                f"Cannot reach System 1 at {self._cfg.base_url}. Start `ollama serve` "
                "or `laya-serve`, or disable System 1 in AI settings.",
                502,
            ) from exc
        latency_ms = int(round((time.perf_counter() - started) * 1000))

        if response.status_code in (401, 403):
            raise SystemOneError(
                SYSTEMONE_UNAUTHORIZED,
                "System 1 rejected the API key (HTTP 401). Check the key in AI settings.",
                401,
            )
        if response.status_code >= 400:
            detail = _safe_error_detail(response)
            raise SystemOneError(
                SYSTEMONE_INVALID_RESPONSE,
                f"System 1 returned HTTP {response.status_code}.{detail}",
                502,
            )

        try:
            parsed = response.json()
        except ValueError as exc:
            raise SystemOneError(
                SYSTEMONE_INVALID_RESPONSE, "System 1 returned a non-JSON response.", 502
            ) from exc

        return parse_systemone_response(parsed, model_default=self._cfg.model, latency_ms=latency_ms)


async def test_connection(cfg: SystemOneConfig) -> ConnectionProbe:
    """Minimal one-question ping used by the settings drawer."""
    if not cfg.enabled:
        return ConnectionProbe(
            reachable=False,
            latency_ms=0,
            model=cfg.model,
            provider_hint=cfg.provider_hint,
            warning="System 1 is disabled; Kodo continues with deterministic rules only.",
            error_code=SYSTEMONE_DISABLED,
        )

    client = SystemOneClient(cfg)
    ping_state = {"kind": "systemone_ping", "protocol": "v1/systemone", "questions": len(PING_QUESTIONS)}
    try:
        response = await client.ask(ping_state, PING_QUESTIONS)
    except SystemOneError as exc:
        return ConnectionProbe(
            reachable=False,
            latency_ms=0,
            model=cfg.model,
            provider_hint=cfg.provider_hint,
            warning=exc.message,
            error_code=exc.code,
        )

    warning = None
    if response.abstain or response.selected("reachability") == "unreachable":
        warning = "System 1 answered but abstained on the reachability ping."
    return ConnectionProbe(
        reachable=True,
        latency_ms=response.latency_ms,
        model=response.model or cfg.model,
        provider_hint=cfg.provider_hint,
        warning=warning,
    )


def _safe_error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    error = body.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return f" Provider said: {error['message'][:200]}"
    if isinstance(error, str):
        return f" Provider said: {error[:200]}"
    return ""


__all__ = [
    "ConnectionProbe",
    "MAX_REQUEST_BYTES",
    "QuestionAnswer",
    "SYSTEMONE_PATH",
    "SystemOneClient",
    "SystemOneResponse",
    "get_transport_override",
    "parse_systemone_response",
    "set_transport_override",
    "test_connection",
]
