"""AppealAgent.process_denial_record — the provider-side entry point.

process_appeal is frozen and covered by golden tests; these tests cover only
the new path.
"""
from datetime import date

from helpers import RecordingAuditSink, RecordingInvocationTracker, make_mock_client

from healthflow_agents.agents.appeal_agent import (
    FALLBACK_CMS_RULE,
    AppealAgent,
)
from healthflow_agents.contracts import CoverageArgument, DenialAnalysis
from healthflow_agents.contracts.denial_record import DenialRecord
from healthflow_agents.core.base import load_system_prompt


def make_record(**overrides) -> DenialRecord:
    base = dict(
        claim_id="CLM-2026-042",
        payer="Aetna Medicare Advantage",
        carc_code="CO-50",
        rarc_codes=["N115"],
        denial_reason_text=(
            "Patient: Clara Barton, DOB: 12/25/1949. Not deemed a medical "
            "necessity by the payer."
        ),
        billed_amount=1250.50,
        service_date=date(2026, 4, 1),
        denial_date=date(2026, 4, 20),
        appeal_deadline=date(2026, 6, 19),
    )
    base.update(overrides)
    return DenialRecord(**base)


def test_output_shape_matches_process_appeal():
    agent = AppealAgent(client=make_mock_client("REFINED"))
    analysis, argument, letter, refined = agent.process_denial_record(make_record())

    assert isinstance(analysis, DenialAnalysis)
    assert isinstance(argument, CoverageArgument)
    assert isinstance(letter, str) and letter
    assert refined == "REFINED"


def test_analysis_maps_structured_fields_deterministically():
    agent = AppealAgent(client=make_mock_client())
    analysis, _, _, _ = agent.process_denial_record(make_record())

    assert analysis.denial_reason_code == "CO-50"
    assert analysis.denial_date == "2026-04-20"
    assert analysis.appeal_deadline == "2026-06-19"
    # Free text landed on the analysis only in redacted form.
    assert "Clara Barton" not in analysis.denial_reason
    assert "[PATIENT_NAME]" in analysis.denial_reason


def test_prompt_is_redacted_and_excludes_claim_id():
    mock_client = make_mock_client("Refined advice.")
    agent = AppealAgent(client=mock_client)
    agent.process_denial_record(make_record())

    kwargs = mock_client.messages.create.call_args.kwargs
    sent_prompt = kwargs["messages"][0]["content"]
    assert "Clara Barton" not in sent_prompt
    assert "[PATIENT_NAME]" in sent_prompt
    assert "12/25/1949" not in sent_prompt
    assert "[DOB]" in sent_prompt
    # claim_id is an account-number-class identifier — never sent to Claude.
    assert "CLM-2026-042" not in sent_prompt
    # Structured, non-identifying metadata IS in the prompt.
    assert "CO-50" in sent_prompt
    assert "N115" in sent_prompt
    assert "$1250.50" in sent_prompt


def test_uses_provider_system_prompt_not_patient_prompt():
    mock_client = make_mock_client()
    agent = AppealAgent(client=mock_client)
    agent.process_denial_record(make_record())

    system = mock_client.messages.create.call_args.kwargs["system"]
    assert system == load_system_prompt("appeal_provider.md")
    assert system != agent.system_prompt
    assert "revenue-cycle" in system
    assert "medical advice" in system.lower()


def test_known_carc_uses_denial_code_db():
    agent = AppealAgent(client=make_mock_client())
    _, argument, _, _ = agent.process_denial_record(make_record(carc_code="CO-50"))
    assert argument.cms_rule != FALLBACK_CMS_RULE


def test_unknown_carc_falls_back():
    agent = AppealAgent(client=make_mock_client())
    _, argument, _, _ = agent.process_denial_record(
        make_record(
            carc_code="CO-9999",
            denial_reason_text="Completely novel denial rationale xyzzy.",
        )
    )
    assert argument.cms_rule == FALLBACK_CMS_RULE
    assert len(argument.common_appeal_grounds) > 0


def test_audit_event_stream_and_phi_redacted_payload():
    audit = RecordingAuditSink()
    tracker = RecordingInvocationTracker()
    agent = AppealAgent(
        client=make_mock_client("REFINED"),
        audit_sink=audit,
        invocation_tracker=tracker,
    )
    agent.process_denial_record(make_record())

    assert audit.event_types() == [
        "phi_redacted",
        "denial_record_mapped",
        "tool_called",
        "recommendation_generated",
        "appeal_generated",
    ]
    phi_payload = audit.events[0][1]
    assert set(phi_payload.keys()) == {"count", "types"}
    assert set(phi_payload["types"]) >= {"[PATIENT_NAME]", "[DOB]"}
    assert tracker.calls == [
        {
            "agent": "appeal",
            "event_type": "process_denial_record",
            "model": "claude-opus-4-8",
        }
    ]
    assert tracker.records[0].details["claim_id"] == "CLM-2026-042"
    assert tracker.records[0].details["code_found_in_db"] is True


def test_missing_deadline_maps_to_none_and_not_stated():
    mock_client = make_mock_client()
    agent = AppealAgent(client=mock_client)
    analysis, _, _, _ = agent.process_denial_record(
        make_record(appeal_deadline=None)
    )
    assert analysis.appeal_deadline is None
    sent_prompt = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Appeal deadline: Not stated" in sent_prompt
