"""Redaction-recall corpus for PHIRedactor.

Each case is realistic denial-letter / remittance free text with three
assertions:

- `leaks`      — substrings that MUST NOT survive redaction (the PHI)
- `placeholders` — placeholders that must appear in the output
- `preserved`  — substrings that MUST survive (guards against over-redaction
                 of clinical/regulatory content the agents need)

Guard cases assert the text passes through byte-identical — they pin the
deliberate non-redactions (provider NPIs and names, CFR citations, dollar
amounts, ZIP+4). Known recall gaps are encoded as strict-xfail cases at the
bottom so fixing one flips a test instead of going unnoticed.
"""
import pytest

from healthflow_agents.redaction.phi_redactor import PHIRedactor
from healthflow_agents.redaction.prompt_inputs import ProviderDenialPromptInput


def _redact(text: str) -> tuple[str, list[dict]]:
    return PHIRedactor().redact(text)


# ── Recall cases: (text, leaks, placeholders, preserved) ────────────────────

RECALL_CASES = [
    # Uppercase names — remittance and EOB free text is very often ALL CAPS.
    pytest.param(
        "Patient: MARGARET HALE, DOB: 03/12/1948. These are non-covered services.",
        ["MARGARET", "HALE", "03/12/1948"],
        {"[PATIENT_NAME]", "[DOB]"},
        ["non-covered services"],
        id="upper-name-title-label",
    ),
    pytest.param(
        "PATIENT: JOHN THORNTON - claim denied as exact duplicate.",
        ["JOHN", "THORNTON"],
        {"[PATIENT_NAME]"},
        ["exact duplicate"],
        id="upper-name-upper-label",
    ),
    pytest.param(
        "MEMBER: DOROTHEA BROOKE. The time limit for filing has expired.",
        ["DOROTHEA", "BROOKE"],
        {"[PATIENT_NAME]"},
        ["time limit for filing"],
        id="upper-name-member-label",
    ),
    pytest.param(
        "Dear MARGARET HALE,\nYour claim has been denied.",
        ["MARGARET", "HALE"],
        {"[PATIENT_NAME]"},
        ["Your claim has been denied."],
        id="upper-name-dear-comma",
    ),
    pytest.param(
        "Dear MARGARET HALE:\nYour claim has been denied.",
        ["MARGARET", "HALE"],
        {"[PATIENT_NAME]"},
        ["Your claim has been denied."],
        id="upper-name-dear-colon",
    ),
    # No punctuation between the name and the next label: the name match must
    # stop before "DOB" so the DOB pattern still sees its label.
    pytest.param(
        "Patient: MARGARET HALE DOB: 03/12/1948",
        ["MARGARET", "HALE", "03/12/1948"],
        {"[PATIENT_NAME]", "[DOB]"},
        [],
        id="upper-name-then-dob-label",
    ),
    # Middle initials.
    pytest.param(
        "PATIENT: MARGARET J. HALE, DOB: 03/12/1948.",
        ["MARGARET", "HALE", "03/12/1948"],
        {"[PATIENT_NAME]", "[DOB]"},
        [],
        id="upper-name-middle-initial",
    ),
    pytest.param(
        "Patient: Margaret J. Hale was denied coverage.",
        ["Margaret", "Hale"],
        {"[PATIENT_NAME]"},
        ["denied coverage"],
        id="title-name-middle-initial",
    ),
    # Lowercase label.
    pytest.param(
        "name: Anne Elliot\nStatus: Denied",
        ["Anne", "Elliot"],
        {"[PATIENT_NAME]"},
        ["Status: Denied"],
        id="lowercase-label",
    ),
    # Title-case regressions (behavior that already worked must keep working).
    pytest.param(
        "Patient: Margaret Hale\nDiagnosis: back pain",
        ["Margaret", "Hale"],
        {"[PATIENT_NAME]"},
        ["Diagnosis: back pain"],
        id="title-name-regression",
    ),
    pytest.param(
        "Dear John Thornton,\nWe regret to inform you.",
        ["John", "Thornton"],
        {"[PATIENT_NAME]"},
        ["We regret to inform you."],
        id="dear-title-regression",
    ),
    # Phone format variants.
    pytest.param(
        "Call 555.123.4567 with questions.",
        ["555.123.4567"],
        {"[PHONE]"},
        ["with questions."],
        id="phone-dots",
    ),
    pytest.param(
        "Call (555)123-4567 with questions.",
        ["123-4567"],
        {"[PHONE]"},
        ["with questions."],
        id="phone-paren-no-space",
    ),
    pytest.param(
        "Contact 555 123 4567 today.",
        ["555 123 4567"],
        {"[PHONE]"},
        ["today."],
        id="phone-spaces",
    ),
    pytest.param(
        "Phone: (555) 123-4567\nCall us",
        ["(555) 123-4567"],
        {"[PHONE]"},
        ["Call us"],
        id="phone-paren-regression",
    ),
    pytest.param(
        "Contact: 555-123-4567 for questions",
        ["555-123-4567"],
        {"[PHONE]"},
        ["for questions"],
        id="phone-dash-regression",
    ),
    # SSN format variants.
    pytest.param(
        "SSN: 123-45-6789\nClaim number: 100200",
        ["123-45-6789"],
        {"[SSN]"},
        ["Claim number: 100200"],
        id="ssn-dashed-regression",
    ),
    pytest.param(
        "SSN 123456789 on file.",
        ["123456789"],
        {"[SSN]"},
        ["on file."],
        id="ssn-bare-nine-digits",
    ),
    pytest.param(
        "SSN: 123 45 6789",
        ["123 45 6789"],
        {"[SSN]"},
        [],
        id="ssn-space-separated",
    ),
]


