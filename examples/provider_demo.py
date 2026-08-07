"""Provider-side denial management demo.

Generates a synthetic remittance batch (50 denied claims), runs AppealAgent
over every record with per-record error isolation, and prints the
prioritized worklist an RCM team would work from, one fully generated appeal
letter, and the BatchInsightsAgent narrative over the batch's aggregates.

Offline by default: the Claude refine step uses a clearly-labeled stub
client, so the demo runs with no API key and produces deterministic output.
Pass --live (with ANTHROPIC_API_KEY set) to make real Opus calls — note
that's one API call per record.

    python -m examples.provider_demo
    python -m examples.provider_demo --n 50 --seed 7
    python -m examples.provider_demo --live --n 5

All data is synthetic — every patient name, claim id, and dollar figure is
invented. Records deliberately include patient identifiers in their free
text; watch the phi_redacted count in the audit tally to see the redaction
boundary do its job.
"""
import argparse
import sys
from collections import Counter
from datetime import date

from healthflow_agents.agents.appeal_agent import AppealAgent
from healthflow_agents.agents.batch_insights_agent import (
    DRY_RUN_NARRATIVE,
    BatchInsightsAgent,
)
from healthflow_agents.batch import BatchRunner, days_until_deadline, prioritize_worklist
from healthflow_agents.contracts import (
    BatchAggregates,
    BatchTotals,
    CarcAggregate,
    DeadlineBuckets,
    PayerAggregate,
)
from healthflow_agents.contracts.denial_record import (
    BatchResult,
    DenialRecord,
    RecordOutcome,
)
from healthflow_agents.tools.denial_codes import DenialCodeDB
from healthflow_agents.tools.remittance_parser import make_synthetic_denials

WIDTH = 100

_STUB_RECOMMENDATION = (
    "1. Attach the operative report and physician documentation supporting "
    "medical necessity for the billed service.\n"
    "2. Cite the applicable coverage rule from the CMS guidance referenced "
    "above and request redetermination within the appeal window.\n"
    "3. If the payer upholds the denial, escalate to a peer-to-peer review "
    "with the plan's medical director.\n"
    "[offline demo — refined recommendation generated without an API call; "
    "run with --live for a real Claude response]"
)


class _StubText:
    def __init__(self, text: str) -> None:
        self.text = text


class _StubResponse:
    def __init__(self, text: str) -> None:
        self.content = [_StubText(text)]


class _StubMessages:
    def __init__(self, text: str) -> None:
        self._text = text

    def create(self, **kwargs: object) -> _StubResponse:
        return _StubResponse(self._text)


class OfflineStubClient:
    """Duck-typed stand-in for anthropic.Anthropic — no network, no key."""

    def __init__(self, text: str = _STUB_RECOMMENDATION) -> None:
        self.messages = _StubMessages(text)


class CountingAuditSink:
    """Tallies audit events instead of printing them, keeping demo output clean."""

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()

    def log(self, event_type: str, details: dict) -> None:
        self.counts[event_type] += 1


class QuietInvocationTracker:
    """No-op tracker for demo output cleanliness."""

    def __call__(self, *, agent: str, event_type: str, model: str | None = None):
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            class _Record:
                details: dict = {}

            yield _Record()

        return _cm()


def _rule(char: str = "─") -> str:
    return char * WIDTH


def _fmt_days(days: float) -> str:
    if days == float("inf"):
        return "—"
    if days < 0:
        return f"OVERDUE {int(-days)}d"
    return f"{int(days)}d left"


def print_summary(result: BatchResult, code_db: DenialCodeDB) -> None:
    s = result.summary
    print(_rule("═"))
    print("BATCH SUMMARY")
    print(_rule())
    print(
        f"  Records: {s.total_records}   Succeeded: {s.succeeded}   "
        f"Failed: {s.failed}   Total billed: ${s.total_billed_amount:,.2f}"
    )
    print()
    print(f"  {'CARC':8} {'Claims':>6} {'Billed':>14}  Denial category")
    for carc, count in sorted(
        s.records_by_carc.items(), key=lambda kv: -s.billed_by_carc[kv[0]]
    ):
        entry = code_db.lookup(carc)
        label = entry["category"] if entry else "(not in code DB — fallback arguments used)"
        print(f"  {carc:8} {count:>6} {s.billed_by_carc[carc]:>13,.2f}  {label}")


def print_worklist(ranked: list[RecordOutcome], today: date, top: int = 15) -> None:
    print(_rule("═"))
    print(f"PRIORITIZED WORKLIST — top {min(top, len(ranked))} of {len(ranked)} "
          f"(deadline proximity, then dollars)")
    print(_rule())
    header = (
        f"  {'#':>2}  {'Claim':22} {'Payer':26} {'CARC':7} "
        f"{'Billed':>12} {'Deadline':11} {'Urgency':12} Status"
    )
    print(header)
    for i, outcome in enumerate(ranked[:top], 1):
        r = outcome.record
        deadline = r.appeal_deadline.isoformat() if r.appeal_deadline else "—"
        urgency = _fmt_days(days_until_deadline(r, today=today))
        status = "ready" if outcome.success else f"FAILED ({outcome.error_type})"
        print(
            f"  {i:>2}  {r.claim_id:22} {r.payer:26} {r.carc_code:7} "
            f"{r.billed_amount:>11,.2f} {deadline:11} {urgency:12} {status}"
        )


