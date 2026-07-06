"""Provider-side denial management demo.

Generates a synthetic remittance batch (50 denied claims), runs AppealAgent
over every record with per-record error isolation, and prints the
prioritized worklist an RCM team would work from, plus one fully generated
appeal letter.

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
from healthflow_agents.batch import BatchRunner, days_until_deadline, prioritize_worklist
from healthflow_agents.contracts.denial_record import BatchResult, RecordOutcome
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
    def create(self, **kwargs: object) -> _StubResponse:
        return _StubResponse(_STUB_RECOMMENDATION)


class OfflineStubClient:
    """Duck-typed stand-in for anthropic.Anthropic — no network, no key."""

    def __init__(self) -> None:
        self.messages = _StubMessages()


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
