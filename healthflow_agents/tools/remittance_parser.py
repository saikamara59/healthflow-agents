"""Parses a SIMPLIFIED remittance format (CSV or JSON) into DenialRecords.

This is deliberately not an X12 835 parser — see tools/x12_835.py for the
stubbed production path. The simplified format carries exactly the
DenialRecord fields:

JSON: a list of objects keyed by DenialRecord field names.
CSV:  a header row of DenialRecord field names; `rarc_codes` is
      pipe-separated (``N115|M76``); dates are ISO (YYYY-MM-DD); an empty
      `appeal_deadline` is None.

Also home to make_synthetic_denials(), a seeded generator of realistic
denial batches (real CARC/RARC pairings, plausible dollar amounts and
deadlines, and occasional synthetic patient identifiers in the free text so
demos exercise the redaction boundary). Synthetic data only — every name,
claim id, and dollar figure is invented.
"""
import csv
import io
import json
import random
from datetime import date, timedelta
from pathlib import Path

from pydantic import ValidationError

from healthflow_agents.contracts.denial_record import DenialRecord

_CSV_FIELDS = [
    "claim_id",
    "payer",
    "carc_code",
    "rarc_codes",
    "denial_reason_text",
    "billed_amount",
    "service_date",
    "denial_date",
    "appeal_deadline",
]


class RemittanceParseError(ValueError):
    """A remittance row failed validation; carries the offending row index."""

    def __init__(self, row: int, message: str):
        self.row = row
        super().__init__(f"remittance row {row}: {message}")


def parse_remittance_json(text: str) -> list[DenialRecord]:
    """Parse a JSON array of DenialRecord objects."""
    data = json.loads(text)
    if not isinstance(data, list):
        raise RemittanceParseError(0, "expected a JSON array of denial objects")
    records = []
    for i, item in enumerate(data):
        try:
            records.append(DenialRecord.model_validate(item))
        except ValidationError as exc:
            raise RemittanceParseError(i, str(exc)) from exc
    return records


def parse_remittance_csv(text: str) -> list[DenialRecord]:
    """Parse simplified-remittance CSV (see module docstring for the format)."""
    reader = csv.DictReader(io.StringIO(text))
    records = []
    for i, row in enumerate(reader):
        try:
            payload: dict = {k: v for k, v in row.items() if k in _CSV_FIELDS}
            rarc = (payload.get("rarc_codes") or "").strip()
            payload["rarc_codes"] = [c.strip() for c in rarc.split("|") if c.strip()]
            if not (payload.get("appeal_deadline") or "").strip():
                payload["appeal_deadline"] = None
            records.append(DenialRecord.model_validate(payload))
        except ValidationError as exc:
            raise RemittanceParseError(i, str(exc)) from exc
    return records


def load_remittance(path: str | Path) -> list[DenialRecord]:
    """Load a remittance file, dispatching on extension (.json / .csv)."""
    p = Path(path)
    if p.suffix.lower() not in (".json", ".csv"):
        raise ValueError(f"unsupported remittance format: {p.suffix!r} (use .json or .csv)")
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".json":
        return parse_remittance_json(text)
    return parse_remittance_csv(text)


# ── Synthetic data ───────────────────────────────────────────────────────────

