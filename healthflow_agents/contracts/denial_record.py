"""Provider-side (RCM) denial contracts.

Additive to the patient-side contracts in schemas.py — nothing there changes.
A DenialRecord is one denied claim line from a remittance; BatchResult is the
outcome of running AppealAgent over a batch of them.
"""
from datetime import date

from pydantic import BaseModel, Field

from healthflow_agents.contracts.schemas import CoverageArgument, DenialAnalysis


class DenialRecord(BaseModel):
    """One denied claim from a payer remittance (simplified 835 line).

    `denial_reason_text` is free text and may contain patient identifiers —
    it MUST cross the redaction boundary (ProviderDenialPromptInput) before
    reaching any prompt. All other fields are structured claim metadata.
    """

    claim_id: str
    payer: str
    carc_code: str
    rarc_codes: list[str] = Field(default_factory=list)
    denial_reason_text: str
    billed_amount: float = Field(..., ge=0)
    service_date: date
    denial_date: date
    appeal_deadline: date | None = None


class AppealOutput(BaseModel):
    """The appeal artifacts for one successfully processed record.

    Mirrors the tuple returned by AppealAgent.process_appeal /
    process_denial_record: (analysis, argument, letter, refined).
    """

    analysis: DenialAnalysis
    argument: CoverageArgument
    appeal_letter: str
    refined_recommendation: str


class RecordOutcome(BaseModel):
    """Per-record batch outcome: success with appeal output, or a structured
    failure. Failures never carry exceptions — error type/message only."""

    record: DenialRecord
    success: bool
    appeal: AppealOutput | None = None
    error_type: str | None = None
    error_message: str | None = None


class BatchSummary(BaseModel):
    total_records: int
    succeeded: int
    failed: int
    total_billed_amount: float
    records_by_carc: dict[str, int]
    billed_by_carc: dict[str, float]


class BatchResult(BaseModel):
    outcomes: list[RecordOutcome]
    summary: BatchSummary
