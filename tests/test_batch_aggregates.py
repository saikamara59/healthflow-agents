"""Contract seam for Batch Aggregates — the insights agent's frozen input.

Exercises construction only: guardrail rejections, immutability, and the
open dismissal-reason keying. No cross-dimension sum invariants are asserted;
the host owns aggregation semantics (see docs/adr/0001).
"""
from datetime import date

import pytest
from pydantic import ValidationError

from healthflow_agents.contracts import (
    BatchAggregates,
    BatchTotals,
    CarcAggregate,
    DeadlineBuckets,
    PayerAggregate,
)


def make_totals(**overrides):
    fields = {
        "records": 12,
        "billed_amount": 48_500.00,
        "drafted": 7,
        "failed": 1,
        "submitted": 3,
        "dismissed": 1,
    }
    fields.update(overrides)
    return BatchTotals(**fields)


def make_deadlines(**overrides):
    fields = {
        "overdue": 2,
        "due_within_7_days": 3,
        "due_7_to_30_days": 4,
        "due_beyond_30_days": 2,
        "unknown": 1,
    }
    fields.update(overrides)
    return DeadlineBuckets(**fields)


def make_aggregates(**overrides):
    fields = {
        "totals": make_totals(),
        "by_payer": [
            PayerAggregate(payer="Aetna", records=7, billed_amount=30_000.00),
            PayerAggregate(payer="Cigna", records=5, billed_amount=18_500.00),
        ],
        "by_carc": [
            CarcAggregate(carc_code="CO-50", records=8, billed_amount=32_000.00),
            CarcAggregate(carc_code="CO-97", records=4, billed_amount=16_500.00),
        ],
        "deadlines": make_deadlines(),
        "dismissals_by_reason": {"payer_correct": 1},
        "service_date_start": date(2026, 1, 4),
        "service_date_end": date(2026, 3, 27),
    }
    fields.update(overrides)
    return BatchAggregates(**fields)


def test_valid_aggregates_construct():
    aggregates = make_aggregates()
    assert aggregates.totals.records == 12
    assert [row.payer for row in aggregates.by_payer] == ["Aetna", "Cigna"]
    assert [row.carc_code for row in aggregates.by_carc] == ["CO-50", "CO-97"]
    assert aggregates.deadlines.overdue == 2
    assert aggregates.dismissals_by_reason == {"payer_correct": 1}
    assert aggregates.service_date_start == date(2026, 1, 4)
    assert aggregates.service_date_end == date(2026, 3, 27)


def test_empty_dimensions_are_allowed():
    """A batch with no dismissals and no deadline data is still valid."""
    aggregates = make_aggregates(
        by_payer=[],
        by_carc=[],
        dismissals_by_reason={},
        service_date_start=None,
        service_date_end=None,
    )
    assert aggregates.by_payer == []
    assert aggregates.dismissals_by_reason == {}
    assert aggregates.service_date_start is None


def test_dimension_totals_need_not_reconcile_with_batch_totals():
    """Deliberately no cross-dimension sum invariants — the host owns those."""
    aggregates = make_aggregates(
        by_payer=[PayerAggregate(payer="Aetna", records=1, billed_amount=1.0)]
    )
    assert aggregates.totals.records == 12


@pytest.mark.parametrize(
    "model, field",
    [
        (BatchAggregates, "totals"),
        (BatchTotals, "records"),
        (PayerAggregate, "payer"),
        (CarcAggregate, "carc_code"),
        (DeadlineBuckets, "overdue"),
    ],
)
def test_models_are_frozen(model, field):
    instances = {
        BatchAggregates: make_aggregates,
        BatchTotals: make_totals,
        PayerAggregate: lambda: PayerAggregate(
            payer="Aetna", records=7, billed_amount=30_000.00
        ),
        CarcAggregate: lambda: CarcAggregate(
            carc_code="CO-50", records=8, billed_amount=32_000.00
        ),
        DeadlineBuckets: make_deadlines,
    }
    instance = instances[model]()
    with pytest.raises(ValidationError):
        setattr(instance, field, getattr(instance, field))


def test_mutating_nested_model_raises():
    aggregates = make_aggregates()
    with pytest.raises(ValidationError):
        aggregates.totals.records = 99


def test_zero_total_records_rejected():
    """An empty batch has nothing to analyse — reject before any API spend."""
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        make_totals(records=0)


@pytest.mark.parametrize(
    "field", ["records", "billed_amount", "drafted", "failed", "submitted", "dismissed"]
)
def test_negative_totals_rejected(field):
    with pytest.raises(ValidationError, match="greater than or equal to"):
        make_totals(**{field: -1})


@pytest.mark.parametrize("field", ["records", "billed_amount"])
def test_negative_payer_aggregate_rejected(field):
    fields = {"payer": "Aetna", "records": 7, "billed_amount": 30_000.00, field: -1}
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        PayerAggregate(**fields)


@pytest.mark.parametrize("field", ["records", "billed_amount"])
def test_negative_carc_aggregate_rejected(field):
    fields = {"carc_code": "CO-50", "records": 8, "billed_amount": 32_000.00, field: -1}
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        CarcAggregate(**fields)


@pytest.mark.parametrize(
    "field",
    ["overdue", "due_within_7_days", "due_7_to_30_days", "due_beyond_30_days", "unknown"],
)
def test_negative_deadline_bucket_rejected(field):
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        make_deadlines(**{field: -1})


def test_negative_dismissal_count_rejected():
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        make_aggregates(dismissals_by_reason={"payer_correct": -1})


def test_unknown_dismissal_reason_keys_accepted():
    """The host's reason set is closed on its side; a new one must not
    force a package tag."""
    aggregates = make_aggregates(
        dismissals_by_reason={"payer_correct": 1, "duplicate_claim": 2}
    )
    assert aggregates.dismissals_by_reason["duplicate_claim"] == 2


def test_service_date_start_without_end_rejected():
    with pytest.raises(ValidationError, match="service_date"):
        make_aggregates(service_date_end=None)


def test_service_date_end_without_start_rejected():
    with pytest.raises(ValidationError, match="service_date"):
        make_aggregates(service_date_start=None)


def test_reversed_service_date_range_rejected():
    with pytest.raises(ValidationError, match="service_date"):
        make_aggregates(
            service_date_start=date(2026, 3, 27),
            service_date_end=date(2026, 1, 4),
        )


def test_single_day_service_date_range_accepted():
    day = date(2026, 2, 2)
    aggregates = make_aggregates(service_date_start=day, service_date_end=day)
    assert aggregates.service_date_start == aggregates.service_date_end


def test_no_free_text_fields_in_the_contract():
    """ADR 0001: nothing free-text may enter the insights input, or the
    redaction boundary re-opens. Payer names and CARC codes are the only
    strings, and both are structured claim metadata."""
    string_fields = {
        name: field
        for model in (BatchAggregates, BatchTotals, DeadlineBuckets)
        for name, field in model.model_fields.items()
        if field.annotation is str
    }
    assert string_fields == {}
