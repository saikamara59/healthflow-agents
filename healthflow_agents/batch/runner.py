"""BatchRunner: run AppealAgent over a batch of provider denial records.

Sequential for now; `max_concurrency` is accepted (and validated) so
concurrency can land later without changing any signature. Per-record
failures are isolated into structured RecordOutcomes — one bad record never
kills the batch. All logging flows through the agent's injected AuditSink
and InvocationTracker; there is no separate batch logging mechanism.
"""
from collections import Counter
from typing import Sequence

from healthflow_agents.agents.appeal_agent import AppealAgent
from healthflow_agents.contracts.denial_record import (
    AppealOutput,
    BatchResult,
    BatchSummary,
    DenialRecord,
    RecordOutcome,
)


def summarize_outcomes(outcomes: Sequence[RecordOutcome]) -> BatchSummary:
    """Batch-level rollup: counts, total dollars, and per-CARC grouping."""
    by_carc_count: Counter[str] = Counter()
    by_carc_billed: dict[str, float] = {}
    total_billed = 0.0
    for outcome in outcomes:
        carc = outcome.record.carc_code
        by_carc_count[carc] += 1
        by_carc_billed[carc] = round(
            by_carc_billed.get(carc, 0.0) + outcome.record.billed_amount, 2
        )
        total_billed += outcome.record.billed_amount
    return BatchSummary(
        total_records=len(outcomes),
        succeeded=sum(1 for o in outcomes if o.success),
        failed=sum(1 for o in outcomes if not o.success),
        total_billed_amount=round(total_billed, 2),
        records_by_carc=dict(by_carc_count),
        billed_by_carc=by_carc_billed,
    )


class BatchRunner:
    """Runs AppealAgent.process_denial_record over a list of DenialRecords."""

    def __init__(self, agent: AppealAgent, *, max_concurrency: int = 1) -> None:
        if max_concurrency != 1:
            raise NotImplementedError(
                "concurrent batch processing is planned but not implemented; "
                "only max_concurrency=1 is supported"
            )
        self.agent = agent
        self.max_concurrency = max_concurrency

    def run(self, records: Sequence[DenialRecord]) -> BatchResult:
        with self.agent.invocations(
            agent="appeal_batch", event_type="run_batch", model=self.agent.model
        ) as inv:
            self.agent.audit.log("batch_started", {"records": len(records)})

            outcomes: list[RecordOutcome] = []
            for record in records:
                try:
                    analysis, argument, letter, refined = (
                        self.agent.process_denial_record(record)
                    )
                except Exception as exc:  # per-record isolation, never re-raise
                    self.agent.audit.log("record_failed", {
                        "claim_id": record.claim_id,
                        "error": f"{type(exc).__name__}: {exc}"[:512],
                    })
                    outcomes.append(RecordOutcome(
                        record=record,
                        success=False,
                        error_type=type(exc).__name__,
                        error_message=str(exc)[:512],
                    ))
                else:
                    outcomes.append(RecordOutcome(
                        record=record,
                        success=True,
                        appeal=AppealOutput(
                            analysis=analysis,
                            argument=argument,
                            appeal_letter=letter,
                            refined_recommendation=refined,
                        ),
                    ))

            summary = summarize_outcomes(outcomes)
            self.agent.audit.log("batch_completed", {
                "records": summary.total_records,
                "succeeded": summary.succeeded,
                "failed": summary.failed,
                "total_billed_amount": summary.total_billed_amount,
            })
            inv.details = {
                "records": summary.total_records,
                "succeeded": summary.succeeded,
                "failed": summary.failed,
            }
            return BatchResult(outcomes=outcomes, summary=summary)
