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
