"""Plan-comparison agent, ported from healthflow.agents.comparison_agent.

Prompt-building logic and the HEALTHFLOW_TEST_MODE stub are verbatim; only
construction (AgentBase injection) and the system-prompt source (prompts/
comparison_agent.md) changed.
"""
import os

from healthflow_agents.contracts import PlanSummary
from healthflow_agents.core.base import AgentBase
from healthflow_agents.core.client import extract_text
from healthflow_agents.core.models import CLAUDE_MODEL_HAIKU
from healthflow_agents.redaction.prompt_inputs import ComparisonPromptInput

# Deterministic stub for the e2e docker stack, which runs with a fake Anthropic
# API key. Returned verbatim when HEALTHFLOW_TEST_MODE=1.
_TEST_MODE_RECOMMENDATION = (
    "Plans are ranked by total estimated cost given your profile. "
    "Review the list for premium, deductible, and star-rating differences."
)


class ComparisonAgent(AgentBase):
    model = CLAUDE_MODEL_HAIKU
    agent_name = "comparison"
    prompt_file = "comparison_agent.md"

    def recommend(
        self,
        plans: list[PlanSummary],
        age: int,
        income_level: str,
        medications: list[str] | None = None,
        procedures: list[str] | None = None,
    ) -> str:
        with self.invocations(
            agent=self.agent_name, event_type="recommend", model=self.model
        ) as inv:
            if os.environ.get("HEALTHFLOW_TEST_MODE") == "1":
                self.audit.log(
                    "recommendation_generated",
                    {"length": len(_TEST_MODE_RECOMMENDATION), "stubbed": True},
                )
                inv.details = {"length": len(_TEST_MODE_RECOMMENDATION), "stubbed": True}
                return _TEST_MODE_RECOMMENDATION

            prompt_input = ComparisonPromptInput(
                plans=plans,
                age=age,
                income_level=income_level,
                medications=medications or [],
                procedures=procedures or [],
            )
            user_prompt = self._build_prompt(prompt_input)

            self.audit.log("tool_called", {"tool": "claude_api", "model": self.model})

            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=self.system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            recommendation = extract_text(response)
            self.audit.log("recommendation_generated", {"length": len(recommendation)})
            inv.details = {"length": len(recommendation), "plans": len(plans)}
            return recommendation

    def _build_prompt(self, prompt_input: ComparisonPromptInput) -> str:
        plans = prompt_input.plans
        age = prompt_input.age
        income_level = prompt_input.income_level
        medications = prompt_input.medications
        procedures = prompt_input.procedures

        lines = [
            f"Compare these Medicare Advantage plans for a {age}-year-old with {income_level} income.",
            "",
            "## Plans",
            "",
        ]

        for i, plan in enumerate(plans, 1):
            lines.append(f"### Plan {i}: {plan.plan_name} ({plan.plan_id})")
            lines.append(f"- Type: {plan.plan_type}")
            lines.append(f"- Monthly Premium: ${plan.monthly_premium:.2f}")
            lines.append(f"- Annual Deductible: ${plan.annual_deductible:.2f}")
            lines.append(f"- Out-of-Pocket Max: ${plan.out_of_pocket_max:.2f}")
            lines.append(f"- Star Rating: {plan.star_rating}/5.0")
            lines.append(f"- Drug Coverage: {'Yes' if plan.drug_coverage else 'No'}")

            if plan.estimated_medication_costs:
                lines.append("- Medication Costs:")
                for med, cost in plan.estimated_medication_costs.items():
                    lines.append(f"  - {med}: ${cost:.2f}/month")

            if plan.estimated_procedure_costs:
                lines.append("- Procedure Costs:")
                for proc, cost in plan.estimated_procedure_costs.items():
                    lines.append(f"  - {proc}: ${cost:.2f}")

            lines.append("")

        if medications:
            lines.append(f"The user takes these medications: {', '.join(medications)}")
        if procedures:
            lines.append(f"The user needs these procedures: {', '.join(procedures)}")

        lines.append("")
        lines.append(
            "Provide a clear comparison and recommend the best plan for this user's "
            "situation. Focus on total estimated costs and value. Do NOT give any medical advice."
        )

        return "\n".join(lines)