def print_sample_appeal(ranked: list[RecordOutcome]) -> None:
    sample = next((o for o in ranked if o.success and o.appeal), None)
    if sample is None:
        print("\nNo successful appeal to display.")
        return
    r = sample.record
    print(_rule("═"))
    print(
        f"SAMPLE APPEAL — highest-priority claim {r.claim_id} "
        f"({r.payer}, {r.carc_code}, ${r.billed_amount:,.2f})"
    )
    print(_rule())
    print(sample.appeal.appeal_letter)
    print(_rule())
    print("REFINED RECOMMENDATION")
    print(_rule())
    print(sample.appeal.refined_recommendation)


def build_aggregates(result: BatchResult, today: date) -> BatchAggregates:
    """Roll a batch up into the aggregates-only insights input.

    Hosts own this computation against their own persisted batch; the demo
    does it over the run's records so the round trip is visible end to end.
    Note what does NOT travel: no claim ids, no denial reason text, no patient
    fields — the insights prompt sits outside the redaction boundary by
    construction (ADR 0001).
    """
    records: list[DenialRecord] = [o.record for o in result.outcomes]
    payer_claims: Counter[str] = Counter()
    payer_billed: Counter[str] = Counter()
    buckets: Counter[str] = Counter()

    for r in records:
        payer_claims[r.payer] += 1
        payer_billed[r.payer] += r.billed_amount
        days = days_until_deadline(r, today=today)
        if days == float("inf"):
            buckets["unknown"] += 1
        elif days < 0:
            buckets["overdue"] += 1
        elif days <= 7:
            buckets["due_within_7_days"] += 1
        elif days <= 30:
            buckets["due_7_to_30_days"] += 1
        else:
            buckets["due_beyond_30_days"] += 1

    summary = result.summary
    return BatchAggregates(
        totals=BatchTotals(
            records=summary.total_records,
            billed_amount=summary.total_billed_amount,
            drafted=summary.succeeded,
            failed=summary.failed,
            # This demo drafts appeals only; a host would carry its own
            # submitted/dismissed lifecycle counts here.
            submitted=0,
            dismissed=0,
        ),
        by_payer=[
            PayerAggregate(
                payer=payer, records=claims, billed_amount=payer_billed[payer]
            )
            for payer, claims in payer_claims.most_common()
        ],
        # Counts and dollars both come off BatchSummary, so the CARC rows the
        # agent sees agree to the cent with the summary printed above.
        by_carc=[
            CarcAggregate(
                carc_code=carc,
                records=summary.records_by_carc[carc],
                billed_amount=billed,
            )
            for carc, billed in sorted(
                summary.billed_by_carc.items(), key=lambda kv: -kv[1]
            )
        ],
        deadlines=DeadlineBuckets(
            overdue=buckets["overdue"],
            due_within_7_days=buckets["due_within_7_days"],
            due_7_to_30_days=buckets["due_7_to_30_days"],
            due_beyond_30_days=buckets["due_beyond_30_days"],
            unknown=buckets["unknown"],
        ),
        dismissals_by_reason={},
        service_date_start=min(r.service_date for r in records) if records else None,
        service_date_end=max(r.service_date for r in records) if records else None,
    )


def print_insights(
    result: BatchResult, today: date, audit: "CountingAuditSink", live: bool
) -> None:
    aggregates = build_aggregates(result, today)
    if live:
        agent = BatchInsightsAgent(
            audit_sink=audit, invocation_tracker=QuietInvocationTracker()
        )
    else:
        # Offline: the stub answers with the package's exported dry-run
        # narrative — the same constant a host's dry-run client serves.
        agent = BatchInsightsAgent(
            client=OfflineStubClient(DRY_RUN_NARRATIVE),  # type: ignore[arg-type]
            audit_sink=audit,
            invocation_tracker=QuietInvocationTracker(),
        )

    print(_rule("═"))
    print("BATCH INSIGHTS — narrative over aggregates only (no free text sent)")
    print(_rule())
    print(agent.generate_insights(aggregates))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=50, help="number of synthetic denials")
    parser.add_argument("--seed", type=int, default=0, help="synthetic data seed")
    parser.add_argument(
        "--live",
        action="store_true",
        help="make real Anthropic API calls for the refine step (one per record)",
    )
    args = parser.parse_args(argv)

    today = date.today()
    records = make_synthetic_denials(args.n, seed=args.seed, base_date=today)

    audit = CountingAuditSink()
    if args.live:
        agent = AppealAgent(audit_sink=audit, invocation_tracker=QuietInvocationTracker())
        mode = "LIVE (real Claude calls)"
    else:
        agent = AppealAgent(
            client=OfflineStubClient(),  # type: ignore[arg-type]
            audit_sink=audit,
            invocation_tracker=QuietInvocationTracker(),
        )
        mode = "offline (refine step stubbed; use --live for real Claude calls)"

    print(_rule("═"))
    print(f"PROVIDER DENIAL MANAGEMENT DEMO — {args.n} synthetic denials, mode: {mode}")

    result = BatchRunner(agent).run(records)
    ranked = prioritize_worklist(result, today=today)

    print_summary(result, agent.code_db)
    print_worklist(ranked, today)
    print_sample_appeal(ranked)
    print_insights(result, today, audit, live=args.live)

    print(_rule("═"))
    print("AUDIT EVENT TALLY (flowed through the injected AuditSink)")
    print(_rule())
    for event, count in sorted(audit.counts.items()):
        print(f"  {event:28} {count}")
    phi = audit.counts.get("phi_redacted", 0)
    print(
        f"\n  Every record crossed the redaction boundary "
        f"({phi} phi_redacted events for {args.n} records)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
