"""BatchRunner — per-record isolation, audit flow, summary math."""
import pytest

from helpers import RecordingAuditSink, RecordingInvocationTracker, make_mock_client

from healthflow_agents.agents.appeal_agent import AppealAgent
from healthflow_agents.batch import BatchRunner, summarize_outcomes
from healthflow_agents.contracts.denial_record import BatchResult
from healthflow_agents.tools.remittance_parser import make_synthetic_denials


def make_agent(**kwargs) -> AppealAgent:
    return AppealAgent(client=make_mock_client("REFINED"), **kwargs)


def test_batch_processes_all_records_successfully():
    records = make_synthetic_denials(6, seed=11)
    result = BatchRunner(make_agent()).run(records)

    assert isinstance(result, BatchResult)
    assert result.summary.total_records == 6
    assert result.summary.succeeded == 6
    assert result.summary.failed == 0
    for outcome in result.outcomes:
        assert outcome.success
        assert outcome.appeal is not None
        assert outcome.appeal.refined_recommendation == "REFINED"
        assert outcome.error_type is None
    # Outcomes preserve input order.
    assert [o.record.claim_id for o in result.outcomes] == [r.claim_id for r in records]


def test_one_failing_record_does_not_kill_the_batch():
    records = make_synthetic_denials(5, seed=12)
    agent = make_agent()

    # Third Claude call blows up; every other record still processes.
    good_response = agent.client.messages.create.return_value
    agent.client.messages.create.side_effect = [
        good_response,
        good_response,
        RuntimeError("payer API meltdown"),
        good_response,
        good_response,
    ]

    result = BatchRunner(agent).run(records)

    assert result.summary.succeeded == 4
    assert result.summary.failed == 1
    failed = [o for o in result.outcomes if not o.success]
    assert len(failed) == 1
    assert failed[0].record.claim_id == records[2].claim_id
    assert failed[0].error_type == "RuntimeError"
    assert "payer API meltdown" in failed[0].error_message
    assert failed[0].appeal is None


def test_batch_flows_through_injected_audit_and_tracker():
    audit = RecordingAuditSink()
    tracker = RecordingInvocationTracker()
    agent = make_agent(audit_sink=audit, invocation_tracker=tracker)
    records = make_synthetic_denials(2, seed=13)

    BatchRunner(agent).run(records)

    events = audit.event_types()
    assert events[0] == "batch_started"
    assert events[-1] == "batch_completed"
    # Each record emitted its full per-record stream in between.
    assert events.count("phi_redacted") == 2
    assert events.count("appeal_generated") == 2
    # One batch-level invocation plus one per record.
    assert [c["event_type"] for c in tracker.calls] == [
        "run_batch",
        "process_denial_record",
        "process_denial_record",
    ]


def test_record_failed_audit_event_emitted():
    audit = RecordingAuditSink()
    agent = make_agent(audit_sink=audit)
    agent.client.messages.create.side_effect = RuntimeError("boom")
    records = make_synthetic_denials(1, seed=14)

    result = BatchRunner(agent).run(records)

    assert result.summary.failed == 1
    failed_events = [d for e, d in audit.events if e == "record_failed"]
    assert len(failed_events) == 1
    assert failed_events[0]["claim_id"] == records[0].claim_id
    assert "RuntimeError" in failed_events[0]["error"]


def test_summary_math_and_carc_grouping():
    records = make_synthetic_denials(30, seed=15)
    result = BatchRunner(make_agent()).run(records)

    s = result.summary
    assert s.total_billed_amount == round(sum(r.billed_amount for r in records), 2)
    assert sum(s.records_by_carc.values()) == 30
    assert set(s.records_by_carc) == {r.carc_code for r in records}
    for carc, dollars in s.billed_by_carc.items():
        expected = round(
            sum(r.billed_amount for r in records if r.carc_code == carc), 2
        )
        assert dollars == pytest.approx(expected, abs=0.01)


def test_summarize_outcomes_empty_batch():
    s = summarize_outcomes([])
    assert s.total_records == 0
    assert s.total_billed_amount == 0.0
    assert s.records_by_carc == {}


def test_concurrency_reserved_but_not_implemented():
    with pytest.raises(NotImplementedError):
        BatchRunner(make_agent(), max_concurrency=4)
