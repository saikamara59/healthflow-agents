"""Unit tests for the typed PromptInput layer.

Each agent's prompt-builder accepts only a PromptInput model whose
constructor redacts free-text fields. These tests prove redaction is
applied at construction and structured fields pass through unchanged.
"""
from healthflow_agents.redaction.prompt_inputs import (
    AppealPromptInput,
    ComparisonPromptInput,
    CostPromptInput,
    NetworkPromptInput,
    RedactedSection,
    TranslationPromptInput,
)


# --- Translation: actually redacts ---

def test_translation_prompt_input_redacts_question_and_sections():
    raw_sections = [
        RedactedSection(title="Coverage", content="Patient: John Doe has coverage."),
        RedactedSection(title="Contact", content="Reach them at john@example.com."),
    ]
    pi = TranslationPromptInput(
        sections=tuple(raw_sections),
        question="Does Dear Jane Doe have a copay?",
    )
    assert "John Doe" not in pi.sections[0].content
    assert "[PATIENT_NAME]" in pi.sections[0].content
    assert "john@example.com" not in pi.sections[1].content
    assert "[EMAIL]" in pi.sections[1].content
    assert "Jane Doe" not in pi.question
    assert "[PATIENT_NAME]" in pi.question
    assert pi.sections[0].title == "Coverage"
    summary = pi.redaction_summary
    assert summary["count"] >= 3
    assert "[PATIENT_NAME]" in summary["types"]
    assert "[EMAIL]" in summary["types"]


# --- Appeal: actually redacts ---

def test_appeal_prompt_input_redacts_denial_and_context():
    pi = AppealPromptInput(
        denial_text="Patient: Mary Smith was denied. DOB: 01/02/1955.",
        additional_context="Member ID: ABC-12345 called about this.",
    )
    assert "Mary Smith" not in pi.redacted_denial
    assert "[PATIENT_NAME]" in pi.redacted_denial
    assert "01/02/1955" not in pi.redacted_denial
    assert "[DOB]" in pi.redacted_denial
    assert "ABC-12345" not in pi.redacted_context
    assert "[MEMBER_ID]" in pi.redacted_context
    summary = pi.redaction_summary
    assert summary["count"] >= 3
    assert set(summary["types"]) >= {"[PATIENT_NAME]", "[DOB]", "[MEMBER_ID]"}


def test_appeal_prompt_input_handles_empty_context():
    """Empty additional_context stays empty; denial_text still redacts normally."""
    pi = AppealPromptInput(
        denial_text="Patient: Walt Whitman was denied. DOB: 05/31/1819.",
        additional_context="",
    )
    assert pi.redacted_context == ""
    # denial_text still redacted — count reflects only the denial-text hits.
    assert "Walt Whitman" not in pi.redacted_denial
    assert "[PATIENT_NAME]" in pi.redacted_denial
    assert "[DOB]" in pi.redacted_denial
    assert pi.redaction_summary["count"] >= 2
    assert set(pi.redaction_summary["types"]) >= {"[PATIENT_NAME]", "[DOB]"}


# --- Comparison / Cost / Network: typed wrappers, no free text ---

def test_comparison_prompt_input_passes_structured_fields_through():
    pi = ComparisonPromptInput(
        plans=["plan-a", "plan-b"],
        age=67,
        income_level="low",
        medications=["Metformin", "Lisinopril"],
        procedures=["Annual physical"],
    )
    assert pi.age == 67
    assert pi.income_level == "low"
    assert pi.medications == ["Metformin", "Lisinopril"]
    assert pi.procedures == ["Annual physical"]
    assert pi.redaction_summary == {"count": 0, "types": []}


def test_cost_prompt_input_passes_structured_fields_through():
    pi = CostPromptInput(results=["result-a"], usage="usage-obj")
    assert pi.results == ["result-a"]
    assert pi.usage == "usage-obj"
    assert pi.redaction_summary == {"count": 0, "types": []}


def test_network_prompt_input_passes_structured_fields_through():
    pi = NetworkPromptInput(plan_results=["net-result-a"])
    assert pi.plan_results == ["net-result-a"]
    assert pi.redaction_summary == {"count": 0, "types": []}


# --- Pydantic model invariants (added with the dataclass -> Pydantic port) ---

import pytest
from pydantic import ValidationError


def test_prompt_inputs_are_frozen():
    """Redacted values cannot be replaced with raw ones after construction."""
    pi = AppealPromptInput(denial_text="Patient: Ada Lovelace denied.", additional_context="")
    with pytest.raises(ValidationError):
        pi.redacted_denial = "Patient: Ada Lovelace denied."

    tpi = TranslationPromptInput(sections=(), question="what is the copay?")
    with pytest.raises(ValidationError):
        tpi.question = "raw question"

    section = RedactedSection(title="T", content="C")
    with pytest.raises(ValidationError):
        section.content = "raw"


def test_appeal_prompt_input_rejects_redacted_field_bypass():
    """The only constructor path is raw text in -> redacted fields out;
    supplying redacted_* directly must be rejected, not silently trusted."""
    with pytest.raises(ValidationError):
        AppealPromptInput(
            denial_text="x",
            additional_context="",
            redacted_denial="attacker-controlled 'pre-redacted' text",
        )


def test_appeal_prompt_input_never_stores_raw_text():
    raw = "Patient: Emily Bronte was denied. DOB: 07/30/1818."
    pi = AppealPromptInput(denial_text=raw, additional_context="")
    assert "Emily Bronte" not in repr(pi)
    assert "Emily Bronte" not in str(pi.model_dump())
    assert "Emily Bronte" not in pi.model_dump_json()


def test_redaction_summary_shape_unchanged():
    """HealthFlow's audit consumers depend on this exact payload shape."""
    pi = AppealPromptInput(
        denial_text="Patient: Mark Twain denied. DOB: 11/30/1835.",
        additional_context="",
    )
    summary = pi.redaction_summary
    assert set(summary.keys()) == {"count", "types"}
    assert isinstance(summary["count"], int)
    assert summary["types"] == sorted(summary["types"])
