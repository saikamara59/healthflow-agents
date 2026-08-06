"""Contract seam for Batch Aggregates — the insights agent's frozen input.

Exercises construction only: guardrail rejections, immutability, and the
open dismissal-reason keying. No cross-dimension sum invariants are asserted;
the host owns aggregation semantics (see docs/adr/0001).
"""
from collections.abc import Mapping
from datetime import date
from typing import get_args, get_origin

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
    assert aggregates.by_payer == ()
    assert dict(aggregates.dismissals_by_reason) == {}
    assert aggregates.service_date_start is None


@pytest.mark.parametrize(
    "field",
    [
        "totals",
        "by_payer",
        "by_carc",
        "deadlines",
        "dismissals_by_reason",
        "service_date_start",
        "service_date_end",
    ],
)
def test_every_field_is_required(field):
    """No defaults: a host worker that forgets a dimension fails at
    construction rather than silently shipping an empty one to a paid call."""
    fields = make_aggregates().model_dump()
    del fields[field]
    with pytest.raises(ValidationError, match="[Ff]ield required"):
        BatchAggregates(**fields)


def test_dimension_totals_need_not_reconcile_with_batch_totals():
    """Deliberately no cross-dimension sum invariants — the host owns those."""
    aggregates = make_aggregates(
        by_payer=[PayerAggregate(payer="Aetna", records=1, billed_amount=1.0)]
    )
    assert aggregates.totals.records == 12


def make_payer(**overrides):
    fields = {"payer": "Aetna", "records": 7, "billed_amount": 30_000.00}
    fields.update(overrides)
    return PayerAggregate(**fields)


def make_carc(**overrides):
    fields = {"carc_code": "CO-50", "records": 8, "billed_amount": 32_000.00}
    fields.update(overrides)
    return CarcAggregate(**fields)


@pytest.mark.parametrize(
    "factory, field",
    [
        (make_aggregates, "totals"),
        (make_totals, "records"),
        (make_payer, "payer"),
        (make_carc, "carc_code"),
        (make_deadlines, "overdue"),
    ],
)
def test_models_are_frozen(factory, field):
    instance = factory()
    with pytest.raises(ValidationError):
        setattr(instance, field, getattr(instance, field))


def test_mutating_nested_model_raises():
    aggregates = make_aggregates()
    with pytest.raises(ValidationError):
        aggregates.totals.records = 99


def test_dimension_rows_cannot_be_appended_to():
    aggregates = make_aggregates()
    with pytest.raises(AttributeError):
        aggregates.by_payer.append(make_payer(payer="Humana"))
    with pytest.raises(AttributeError):
        aggregates.by_carc.append(make_carc(carc_code="CO-16"))


def test_dismissal_counts_cannot_be_written_past_their_bound():
    """A plain dict would let a caller slip a negative count in after
    construction, past the ge=0 guardrail."""
    aggregates = make_aggregates()
    with pytest.raises(TypeError):
        aggregates.dismissals_by_reason["payer_correct"] = -5
    assert aggregates.dismissals_by_reason["payer_correct"] == 1


def test_host_lists_and_dicts_are_accepted_and_not_aliased():
    """Hosts pass ordinary lists/dicts; later edits to those must not leak in."""
    payers = [make_payer()]
    dismissals = {"payer_correct": 1}
    aggregates = make_aggregates(by_payer=payers, dismissals_by_reason=dismissals)

    payers.append(make_payer(payer="Humana"))
    dismissals["other"] = 3

    assert len(aggregates.by_payer) == 1
    assert dict(aggregates.dismissals_by_reason) == {"payer_correct": 1}


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


def test_round_trips_through_json():
    """The host builds these on its side of the seam and may persist them."""
    original = make_aggregates()
    restored = BatchAggregates.model_validate_json(original.model_dump_json())
    assert restored == original
    assert dict(restored.dismissals_by_reason) == {"payer_correct": 1}
    assert restored.by_payer[0].payer == "Aetna"


def test_dump_yields_plain_builtins():
    dumped = make_aggregates().model_dump()
    assert dumped["dismissals_by_reason"] == {"payer_correct": 1}
    assert type(dumped["dismissals_by_reason"]) is dict


def carries_a_string(annotation) -> bool:
    """True if `str` appears anywhere in the annotation — bare, optional, or
    nested in a container. `dict[str, int]` keys don't count: those are the
    enum identifiers ADR 0001 explicitly permits."""
    if annotation is str:
        return True
    args = get_args(annotation)
    if get_origin(annotation) in (dict, Mapping):
        return any(carries_a_string(arg) for arg in args[1:])
    return any(carries_a_string(arg) for arg in args)


def test_no_free_text_fields_in_the_contract():
    """ADR 0001: nothing free-text may enter the insights input, or the
    redaction boundary re-opens by construction. Payer names and CARC codes
    are the only strings in the contract, and both are structured claim
    metadata rather than prose. Anything else is a boundary regression.

    This sweeps every model reachable from BatchAggregates, and catches
    `str | None`, `list[str]`, and `dict[str, str]` as well as bare `str`.
    """
    allowed = {("PayerAggregate", "payer"), ("CarcAggregate", "carc_code")}
    models = (
        BatchAggregates,
        BatchTotals,
        DeadlineBuckets,
        PayerAggregate,
        CarcAggregate,
    )
    offenders = {
        (model.__name__, name)
        for model in models
        for name, field in model.model_fields.items()
        if carries_a_string(field.annotation)
    } - allowed
    assert offenders == set()


def test_free_text_sweep_would_catch_a_regression():
    """Guards the guard: the sweep above passes trivially if its detection
    is broken, so prove it flags the shapes a free-text field would take."""
    assert carries_a_string(str)
    assert carries_a_string(str | None)
    assert carries_a_string(list[str])
    assert carries_a_string(dict[str, str])
    assert not carries_a_string(int)
    assert not carries_a_string(dict[str, int])
    assert not carries_a_string(date | None)