@pytest.mark.parametrize("text,leaks,placeholders,preserved", RECALL_CASES)
def test_recall(text, leaks, placeholders, preserved):
    redacted, log = _redact(text)
    for leak in leaks:
        assert leak not in redacted, f"leaked {leak!r} in: {redacted!r}"
    for placeholder in placeholders:
        assert placeholder in redacted, f"missing {placeholder} in: {redacted!r}"
    for keep in preserved:
        assert keep in redacted, f"over-redacted {keep!r} from: {redacted!r}"
    logged = {entry["placeholder"] for entry in log}
    assert placeholders <= logged


# ── Guard cases: deliberate non-redactions must pass through unchanged ──────

GUARD_CASES = [
    # Provider NPIs (10 digits) and provider names are public NPPES data and
    # pass through by design. This is also why bare 10-digit numbers are NOT
    # treated as phone numbers.
    pytest.param(
        "Rendering provider NPI 1234567890, Dr. Sarah Chen.",
        id="npi-and-provider-name",
    ),
    pytest.param(
        "Appeal rights under 42 CFR §405.940-405.958 apply.",
        id="cfr-citation",
    ),
    pytest.param(
        "Billed $1,234.56 on 2026-07-01 for CPT 99213.",
        id="amount-iso-date-cpt",
    ),
    # ZIP+4 is 5-4; the SSN patterns require the 3-2-4 shape.
    pytest.param(
        "Mail to PO Box 982, Lexington KY 40512-8306.",
        id="zip-plus-four",
    ),
    pytest.param(
        "Per LCD L34567, coverage criteria were not met.",
        id="lcd-citation",
    ),
]


@pytest.mark.parametrize("text", GUARD_CASES)
def test_guard_passthrough(text):
    redacted, log = _redact(text)
    assert redacted == text
    assert log == []


# ── Boundary integration: uppercase remittance text through the provider
#    prompt input ─────────────────────────────────────────────────────────────


def test_provider_prompt_input_redacts_uppercase_remittance_text():
    pi = ProviderDenialPromptInput(
        denial_reason_text=(
            "PATIENT: MARGARET HALE DOB: 03/12/1948. These are non-covered "
            "services because this is not deemed a medical necessity."
        )
    )
    assert "MARGARET" not in pi.redacted_reason
    assert "HALE" not in pi.redacted_reason
    assert "03/12/1948" not in pi.redacted_reason
    assert "[PATIENT_NAME]" in pi.redacted_reason
    assert "[DOB]" in pi.redacted_reason
    assert "medical necessity" in pi.redacted_reason
    assert set(pi.redaction_summary["types"]) >= {"[PATIENT_NAME]", "[DOB]"}


# ── Known gaps: documented residual risk, strict-xfail so a fix flips them ──

GAP_CASES = [
    pytest.param(
        "The beneficiary was born on 03/12/1948.",
        ["03/12/1948"],
        id="gap-unlabeled-dob",
    ),
    pytest.param(
        "Patient resides at 123 Main Street, Apt 4B, Springfield.",
        ["Main Street"],
        id="gap-street-address",
    ),
    pytest.param(
        "MRN: 445-291-88 was reviewed.",
        ["445-291-88"],
        id="gap-mrn-label",
    ),
]


@pytest.mark.parametrize("text,leaks", GAP_CASES)
@pytest.mark.xfail(strict=True, reason="known recall gap — documented residual risk")
def test_known_gaps(text, leaks):
    redacted, _ = _redact(text)
    for leak in leaks:
        assert leak not in redacted
