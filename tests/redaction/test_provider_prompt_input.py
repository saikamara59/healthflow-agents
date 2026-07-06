"""ProviderDenialPromptInput — the provider-side redaction boundary.

New tests only; the existing patient-side PromptInput tests are untouched.
"""
import pytest
from pydantic import ValidationError

from healthflow_agents.redaction.prompt_inputs import ProviderDenialPromptInput


def test_redacts_denial_reason_text():
    pi = ProviderDenialPromptInput(
        denial_reason_text=(
            "Patient: Clara Barton, DOB: 12/25/1949. Service not deemed "
            "medically necessary. Contact us at claims@payer.example.com."
        )
    )
    assert "Clara Barton" not in pi.redacted_reason
    assert "[PATIENT_NAME]" in pi.redacted_reason
    assert "12/25/1949" not in pi.redacted_reason
    assert "[DOB]" in pi.redacted_reason
    assert "claims@payer.example.com" not in pi.redacted_reason
    assert "[EMAIL]" in pi.redacted_reason


def test_redaction_summary_shape():
    pi = ProviderDenialPromptInput(
        denial_reason_text="Patient: Clara Barton denied. DOB: 12/25/1949."
    )
    summary = pi.redaction_summary
    assert set(summary.keys()) == {"count", "types"}
    assert summary["count"] >= 2
    assert set(summary["types"]) >= {"[PATIENT_NAME]", "[DOB]"}
    assert summary["types"] == sorted(summary["types"])


def test_clean_text_passes_through_with_empty_summary():
    pi = ProviderDenialPromptInput(
        denial_reason_text="Charge exceeds fee schedule maximum allowable."
    )
    assert pi.redacted_reason == "Charge exceeds fee schedule maximum allowable."
    assert pi.redaction_summary == {"count": 0, "types": []}


def test_is_frozen():
    pi = ProviderDenialPromptInput(denial_reason_text="Duplicate claim.")
    with pytest.raises(ValidationError):
        pi.redacted_reason = "raw text"


def test_rejects_redacted_field_bypass():
    with pytest.raises(ValidationError):
        ProviderDenialPromptInput(
            denial_reason_text="x",
            redacted_reason="attacker-controlled 'pre-redacted' text",
        )


def test_requires_denial_reason_text():
    with pytest.raises(ValidationError):
        ProviderDenialPromptInput()


def test_never_stores_raw_text():
    raw = "Patient: Clara Barton was denied."
    pi = ProviderDenialPromptInput(denial_reason_text=raw)
    assert "Clara Barton" not in repr(pi)
    assert "Clara Barton" not in str(pi.model_dump())
    assert "Clara Barton" not in pi.model_dump_json()
