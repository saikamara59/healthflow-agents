"""BatchInsightsAgent tests — the whole agent path, offline.

Every test drives the public seam: build Batch Aggregates, hand the agent an
injected stub client, assert on the returned narrative, the raised error, or
the emitted events. The user prompt is asserted only through the committed
golden in tests/goldens/batch_insights.json.
"""
import json
import re
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from helpers import RecordingAuditSink, RecordingInvocationTracker

from healthflow_agents import DRY_RUN_NARRATIVE
from healthflow_agents.agents.batch_insights_agent import (
    INSIGHTS_SECTION_HEADINGS,
    BatchInsightsAgent,
)
from healthflow_agents.contracts import (
    BatchAggregates,
    BatchTotals,
    CarcAggregate,
    DeadlineBuckets,
    PayerAggregate,
)

GOLDENS = json.loads(
    (Path(__file__).parent / "goldens" / "batch_insights.json").read_text()
)

# CO-16 is in the curated DenialCodeDB (enriched with its description);
# XX-999 is not (falls back to the bare code).
SAMPLE_AGGREGATES = BatchAggregates(
    totals=BatchTotals(
        records=120,
        billed_amount=248500.50,
        drafted=40,
        failed=5,
        submitted=30,
        dismissed=10,
    ),
    by_payer=[
        PayerAggregate(payer="Aetna", records=62, billed_amount=130250.25),
        PayerAggregate(payer="UnitedHealthcare", records=58, billed_amount=118250.25),
    ],
    by_carc=[
        CarcAggregate(carc_code="CO-16", records=70, billed_amount=140000.00),
        CarcAggregate(carc_code="XX-999", records=50, billed_amount=108500.50),
    ],
    deadlines=DeadlineBuckets(
        overdue=3,
        due_within_7_days=9,
        due_7_to_30_days=41,
        due_beyond_30_days=60,
        unknown=7,
    ),
    dismissals_by_reason={"payer_correct": 6, "too_small": 3, "other": 1},
    service_date_start=date(2026, 1, 4),
    service_date_end=date(2026, 3, 29),
)

MINIMAL_AGGREGATES = BatchAggregates(
    totals=BatchTotals(
        records=1,
        billed_amount=0.0,
        drafted=0,
        failed=0,
        submitted=0,
        dismissed=0,
    ),
    by_payer=[],
    by_carc=[],
    deadlines=DeadlineBuckets(
        overdue=0,
        due_within_7_days=0,
        due_7_to_30_days=0,
        due_beyond_30_days=0,
        unknown=1,
    ),
    dismissals_by_reason={},
    service_date_start=None,
    service_date_end=None,
)


def make_agent(
    response_text: str = DRY_RUN_NARRATIVE,
    stop_reason: str = "end_turn",
    **kwargs,
) -> tuple[BatchInsightsAgent, MagicMock]:
    """Agent wired to a stub client returning `response_text`."""
    stub_client = MagicMock()
    stub_response = MagicMock()
    stub_response.content = [MagicMock(text=response_text)]
    stub_response.stop_reason = stop_reason
    stub_client.messages.create.return_value = stub_response
    return BatchInsightsAgent(client=stub_client, **kwargs), stub_client


# --- Primary seam: aggregates in, narrative out ---


def test_generate_insights_returns_the_canned_narrative():
    agent, _ = make_agent()

    narrative = agent.generate_insights(SAMPLE_AGGREGATES)

    assert narrative == DRY_RUN_NARRATIVE


def test_generate_insights_uses_the_standard_call_shape():
    agent, stub_client = make_agent()

    agent.generate_insights(SAMPLE_AGGREGATES)

    call = stub_client.messages.create.call_args
    assert call.kwargs["model"] == BatchInsightsAgent.model
    assert call.kwargs["max_tokens"] == 1024
    assert call.kwargs["system"] == agent.system_prompt
    assert [m["role"] for m in call.kwargs["messages"]] == ["user"]


def test_constructor_parity_with_existing_agents():
    """client / audit sink / invocation tracker are all injectable kwargs."""
    audit = RecordingAuditSink()
    tracker = RecordingInvocationTracker()

    agent, _ = make_agent(audit_sink=audit, invocation_tracker=tracker)

    assert agent.audit is audit
    assert agent.invocations is tracker
    assert agent.agent_name == "batch_insights"


# --- Golden: the built user prompt, CARC enrichment included ---


def test_system_prompt_matches_golden():
    agent, _ = make_agent()

    assert agent.system_prompt == GOLDENS["system_prompt"]


def test_user_prompt_matches_golden():
    agent, stub_client = make_agent()

    agent.generate_insights(SAMPLE_AGGREGATES)

    user_prompt = stub_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert user_prompt == GOLDENS["user_prompt"]


def test_user_prompt_enriches_known_carc_codes_and_falls_back_on_unknown():
    agent, stub_client = make_agent()

    agent.generate_insights(SAMPLE_AGGREGATES)

    user_prompt = stub_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert (
        "CO-16 (Claim/service lacks information or has submission/billing error(s))"
        in user_prompt
    )
    # Unknown code travels bare — no invented description.
    assert "XX-999:" in user_prompt
    assert "XX-999 (" not in user_prompt


def test_user_prompt_is_deterministic():
    agent_a, client_a = make_agent()
    agent_b, client_b = make_agent()

    agent_a.generate_insights(SAMPLE_AGGREGATES)
    agent_b.generate_insights(SAMPLE_AGGREGATES)

    assert (
        client_a.messages.create.call_args.kwargs["messages"][0]["content"]
        == client_b.messages.create.call_args.kwargs["messages"][0]["content"]
    )