# Realistic CARC/RARC pairings. Most codes exist in DenialCodeDB so demo
# batches hit the real lookup path; the last entries are deliberately absent
# from the DB to exercise the keyword-search / fallback path.
_DENIAL_PROFILES: list[dict] = [
    {
        "carc": "CO-50",
        "rarcs": ["N115"],
        "reason": "These are non-covered services because this is not deemed a medical necessity by the payer. Per LCD L{lcd}, coverage criteria were not met.",
    },
    {
        "carc": "CO-97",
        "rarcs": ["M15"],
        "reason": "The benefit for this service is included in the payment/allowance for another service already adjudicated. Separately billed services were bundled.",
    },
    {
        "carc": "CO-29",
        "rarcs": ["N30"],
        "reason": "The time limit for filing has expired. Claim received after the timely filing deadline.",
    },
    {
        "carc": "CO-16",
        "rarcs": ["M76", "N265"],
        "reason": "Claim lacks information or has submission/billing error(s). Missing or incomplete diagnosis; ordering provider information incomplete.",
    },
    {
        "carc": "CO-18",
        "rarcs": ["N522"],
        "reason": "Exact duplicate claim/service. This claim was previously processed.",
    },
    {
        "carc": "CO-45",
        "rarcs": [],
        "reason": "Charge exceeds fee schedule/maximum allowable or contracted/legislated fee arrangement.",
    },
    {
        "carc": "CO-4",
        "rarcs": ["N519"],
        "reason": "The procedure code is inconsistent with the modifier used, or a required modifier is missing.",
    },
    {
        "carc": "CO-11",
        "rarcs": ["M64"],
        "reason": "The diagnosis is inconsistent with the procedure. Diagnosis code does not support medical necessity of the billed service.",
    },
    {
        "carc": "CO-22",
        "rarcs": ["MA04"],
        "reason": "This care may be covered by another payer per coordination of benefits. Secondary payment cannot be considered without primary EOB.",
    },
    {
        "carc": "CO-109",
        "rarcs": ["N418"],
        "reason": "Claim/service not covered by this payer/contractor. You must send the claim to the correct payer/contractor.",
    },
    {
        "carc": "CO-119",
        "rarcs": [],
        "reason": "Benefit maximum for this time period or occurrence has been reached.",
    },
    # Not in DenialCodeDB — exercises keyword search + fallback arguments.
    {
        "carc": "CO-252",
        "rarcs": ["N706"],
        "reason": "An attachment/other documentation is required to adjudicate this claim. Documentation was not received.",
    },
    {
        "carc": "PR-204",
        "rarcs": ["N130"],
        "reason": "This service/equipment/drug is not covered under the patient's current benefit plan.",
    },
]

_PAYERS = [
    "Aetna Medicare Advantage",
    "UnitedHealthcare Medicare",
    "Humana Gold Plus",
    "Cigna Medicare",
    "BCBS Federal",
    "WellCare",
]

# Synthetic patients — appear inside denial_reason_text on a subset of
# records so demos and tests exercise the PHI redaction boundary.
_SYNTHETIC_PATIENTS = [
    ("Margaret Hale", "03/12/1948"),
    ("John Thornton", "07/04/1951"),
    ("Dorothea Brooke", "11/23/1955"),
    ("Edward Casaubon", "01/30/1943"),
    ("Anne Elliot", "08/09/1957"),
]


def make_synthetic_denials(
    n: int,
    seed: int = 0,
    base_date: date = date(2026, 7, 1),
) -> list[DenialRecord]:
    """Generate `n` synthetic-but-realistic denial records, deterministically.

    Pure given (n, seed, base_date) — no wall clock. Roughly one in three
    records embeds a synthetic patient name/DOB in denial_reason_text so the
    redaction path is exercised; ~10% have no appeal_deadline.
    """
    rng = random.Random(seed)
    records: list[DenialRecord] = []
    for i in range(n):
        profile = rng.choice(_DENIAL_PROFILES)
        reason = profile["reason"].format(lcd=rng.randint(30000, 39999))
        if rng.random() < 0.34:
            name, dob = rng.choice(_SYNTHETIC_PATIENTS)
            reason = f"Patient: {name}, DOB: {dob}. {reason}"

        service_date = base_date - timedelta(days=rng.randint(45, 120))
        denial_date = service_date + timedelta(days=rng.randint(14, 40))
        deadline: date | None
        if rng.random() < 0.10:
            deadline = None
        else:
            deadline = denial_date + timedelta(days=rng.choice([30, 60, 90]))

        records.append(
            DenialRecord(
                claim_id=f"CLM-{2026_000_000 + rng.randint(10_000, 999_999)}-{i:03d}",
                payer=rng.choice(_PAYERS),
                carc_code=profile["carc"],
                rarc_codes=list(profile["rarcs"]),
                denial_reason_text=reason,
                billed_amount=round(rng.uniform(85.0, 45_000.0), 2),
                service_date=service_date,
                denial_date=denial_date,
                appeal_deadline=deadline,
            )
        )
    return records
