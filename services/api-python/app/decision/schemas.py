"""Typed `/v1/systemone` question sets.

Laya is a non-autoregressive decision model: it never generates text. Each question is a short,
self-contained English instruction with a small, explicit answer space. Choices stay well below the
~20-option ceiling, and every set ends with an explicit neutral/safe fallback so the model can always
abstain instead of forcing a guess.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

QuestionType = Literal["choice", "noul", "score"]

MAX_CHOICE_OPTIONS = 12
# Keys that mean "do not act automatically" — at least one must exist on every choice question.
NEUTRAL_KEYS = frozenset(
    {
        "uncertain",
        "human_review",
        "careful_manual_review",
        "ignore_benign",
        "escalate_human_review",
        "unreachable",
    }
)


class SystemOneOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(..., min_length=1, max_length=64)
    description: str = Field(..., min_length=1, max_length=240)


class SystemOneQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=64)
    type: QuestionType = "choice"
    text: str = Field(..., min_length=1, max_length=600)
    options: list[SystemOneOption] = Field(default_factory=list, max_length=MAX_CHOICE_OPTIONS)


def _q(
    question_id: str,
    text: str,
    options: list[tuple[str, str]],
) -> SystemOneQuestion:
    return SystemOneQuestion(
        id=question_id,
        type="choice",
        text=text,
        options=[SystemOneOption(key=key, description=description) for key, description in options],
    )


AUDIT_TRIAGE_QUESTIONS: tuple[SystemOneQuestion, ...] = (
    _q(
        "risk_level",
        (
            "You triage one deterministic architecture-audit finding for a software team. "
            "Judge the real architectural risk, not the severity label. Pick one:"
        ),
        [
            ("critical_arch_risk", "Breaks a layer boundary, cycle or data exposure a user can hit."),
            ("moderate_maintainability", "Real drift, but contained and safe to schedule."),
            ("low_boilerplate", "Cosmetic or boilerplate-only; no behavioural risk."),
            ("uncertain", "The state is insufficient to judge safely. Neutral fallback."),
        ],
    ),
    _q(
        "fix_route",
        "Which remediation path should Kodo recommend for this finding? Pick one:",
        [
            ("deterministic_ast", "A guarded AST patch fixes it with no model needed."),
            ("template_builder", "Re-scaffold the slice through the deterministic Builder."),
            ("deepseek_refactor", "Needs reasoning; escalate to System 2 DeepSeek."),
            ("human_review", "An architect should decide. Safe neutral fallback."),
            ("ignore_benign", "Benign; leave the code untouched."),
        ],
    ),
    _q(
        "needs_human_design",
        "Does fixing this finding require a human architectural decision (not a mechanical edit)?",
        [
            ("yes_architectural_decision", "Yes: service boundaries or ownership must change."),
            ("no_mechanical_fix", "No: the change is mechanical and reviewable in a diff."),
            ("uncertain", "Not enough signal. Neutral fallback."),
        ],
    ),
)

TASK_ROUTER_QUESTIONS: tuple[SystemOneQuestion, ...] = (
    _q(
        "execution_path",
        (
            "You route one engineering request inside an analysed codebase. "
            "Choose the cheapest path that can complete it correctly. Pick one:"
        ),
        [
            ("deterministic_ast", "Field/annotation/relation edits Kodo can patch deterministically."),
            ("template_builder", "A new vertical slice from the versioned blueprint."),
            ("deepseek_code", "Small code generation; System 2 code model."),
            ("deepseek_reasoning", "Cross-cutting reasoning; System 2 reasoning model."),
            ("human_review", "Ambiguous or high-impact; a human should plan it. Safe fallback."),
            ("uncertain", "Insufficient state to route. Neutral fallback."),
        ],
    ),
    _q(
        "blast_radius",
        "How far does this request reach? Pick one:",
        [
            ("single_file_local", "One file or one component."),
            ("cross_layer_slice", "Several layers of one vertical slice."),
            ("multi_service_arch", "Multiple services or architectural boundaries."),
            ("uncertain", "Scope cannot be determined. Neutral fallback."),
        ],
    ),
    _q(
        "escalate_to_system2",
        "Should Kodo act with System 1/deterministic tools now, or escalate? Pick one:",
        [
            ("act_system1_deterministic", "Act now with deterministic tools only."),
            ("escalate_system2_deepseek", "Escalate to the DeepSeek System 2 model."),
            ("escalate_human_review", "Escalate to a human. Safe fallback."),
        ],
    ),
)

DIFF_SAFETY_QUESTIONS: tuple[SystemOneQuestion, ...] = (
    _q(
        "logic_deletion_risk",
        (
            "You review a proposed code diff before a human sees it. "
            "Does the diff delete or weaken existing business logic? Pick one:"
        ),
        [
            ("safe_preserved", "Existing statements and signatures are preserved."),
            ("possible_logic_loss", "Statements, branches or methods were removed or weakened."),
            ("uncertain", "Cannot tell from the summary. Neutral fallback."),
        ],
    ),
    _q(
        "layer_boundary_risk",
        "Does the diff cross architecture layer boundaries incorrectly? Pick one:",
        [
            ("clean_boundaries", "Every change stays inside its own layer."),
            ("possible_layer_violation", "A controller/repository/entity boundary is crossed."),
            ("uncertain", "Cannot tell from the summary. Neutral fallback."),
        ],
    ),
    _q(
        "review_priority",
        "How carefully should a human review this diff? Pick one:",
        [
            ("routine_quick_check", "Routine mechanical change; a quick check is enough."),
            ("careful_manual_review", "Read every hunk carefully. Neutral fallback."),
            ("high_risk_block_advised", "Block the apply until an architect reviews it."),
        ],
    ),
)

PING_QUESTIONS: tuple[SystemOneQuestion, ...] = (
    _q(
        "reachability",
        "Reply ok when you can read this state. Pick one:",
        [
            ("ok", "The decision endpoint is serving requests."),
            ("unreachable", "The endpoint cannot answer. Neutral fallback."),
        ],
    ),
)

QUESTION_SETS: dict[str, tuple[SystemOneQuestion, ...]] = {
    "audit_triage": AUDIT_TRIAGE_QUESTIONS,
    "task_route": TASK_ROUTER_QUESTIONS,
    "diff_safety": DIFF_SAFETY_QUESTIONS,
}


def validate_question_set(questions: tuple[SystemOneQuestion, ...]) -> None:
    """Deterministic guard: unique ids, bounded choices, an explicit neutral fallback."""
    seen: set[str] = set()
    if not questions:
        raise ValueError("A System 1 question set must not be empty.")
    for question in questions:
        if question.id in seen:
            raise ValueError(f"Duplicate System 1 question id: {question.id}")
        seen.add(question.id)
        if question.type != "choice":
            continue
        if len(question.options) < 2:
            raise ValueError(f"Question {question.id} needs at least two options.")
        if len(question.options) > MAX_CHOICE_OPTIONS:
            raise ValueError(f"Question {question.id} exceeds {MAX_CHOICE_OPTIONS} options.")
        keys = {option.key for option in question.options}
        if len(keys) != len(question.options):
            raise ValueError(f"Question {question.id} contains duplicate option keys.")
        if not keys & NEUTRAL_KEYS:
            raise ValueError(f"Question {question.id} needs an explicit neutral fallback option.")


for _question_set in (*QUESTION_SETS.values(), PING_QUESTIONS):
    validate_question_set(_question_set)


def question_payload(questions: tuple[SystemOneQuestion, ...]) -> list[dict[str, object]]:
    """Wire form sent to `POST /v1/systemone`, preserving the declared order."""
    return [
        {
            "id": question.id,
            "type": question.type,
            "text": question.text,
            "options": [
                {"key": option.key, "description": option.description} for option in question.options
            ],
        }
        for question in questions
    ]


def questions_for(decision_type: str) -> tuple[SystemOneQuestion, ...]:
    return QUESTION_SETS.get(decision_type, ())


__all__ = [
    "AUDIT_TRIAGE_QUESTIONS",
    "DIFF_SAFETY_QUESTIONS",
    "MAX_CHOICE_OPTIONS",
    "NEUTRAL_KEYS",
    "PING_QUESTIONS",
    "QUESTION_SETS",
    "TASK_ROUTER_QUESTIONS",
    "SystemOneOption",
    "SystemOneQuestion",
    "question_payload",
    "questions_for",
    "validate_question_set",
]
