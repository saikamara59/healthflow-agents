"""Worklist prioritization: which appeals should the RCM team work first.

Pure functions — the clock is always a parameter, never read from the
system. Ranking: appeal_deadline proximity first (already-overdue records
sort most urgent; records with no known deadline sort last), then billed
amount descending.
"""
from datetime import date

from healthflow_agents.contracts.denial_record import BatchResult, DenialRecord, RecordOutcome

# Records with no known deadline rank after any dated record.
_NO_DEADLINE = float("inf")


def days_until_deadline(record: DenialRecord, *, today: date) -> float:
    """Days from `today` to the record's appeal deadline.

    Negative when the deadline has passed; +inf when no deadline is known.
    """
    if record.appeal_deadline is None:
        return _NO_DEADLINE
    return float((record.appeal_deadline - today).days)


def prioritize_worklist(result: BatchResult, *, today: date) -> list[RecordOutcome]:
    """Rank a batch's outcomes into a worklist: most urgent first.

    Sort key: (days until deadline ascending, billed amount descending).
    Overdue records (negative days) naturally rank above everything with
    time remaining; no-deadline records rank last, ordered among themselves
    by dollars at stake. Failed records rank by the same rules — they still
    represent money and deadlines needing attention.
    """
    return sorted(
        result.outcomes,
        key=lambda o: (
            days_until_deadline(o.record, today=today),
            -o.record.billed_amount,
        ),
    )