def test_empty_dimensions_and_absent_service_dates_build_a_prompt():
    agent, stub_client = make_agent()

    agent.generate_insights(MINIMAL_AGGREGATES)

    user_prompt = stub_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert user_prompt == GOLDENS["user_prompt_minimal"]


# --- Failure semantics ---


def test_empty_response_raises_value_error():
    agent, _ = make_agent(response_text="   ")

    with pytest.raises(ValueError, match="empty"):
        agent.generate_insights(SAMPLE_AGGREGATES)


def test_truncated_response_raises_value_error():
    agent, _ = make_agent(stop_reason="max_tokens")

    with pytest.raises(ValueError, match="truncated"):
        agent.generate_insights(SAMPLE_AGGREGATES)


def test_response_without_a_stop_reason_attribute_passes_the_guard():
    """Canned clients need not model stop_reason — the guard is defensive."""

    class CannedBlock:
        text = DRY_RUN_NARRATIVE

    class CannedResponse:
        content = [CannedBlock()]

    class CannedClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                return CannedResponse()

    agent = BatchInsightsAgent(client=CannedClient())

    assert agent.generate_insights(SAMPLE_AGGREGATES) == DRY_RUN_NARRATIVE


def test_sdk_errors_propagate_untouched():
    agent, stub_client = make_agent()
    stub_client.messages.create.side_effect = RuntimeError("connection reset")

    with pytest.raises(RuntimeError, match="connection reset"):
        agent.generate_insights(SAMPLE_AGGREGATES)


# --- Observability ---


def test_audit_and_invocation_events_follow_convention():
    audit = RecordingAuditSink()
    tracker = RecordingInvocationTracker()
    agent, _ = make_agent(audit_sink=audit, invocation_tracker=tracker)

    agent.generate_insights(SAMPLE_AGGREGATES)

    assert audit.event_types() == ["tool_called", "insights_generated"]
    tool_called = dict(audit.events)["tool_called"]
    assert tool_called == {"tool": "claude_api", "model": BatchInsightsAgent.model}
    assert dict(audit.events)["insights_generated"]["length"] == len(DRY_RUN_NARRATIVE)

    assert tracker.calls == [
        {
            "agent": "batch_insights",
            "event_type": "generate_insights",
            "model": BatchInsightsAgent.model,
        }
    ]
    assert tracker.records[0].details["length"] == len(DRY_RUN_NARRATIVE)


def test_no_redaction_event_is_emitted():
    """Nothing crosses the redaction boundary — ADR 0001."""
    audit = RecordingAuditSink()
    agent, _ = make_agent(audit_sink=audit)

    agent.generate_insights(SAMPLE_AGGREGATES)

    assert "phi_redacted" not in audit.event_types()


def test_failures_emit_no_success_event():
    audit = RecordingAuditSink()
    agent, _ = make_agent(response_text="", audit_sink=audit)

    with pytest.raises(ValueError):
        agent.generate_insights(SAMPLE_AGGREGATES)

    assert "insights_generated" not in audit.event_types()


# --- DRY_RUN_NARRATIVE compliance ---


def test_dry_run_narrative_carries_a_dry_run_label():
    first_line = DRY_RUN_NARRATIVE.strip().splitlines()[0]
    assert "dry run" in first_line.lower()


def test_dry_run_narrative_has_exactly_the_three_mandated_sections():
    headings = re.findall(r"^#+ +(.*)$", DRY_RUN_NARRATIVE, flags=re.MULTILINE)

    assert headings == list(INSIGHTS_SECTION_HEADINGS)


def test_dry_run_narrative_uses_only_renderer_safe_markdown():
    body = re.sub(r"\*\*[^*\n]+\*\*", "", DRY_RUN_NARRATIVE)  # drop bold spans

    assert "*" not in body, "no italics or asterisk bullets"
    assert "_" not in body, "no underscore emphasis"
    assert "`" not in body, "no code spans or fences"
    assert "|" not in body, "no tables"
    assert "](" not in body, "no links or images"
    assert "<" not in body, "no raw HTML"
    for line in DRY_RUN_NARRATIVE.splitlines():
        if line.startswith("#"):
            assert line.startswith("## "), "only level-2 headings"
        assert not re.match(r"^\s+[-0-9]", line), "lists stay flat"


def test_dry_run_narrative_respects_the_word_cap():
    """The placeholder demonstrates the format, so it has to obey the same
    ~350-word cap the prompt imposes on a real narrative."""
    assert len(DRY_RUN_NARRATIVE.split()) <= 350


def test_dry_run_narrative_is_flat_re_exported():
    import healthflow_agents
    from healthflow_agents.agents import DRY_RUN_NARRATIVE as from_agents

    assert healthflow_agents.DRY_RUN_NARRATIVE is from_agents
    assert "DRY_RUN_NARRATIVE" in healthflow_agents.__all__
    assert "BatchInsightsAgent" in healthflow_agents.__all__


# --- The prompt itself states the output contract ---


def test_system_prompt_mandates_the_three_sections_and_the_word_cap():
    agent, _ = make_agent()

    for heading in INSIGHTS_SECTION_HEADINGS:
        assert heading in agent.system_prompt
    assert "350" in agent.system_prompt


def test_system_prompt_restricts_output_to_the_renderer_safe_subset():
    """The markdown restriction is the only thing standing between the model
    and a panel that silently degrades — it must stay stated in the prompt."""
    agent, _ = make_agent()
    prompt = agent.system_prompt.lower()

    for allowed in ("heading", "bold", "list", "paragraph"):
        assert allowed in prompt
    for banned in ("table", "link", "italic", "code", "html"):
        assert banned in prompt
