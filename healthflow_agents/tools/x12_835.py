"""X12 835 (Electronic Remittance Advice) parsing — NOT IMPLEMENTED.

This is the production ingestion path for provider-side denial management:
real payer remittances arrive as X12 835 transaction sets (CLP claim payment
loops, CAS adjustment segments carrying CARC codes, LQ/RARC remark codes).
Parsing them correctly requires a full EDI segment/loop parser plus payer
companion-guide quirks, and is deliberately out of scope for now — see
TODO.md.

Until then, use tools/remittance_parser.py, which ingests a simplified
CSV/JSON format carrying the same DenialRecord fields, and
make_synthetic_denials() for demo/test data.
"""
from healthflow_agents.contracts.denial_record import DenialRecord


def parse_835(text: str) -> list[DenialRecord]:
    """Parse an X12 835 transaction set into DenialRecords. Not implemented."""
    raise NotImplementedError(
        "X12 835 parsing is not implemented yet — this stub marks the "
        "production ingestion path. Use tools/remittance_parser.py "
        "(simplified CSV/JSON) in the meantime."
    )
