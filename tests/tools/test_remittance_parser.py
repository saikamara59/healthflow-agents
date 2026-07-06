"""Tests for the simplified remittance parser and the synthetic generator."""
import json
from datetime import date

import pytest

from healthflow_agents.contracts.denial_record import DenialRecord
from healthflow_agents.tools.remittance_parser import (
    RemittanceParseError,
    load_remittance,
    make_synthetic_denials,
    parse_remittance_csv,
    parse_remittance_json,
)

SAMPLE = DenialRecord(
    claim_id="CLM-2026-001",
    payer="Aetna Medicare Advantage",
    carc_code="CO-50",
    rarc_codes=["N115"],
    denial_reason_text="Not deemed a medical necessity by the payer.",
    billed_amount=1250.50,
    service_date=date(2026, 4, 1),
    denial_date=date(2026, 4, 20),
    appeal_deadline=date(2026, 6, 19),
)


# --- JSON ---


def test_parse_json_round_trip():
    text = json.dumps([SAMPLE.model_dump(mode="json")])
    records = parse_remittance_json(text)
    assert records == [SAMPLE]


def test_parse_json_rejects_non_array():
    with pytest.raises(RemittanceParseError):
        parse_remittance_json(json.dumps({"claim_id": "x"}))


def test_parse_json_reports_offending_row():
    good = SAMPLE.model_dump(mode="json")
    bad = {**good, "billed_amount": -5}
    with pytest.raises(RemittanceParseError, match="row 1"):
        parse_remittance_json(json.dumps([good, bad]))


# --- CSV ---


def test_parse_csv_round_trip():
    text = (
        "claim_id,payer,carc_code,rarc_codes,denial_reason_text,"
        "billed_amount,service_date,denial_date,appeal_deadline\n"
        'CLM-2026-001,Aetna Medicare Advantage,CO-50,N115,'
        '"Not deemed a medical necessity by the payer.",'
        "1250.50,2026-04-01,2026-04-20,2026-06-19\n"
    )
    assert parse_remittance_csv(text) == [SAMPLE]


def test_parse_csv_multiple_rarcs_and_missing_deadline():
    text = (
        "claim_id,payer,carc_code,rarc_codes,denial_reason_text,"
        "billed_amount,service_date,denial_date,appeal_deadline\n"
        "CLM-2,UHC,CO-16,M76|N265,Missing information.,300,2026-04-01,2026-04-20,\n"
    )
    [record] = parse_remittance_csv(text)
    assert record.rarc_codes == ["M76", "N265"]
    assert record.appeal_deadline is None


def test_parse_csv_reports_offending_row():
    text = (
        "claim_id,payer,carc_code,rarc_codes,denial_reason_text,"
        "billed_amount,service_date,denial_date,appeal_deadline\n"
        "CLM-1,UHC,CO-16,,ok,300,2026-04-01,2026-04-20,\n"
        "CLM-2,UHC,CO-16,,bad amount,not-a-number,2026-04-01,2026-04-20,\n"
    )
    with pytest.raises(RemittanceParseError, match="row 1"):
        parse_remittance_csv(text)


# --- load_remittance ---


def test_load_remittance_dispatches_on_extension(tmp_path):
    j = tmp_path / "remit.json"
    j.write_text(json.dumps([SAMPLE.model_dump(mode="json")]))
    assert load_remittance(j) == [SAMPLE]

    with pytest.raises(ValueError, match="unsupported"):
        load_remittance(tmp_path / "remit.x12")


# --- synthetic generator ---


def test_synthetic_denials_deterministic_for_seed():
    a = make_synthetic_denials(20, seed=7)
    b = make_synthetic_denials(20, seed=7)
    assert a == b
    assert a != make_synthetic_denials(20, seed=8)


def test_synthetic_denials_shape_and_realism():
    records = make_synthetic_denials(50, seed=1)
    assert len(records) == 50
    for r in records:
        assert r.carc_code.split("-")[0] in {"CO", "PR", "OA"}
        assert r.billed_amount > 0
        assert r.service_date < r.denial_date
        if r.appeal_deadline is not None:
            assert r.appeal_deadline > r.denial_date
    # A generated batch spans several distinct CARC codes.
    assert len({r.carc_code for r in records}) >= 5
    # Some (not all) records lack a deadline.
    missing = [r for r in records if r.appeal_deadline is None]
    assert 0 < len(missing) < len(records)


def test_synthetic_denials_include_phi_bearing_text():
    """A subset must embed synthetic patient identifiers so the batch demo
    and agent tests genuinely exercise the redaction boundary."""
    records = make_synthetic_denials(50, seed=1)
    phi_bearing = [r for r in records if "Patient:" in r.denial_reason_text]
    assert 0 < len(phi_bearing) < len(records)
    assert any("DOB:" in r.denial_reason_text for r in phi_bearing)


def test_synthetic_denials_pure_given_base_date():
    a = make_synthetic_denials(5, seed=3, base_date=date(2026, 1, 1))
    b = make_synthetic_denials(5, seed=3, base_date=date(2026, 1, 1))
    assert a == b
    assert all(r.service_date < date(2026, 1, 1) for r in a)
