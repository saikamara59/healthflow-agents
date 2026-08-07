"""Each agent is pinned to a Claude model tier matched to its task complexity
(see healthflow_agents/core/models.py). These tests lock the tier contract so
a careless edit can't silently move an agent onto a more/less expensive model.

- AppealAgent        -> Opus   (high-stakes regulatory/legal reasoning)
- TranslationAgent   -> Sonnet (nuanced extraction from policy text)
- BatchInsightsAgent -> Sonnet (inference over batch aggregates)
- Comparison/Cost/Network -> Haiku (narrating tool-computed structured data)
"""
from helpers import make_mock_client

from healthflow_agents.agents import (
    AppealAgent,
    BatchInsightsAgent,
    ComparisonAgent,
    CostCalculatorAgent,
    NetworkAgent,
    TranslationAgent,
)
from healthflow_agents.contracts import PlanSummary
from healthflow_agents.core import models


def test_tier_constants_are_current_ga_ids():
    assert models.CLAUDE_MODEL_OPUS == "claude-opus-4-8"
    assert models.CLAUDE_MODEL_SONNET == "claude-sonnet-4-6"
    assert models.CLAUDE_MODEL_HAIKU == "claude-haiku-4-5"
    # Back-compat default stays on Sonnet for any caller still importing it.
    assert models.CLAUDE_MODEL == models.CLAUDE_MODEL_SONNET


def test_appeal_agent_uses_opus():
    assert AppealAgent.model == models.CLAUDE_MODEL_OPUS


def test_translation_agent_uses_sonnet():
    assert TranslationAgent.model == models.CLAUDE_MODEL_SONNET


def test_batch_insights_agent_uses_sonnet():
    """Sonnet, not Haiku, and deliberately so: insights *infer* root causes,
    payer patterns, and prevention recommendations from aggregates. The Haiku
    agents below only narrate figures a tool already computed — nothing in
    their output is a judgement. Moving insights down a tier trades away the
    reasoning the feature exists to provide."""
    assert BatchInsightsAgent.model == models.CLAUDE_MODEL_SONNET


def test_summarize_only_agents_use_haiku():
    assert ComparisonAgent.model == models.CLAUDE_MODEL_HAIKU
    assert CostCalculatorAgent.model == models.CLAUDE_MODEL_HAIKU
    assert NetworkAgent.model == models.CLAUDE_MODEL_HAIKU


def test_tier_reaches_messages_create():
    """Guard against the binding being correct but not actually passed to the
    API call — assert the model kwarg on a representative (Haiku) agent."""
    mock_client = make_mock_client("Plan A.")

    plan = PlanSummary(
        plan_name="Aetna Medicare Eagle Plus (HMO)",
        plan_id="H3312-034",
        monthly_premium=0.0,
        annual_deductible=250.0,
        out_of_pocket_max=4500.0,
        star_rating=4.5,
        plan_type="HMO",
        drug_coverage=True,
        estimated_medication_costs={"Metformin": 5.0},
        estimated_procedure_costs={"MRI": 150.0},
    )

    ComparisonAgent(client=mock_client).recommend(
        plans=[plan], age=65, income_level="low"
    )

    call = mock_client.messages.create.call_args
    assert call.kwargs["model"] == "claude-haiku-4-5"
