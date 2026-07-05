"""Data contracts, ported field-for-field from healthflow.models.schemas."""
from pydantic import BaseModel, Field


class PlanSummary(BaseModel):
    plan_name: str
    plan_id: str
    monthly_premium: float
    annual_deductible: float
    out_of_pocket_max: float
    star_rating: float = Field(..., ge=1.0, le=5.0)
    plan_type: str
    drug_coverage: bool
    estimated_medication_costs: dict[str, float] | None = None
    estimated_procedure_costs: dict[str, float] | None = None


class DocumentSection(BaseModel):
    title: str
    content: str


class PrescriptionInput(BaseModel):
    name: str
    fills_per_year: int = Field(..., ge=1, le=365)


class ProcedureInput(BaseModel):
    name: str
    count: int = Field(..., ge=1, le=365)


class UsageInput(BaseModel):
    doctor_visits_per_year: int = Field(..., ge=0, le=365)
    prescriptions: list[PrescriptionInput] = Field(
        default_factory=list, max_length=20
    )
    procedures: list[ProcedureInput] = Field(
        default_factory=list, max_length=20
    )


class PrescriptionDetail(BaseModel):
    name: str
    cost_per_fill: float
    annual_cost: float


class ProcedureDetail(BaseModel):
    name: str
    cost_per_visit: float
    annual_cost: float


class CostBreakdown(BaseModel):
    premium_total: float
    deductible_spent: float
    doctor_visit_costs: float
    prescription_costs: float
    procedure_costs: float
    total_before_oop_cap: float
    oop_cap_applied: bool
    final_care_cost: float


class PlanCostResult(BaseModel):
    plan_name: str
    plan_id: str
    annual_premium: float
    annual_care_cost: float
    total_annual_cost: float
    breakdown: CostBreakdown
    prescription_details: list[PrescriptionDetail]
    procedure_details: list[ProcedureDetail]


class DenialAnalysis(BaseModel):
    denial_reason_code: str | None
    denial_reason: str
    treatment_denied: str
    policy_section_cited: str | None
    appeal_deadline: str | None
    denial_date: str | None


class CoverageArgument(BaseModel):
    cms_rule: str
    common_appeal_grounds: list[str]
    success_precedents: list[str]


class ProviderInput(BaseModel):
    name: str
    npi: str | None = None


class ProviderResult(BaseModel):
    name: str
    npi: str | None
    npi_verified: bool
    specialty: str | None
    in_network: bool
    warning: str | None


class FormularyResult(BaseModel):
    drug_name: str
    on_formulary: bool
    tier: str | None
    copay: float | None
    prior_auth_required: bool
    warning: str | None


class PlanNetworkResult(BaseModel):
    plan_name: str
    plan_id: str
    provider_results: list[ProviderResult]
    formulary_results: list[FormularyResult]
