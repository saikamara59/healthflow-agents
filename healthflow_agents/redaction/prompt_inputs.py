"""Typed prompt inputs for the agent layer — the single PHI redaction boundary.

Every agent's `_build_prompt` method accepts ONLY one of these models. There
is no code path from a raw string to a prompt body that does not pass through
a PromptInput constructor: free-text fields are redacted by a
`mode="before"` validator during construction, and the models are frozen, so
a redacted value cannot be replaced with a raw one afterward.

Three of the five (Comparison, Cost, Network) have no free-text fields — they
are typed wrappers that enforce the contract uniformly and make the layer
ready for the day someone adds a free-text field.

See docs/2026-05-14-phi-redaction-design.md for the threat model (no BAA
assumed: redact patient identifiers, allow de-identified medical content like
medication/procedure names and doctor names/NPIs).
"""
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from healthflow_agents.redaction.phi_redactor import PHIRedactor

# Module-level singleton — PHIRedactor compiles its regexes at class-definition
# time, so constructing one per call would be wasteful.
_REDACTOR = PHIRedactor()


def _redact_field(text: str) -> tuple[str, list[dict]]:
    """Redact PHI from a free-text field.

    Returns (redacted_text, redaction_log). The log is a list of dicts with
    'placeholder', 'pattern', 'position' keys — see PHIRedactor.redact.
    """
    return _REDACTOR.redact(text)


def _summarize(log: list[dict]) -> dict:
    """Turn a redaction log into a compact summary for the audit logger."""
    return {
        "count": len(log),
        "types": sorted({entry["placeholder"] for entry in log}),
    }


class _FrozenPromptInput(BaseModel):
    """Base for all PromptInputs: immutable after construction."""

    model_config = ConfigDict(frozen=True)


class RedactedSection(_FrozenPromptInput):
    """A document section whose content has already been redacted.

    `title` is assumed safe (section headings, not patient data). `content`
    is redacted by the TranslationPromptInput validator before a
    RedactedSection is stored.
    """

    title: str
    content: str


class TranslationPromptInput(_FrozenPromptInput):
    """Input for TranslationAgent._build_prompt. Redacts question + section content."""

    sections: tuple[RedactedSection, ...]
    question: str
    # Populated by the validator; excluded from dumps so redaction metadata
    # (positions) never rides along with serialized prompt inputs.
    redaction_log: list[dict] = Field(default_factory=list, repr=False, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _redact_free_text(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        log: list[dict] = []

        question = data.get("question")
        if isinstance(question, str):
            q_redacted, q_log = _redact_field(question)
            data["question"] = q_redacted
            log.extend(q_log)

        sections = data.get("sections")
        if sections is not None:
            redacted_sections = []
            for section in sections:
                title = section["title"] if isinstance(section, dict) else section.title
                content = section["content"] if isinstance(section, dict) else section.content
                c_redacted, c_log = _redact_field(content)
                redacted_sections.append(RedactedSection(title=title, content=c_redacted))
                log.extend(c_log)
            data["sections"] = tuple(redacted_sections)

        data["redaction_log"] = log
        return data

    @property
    def redaction_summary(self) -> dict:
        return _summarize(self.redaction_log)


class AppealPromptInput(_FrozenPromptInput):
    """Input for AppealAgent. The single redaction boundary for the appeal flow.

    The constructor accepts ONLY raw `denial_text` / `additional_context`;
    the validator redacts them and discards the raw values — only
    `redacted_denial` / `redacted_context` persist on the instance. Passing
    `redacted_*` directly is rejected so pre-"redacted" text can't bypass the
    boundary. `process_appeal` consumes `redacted_denial` for BOTH the denial
    parser and the Claude refine prompt — this model is not prompt-only.
    """

    redacted_denial: str
    redacted_context: str
    redaction_log: list[dict] = Field(default_factory=list, repr=False, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _redact_constructor_inputs(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        supplied = set(data) & {"redacted_denial", "redacted_context", "redaction_log"}
        if supplied:
            raise ValueError(
                f"AppealPromptInput computes {sorted(supplied)} itself; "
                "pass raw denial_text / additional_context only"
            )
        if "denial_text" not in data or "additional_context" not in data:
            raise ValueError("denial_text and additional_context are required")

        log: list[dict] = []
        denial_redacted, denial_log = _redact_field(data["denial_text"])
        log.extend(denial_log)
        context_redacted, context_log = _redact_field(data["additional_context"])
        log.extend(context_log)
        return {
            "redacted_denial": denial_redacted,
            "redacted_context": context_redacted,
            "redaction_log": log,
        }

    @property
    def redaction_summary(self) -> dict:
        return _summarize(self.redaction_log)


class ComparisonPromptInput(_FrozenPromptInput):
    """Input for ComparisonAgent._build_prompt. No free-text fields — typed wrapper."""

    plans: list[Any]            # list[PlanSummary] in production
    age: int
    income_level: str
    medications: list[str]
    procedures: list[str]

    @property
    def redaction_summary(self) -> dict:
        return {"count": 0, "types": []}


class CostPromptInput(_FrozenPromptInput):
    """Input for CostCalculatorAgent._build_prompt. No free-text fields — typed wrapper."""

    results: list[Any]          # list[PlanCostResult] in production
    usage: Any                  # UsageInput in production

    @property
    def redaction_summary(self) -> dict:
        return {"count": 0, "types": []}


class NetworkPromptInput(_FrozenPromptInput):
    """Input for NetworkAgent._build_prompt. No free-text fields — typed wrapper.

    Wraps `plan_results` (list[PlanNetworkResult]) — what _build_prompt actually
    consumes. Provider names + NPIs inside plan_results are professional
    identifiers (public NPPES registry data), not patient PHI, so they pass
    through by design.
    """

    plan_results: list[Any]     # list[PlanNetworkResult] in production

    @property
    def redaction_summary(self) -> dict:
        return {"count": 0, "types": []}
