"""Batch Insights input contract — the host-computed aggregates view.

Batch Aggregates is the *workflow-state* rollup a host computes over its own
batch (lifecycle counts, payer/CARC/deadline/dismissal dimensions) and feeds to
BatchInsightsAgent. It is distinct from BatchSummary in denial_record.py, which
is the package's own *execution* rollup — see CONTEXT.md.

Every model here is frozen: aggregates are a value the host hands over, not a
mutable buffer the agent edits. Validation is deliberately light — non-negative
counts and dollars, a non-empty batch, and a coherent service-date range. There
are no cross-dimension sum invariants: the host owns aggregation semantics, and
per-dimension dollar rounding legitimately drifts by cents.

ADR 0001 governs the shape: no free-text field may ever be added here. Doing so
re-opens the PHI-redaction question this contract exists to close.
"""
from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

Count = Annotated[int, Field(ge=0)]
Amount = Annotated[float, Field(ge=0)]


class PayerAggregate(BaseModel):
    """One payer's slice of a batch."""

    model_config = ConfigDict(frozen=True)

    payer: str
    records: Count
    billed_amount: Amount


class CarcAggregate(BaseModel):
    """One CARC code's slice of a batch.

    The code travels bare; BatchInsightsAgent enriches it with a description
    from the package's curated DenialCodeDB at prompt-build time, so insight
    quality never depends on a host remembering to look codes up.
    """

    model_config = ConfigDict(frozen=True)

    carc_code: str
    records: Count
    billed_amount: Amount


class DeadlineBuckets(BaseModel):
    """Appeal-deadline pressure, in the host spec's fixed buckets.

    `unknown` covers records with no deadline on file.
    """

    model_config = ConfigDict(frozen=True)

    overdue: Count
    due_within_7_days: Count
    due_7_to_30_days: Count
    due_beyond_30_days: Count
    unknown: Count


class BatchTotals(BaseModel):
    """Batch-wide record counts and dollars by lifecycle state.

    `records` is `ge=1`: an empty batch has nothing to analyse, and rejecting
    it at construction keeps degenerate host data from reaching a paid call.
    The lifecycle counts need not sum to `records` — records in no terminal
    state yet are simply absent from all four.
    """

    model_config = ConfigDict(frozen=True)

    records: int = Field(..., ge=1)
    billed_amount: Amount
    drafted: Count
    failed: Count
    submitted: Count
    dismissed: Count


class BatchAggregates(BaseModel):
    """The complete aggregates-only view of one batch, as fed to insights.

    `dismissals_by_reason` is keyed by the host's closed reason enum
    (`payer_correct | too_small | deadline_passed | other`) but typed as an
    open dict, so a host adding a reason never forces a package release. Keys
    are enum identifiers, never user prose (ADR 0001).

    `service_date_start` / `service_date_end` are set together and ordered, or
    both None when the batch carries no service dates.
    """

    model_config = ConfigDict(frozen=True)

    totals: BatchTotals
    by_payer: list[PayerAggregate] = Field(default_factory=list)
    by_carc: list[CarcAggregate] = Field(default_factory=list)
    deadlines: DeadlineBuckets
    dismissals_by_reason: dict[str, Count] = Field(default_factory=dict)
    service_date_start: date | None = None
    service_date_end: date | None = None

    @model_validator(mode="after")
    def _service_date_range_is_coherent(self) -> "BatchAggregates":
        start, end = self.service_date_start, self.service_date_end
        if (start is None) != (end is None):
            raise ValueError(
                "service_date_start and service_date_end must both be set or both be None"
            )
        if start is not None and end is not None and start > end:
            raise ValueError("service_date_start must not be after service_date_end")
        return self
