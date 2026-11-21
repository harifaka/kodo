"""Async OpenAI-compatible client for DeepSeek Cloud and air-gapped Ollama / vLLM servers.

Only ``/chat/completions`` and ``/models`` are used, so any OpenAI-compatible server works by
changing the Base URL. API keys are attached to the outgoing request only: they are never logged,
returned or persisted.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.llm.config import LlmConfig, is_local_base_url
from app.llm.errors import LlmError

_THINK_BLOCK = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.IGNORECASE | re.DOTALL)
_FENCE = re.compile(r"```[A-Za-z0-9_+.-]*[ \t]*\r?\n?(.*?)```", re.DOTALL)
_OPENING_FENCE = re.compile(r"^\s*```[A-Za-z0-9_+.-]*[ \t]*\r?\n?", re.MULTILINE)

# Tests inject an httpx.MockTransport here so the whole suite runs without network access.
_transport_override: httpx.AsyncBaseTransport | None = None


def set_transport_override(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport_override
    _transport_override = transport


def get_transport_override() -> httpx.AsyncBaseTransport | None:
    return _transport_override


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str

    def to_payload(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class Completion:
    content: str
    model: str


def strip_reasoning(text: str) -> str:
    """Drop ``<think>…</think>`` blocks that DeepSeek-R1 style models prepend to the answer."""
    return _THINK_BLOCK.sub("", text).strip()


def strip_code_fences(text: str) -> str:
    """Unwrap ```json … ``` (or bare ```) that local models wrap JSON in."""
    match = _FENCE.search(text)
    if match:
        return match.group(1).strip()
    return _OPENING_FENCE.sub("", text).strip().removesuffix("```").strip()


def parse_llm_json(content: str) -> Any:
    """Parse model output into JSON, tolerating reasoning blocks, fences and surrounding prose."""
    cleaned = strip_code_fences(strip_reasoning(content))

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Last resort: the outermost balanced object/array inside the answer.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue

    raise LlmError(
        "INVALID_JSON",
        "The model did not return valid JSON. Try again, or switch to a model that follows JSON instructions.",
        422,
    )


class LlmClient:
    def __init__(self, cfg: LlmConfig, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._cfg = cfg
        self._transport = transport if transport is not None else _transport_override

    @property
    def config(self) -> LlmConfig:
        return self._cfg

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._cfg.api_key:
            headers["Authorization"] = f"Bearer {self._cfg.api_key}"
        return headers

    def _check_ready(self) -> None:
        if not self._cfg.base_url.startswith(("http://", "https://")):
            raise LlmError(
                "INVALID_BASE_URL",
                f"Base URL '{self._cfg.base_url}' must start with http:// or https://.",
                400,
            )
        if not self._cfg.api_key and not is_local_base_url(self._cfg.base_url):
            raise LlmError(
                "MISSING_API_KEY",
                "No API key configured. Open the AI Copilot settings and paste a DeepSeek API key, "
                "or point the Base URL at a local Ollama/vLLM server.",
                401,
            )

    def _url(self, path: str) -> str:
        return f"{self._cfg.base_url}{path}"

    def _client(self) -> httpx.AsyncClient:
        timeout = httpx.Timeout(self._cfg.timeout_seconds, connect=min(10.0, self._cfg.timeout_seconds))
        return httpx.AsyncClient(timeout=timeout, transport=self._transport, follow_redirects=False)

    def _raise_for_status(self, response: httpx.Response, action: str) -> None:
        if response.status_code < 400:
            return

        status = response.status_code
        if status in (401, 403):
            raise LlmError(
                "UNAUTHORIZED",
                "The LLM provider rejected the API key (HTTP 401). Check the key in AI Copilot settings.",
                401,
            )
        if status == 429:
            raise LlmError(
                "RATE_LIMITED",
                "The LLM provider is rate limiting requests (HTTP 429). Retry in a moment.",
                429,
            )
        summary = _safe_error_detail(response)
        raise LlmError(
            "PROVIDER_ERROR",
            f"The LLM provider returned HTTP {status} while trying to {action}.{summary}",
            502,
        )

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        json_mode: bool = True,
        max_tokens: int | None = None,
    ) -> Completion:
        self._check_ready()
        payload: dict[str, Any] = {
            "model": model or self._cfg.code_model,
            "messages": [message.to_payload() for message in messages],
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        response = await self._post_chat(payload)
        # Some local servers reject response_format outright; retry once without JSON mode.
        if response.status_code == 400 and json_mode and _mentions_response_format(response):
            payload.pop("response_format", None)
            response = await self._post_chat(payload)

        self._raise_for_status(response, "generate a completion")
        content = _extract_message_content(response)
        if not content.strip():
            raise LlmError("EMPTY_COMPLETION", "The LLM returned an empty response.", 502)
        return Completion(content=content, model=str(payload["model"]))

    async def _post_chat(self, payload: dict[str, Any]) -> httpx.Response:
        try:
            async with self._client() as client:
                return await client.post(self._url("/chat/completions"), json=payload, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise LlmError(
                "TIMEOUT",
                f"The LLM did not answer within {self._cfg.timeout_seconds:.0f}s. "
                "Retry, or raise the timeout in AI Copilot settings.",
                504,
            ) from exc
        except httpx.HTTPError as exc:
            raise LlmError(
                "UNREACHABLE",
                f"Cannot reach the LLM server at {self._cfg.base_url}. "
                "For local Ollama/vLLM, confirm the server is running and the Base URL ends with /v1.",
                502,
            ) from exc

    async def list_models(self) -> list[str]:
        self._check_ready()
        try:
            async with self._client() as client:
                response = await client.get(self._url("/models"), headers=self._headers())
        except httpx.TimeoutException as exc:
            raise LlmError("TIMEOUT", "The LLM server did not answer the connection check in time.", 504) from exc
        except httpx.HTTPError as exc:
            raise LlmError(
                "UNREACHABLE",
                f"Cannot reach the LLM server at {self._cfg.base_url}. "
                "For local Ollama/vLLM, confirm the server is running and the Base URL ends with /v1.",
                502,
            ) from exc

        self._raise_for_status(response, "list the available models")
        try:
            body = response.json()
        except ValueError as exc:
            raise LlmError("PROVIDER_ERROR", "The LLM provider returned a non-JSON model list.", 502) from exc

        entries = body.get("data") if isinstance(body, dict) else None
        if not isinstance(entries, list):
            return []
        return sorted(str(item.get("id")) for item in entries if isinstance(item, dict) and item.get("id"))


def _extract_message_content(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError as exc:
        raise LlmError("PROVIDER_ERROR", "The LLM provider returned a non-JSON response.", 502) from exc

    choices = body.get("choices") if isinstance(body, dict) else None
    if not isinstance(choices, list) or not choices:
        raise LlmError("PROVIDER_ERROR", "The LLM response contained no completion choices.", 502)

    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise LlmError("PROVIDER_ERROR", "The LLM response contained no assistant message.", 502)

    content = message.get("content")
    if isinstance(content, str):
        return content
    # Some servers return content parts instead of a plain string.
    if isinstance(content, list):
        return "".join(
            str(part.get("text", "")) for part in content if isinstance(part, dict)
        )
    return ""


def _safe_error_detail(response: httpx.Response) -> str:
    """Short, key-free provider message appended to a structured error."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    error = body.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return f" Provider said: {error['message'][:300]}"
    if isinstance(error, str):
        return f" Provider said: {error[:300]}"
    return ""


def _mentions_response_format(response: httpx.Response) -> bool:
    return "response_format" in response.text


__all__ = [
    "ChatMessage",
    "Completion",
    "LlmClient",
    "get_transport_override",
    "parse_llm_json",
    "set_transport_override",
    "strip_code_fences",
    "strip_reasoning",
]
