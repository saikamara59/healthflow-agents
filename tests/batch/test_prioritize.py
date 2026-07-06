"""Prioritization — pure deadline/dollar ranking, clock as a parameter."""
import inspect
from datetime import date

from healthflow_agents.batch import prioritize
from healthflow_agents.batch.prioritize import days_until_deadline, prioritize_worklist
from healthflow_agents.batch.runner import summarize_outcomes
from healthflow_agents.contracts.denial_record import (
    BatchResult,
    DenialRecord,
    RecordOutcome,
)

TODAY = date(2026, 7, 1)


def make_outcome(
    claim_id: str,
    billed: float,
    deadline: date | None,
    success: bool = True,
) -> RecordOutcome:
    record = DenialRecord(
        claim_id=claim_id,
        payer="UHC",
        carc_code="CO-50",
        denial_reason_text="Not medically necessary.",
        billed_amount=billed,
        service_date=date(2026, 4, 1),
        denial_date=date(2026, 4, 20),
        appeal_deadline=deadline,
    )
    return RecordOutcome(
        record=record,
        success=success,
        error_type=None if success else "RuntimeError",
        error_message=None if success else "boom",
    )


def make_result(*outcomes: RecordOutcome) -> BatchResult:
    return BatchResult(outcomes=list(outcomes), summary=summarize_outcomes(outcomes))


def test_days_until_deadline():
    assert days_until_deadline(
        make_outcome("a", 1, date(2026, 7, 11)).record, today=TODAY
    ) == 10.0
    assert days_until_deadline(
        make_outcome("b", 1, date(2026, 6, 21)).record, today=TODAY
    ) == -10.0
    assert days_until_deadline(
        make_outcome("c", 1, None).record, today=TODAY
    ) == float("inf")


def test_sooner_deadlines_rank_first():
    result = make_result(
        make_outcome("far", 100.0, date(2026, 9, 1)),
        make_outcome("soon", 100.0, date(2026, 7, 5)),
        make_outcome("mid", 100.0, date(2026, 8, 1)),
    )
    ranked = prioritize_worklist(result, today=TODAY)
    assert [o.record.claim_id for o in ranked] == ["soon", "mid", "far"]


def test_overdue_records_rank_most_urgent():
    result = make_result(
        make_outcome("upcoming", 100.0, date(2026, 7, 10)),
        make_outcome("overdue", 100.0, date(2026, 6, 15)),
    )
    ranked = prioritize_worklist(result, today=TODAY)
    assert ranked[0].record.claim_id == "overdue"


def test_equal_deadlines_break_ties_by_dollars_descending():
    same_day = date(2026, 7, 20)
    result = make_result(
        make_outcome("small", 250.0, same_day),
        make_outcome("large", 42_000.0, same_day),
        make_outcome("medium", 5_000.0, same_day),
    )
    ranked = prioritize_worklist(result, today=TODAY)
    assert [o.record.claim_id for o in ranked] == ["large", "medium", "small"]


def test_no_deadline_ranks_last_ordered_by_dollars():
    result = make_result(
        make_outcome("dated", 10.0, date(2026, 12, 31)),
        make_outcome("undated-small", 100.0, None),
        make_outcome("undated-large", 9_000.0, None),
    )
    ranked = prioritize_worklist(result, today=TODAY)
    assert [o.record.claim_id for o in ranked] == [
        "dated",
        "undated-large",
        "undated-small",
    ]


def test_failed_records_rank_by_the_same_rules():
    result = make_result(
        make_outcome("ok", 100.0, date(2026, 8, 1)),
        make_outcome("failed-urgent", 100.0, date(2026, 7, 3), success=False),
    )
    ranked = prioritize_worklist(result, today=TODAY)
    assert ranked[0].record.claim_id == "failed-urgent"


def test_ranking_is_a_pure_function_of_today():
    result = make_result(
        make_outcome("a", 50_000.0, date(2026, 7, 2)),
        make_outcome("b", 100.0, date(2026, 7, 30)),
    )
    ranked_now = prioritize_worklist(result, today=TODAY)
    ranked_later = prioritize_worklist(result, today=date(2026, 8, 15))
    assert ranked_now[0].record.claim_id == "a"
    # From a vantage point after both deadlines, 'a' is MORE overdue than 'b',
    # so it still ranks first — but the point is the answer depends only on
    # the `today` argument, and calls are deterministic.
    assert ranked_later == prioritize_worklist(result, today=date(2026, 8, 15))
    # Input order is never mutated.
    assert [o.record.claim_id for o in result.outcomes] == ["a", "b"]


def test_module_never_reads_the_system_clock():
    source = inspect.getsource(prioritize)
    assert "datetime.now" not in source
    assert "date.today" not in source
