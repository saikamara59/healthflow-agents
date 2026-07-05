"""Cost-calculator agent, ported from healthflow.agents.cost_calculator_agent.

Prompt-building logic is verbatim; only construction (AgentBase injection)
and the system-prompt source (prompts/cost_calculator_agent.md) changed.
"""
from typing import Any

from healthflow_agents.contracts import PlanCostResult, PlanSummary, UsageInput
from healthflow_agents.core.base import AgentBase
from healthflow_agents.core.client import extract_text
from healthflow_agents.core.models import CLAUDE_MODEL_HAIKU
from healthflow_agents.redaction.prompt_inputs import CostPromptInput
from healthflow_agents.tools.cost_modeler import CostModeler


class CostCalculatorAgent(AgentBase):
    model = CLAUDE_MODEL_HAIKU
    agent_name = "cost_calculator"
    prompt_file = "cost_calculator_agent.md"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.modeler = CostModeler()

    def calculate(
        self,
        plans: list[PlanSummary],
        usage: UsageInput,
    ) -> tuple[list[PlanCostResult], str]:
        with self.invocations(
            agent=self.agent_name, event_type="calculate", model=self.model
        ) as inv:
            results = [self.modeler.calculate(plan, usage) for plan in plans]
            results.sort(key=lambda r: r.total_annual_cost)

            prompt_input = CostPromptInput(results=results, usage=usage)
            user_prompt = self._build_prompt(prompt_input)

            self.audit.log(
                "tool_called",
                {"tool": "claude_api", "model": self.model, "task": "calculate"},
            )

            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=self.system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            recommendation = extract_text(response)
            self.audit.log(
                "recommendation_generated",
                {"length": len(recommendation), "task": "calculate"},
            )

            inv.details = {"length": len(recommendation), "plans": len(plans)}
            return results, recommendation

    def _build_prompt(self, prompt_input: CostPromptInput) -> str:
        results = prompt_input.results
        usage = prompt_input.usage

        lines = [
            "Compare these Medicare Advantage plans by estimated annual out-of-pocket cost.",
            "",
            f"User's expected usage: {usage.doctor_visits_per_year} doctor visits/year",
        ]

        if usage.prescriptions:
            rx_list = ", ".join(
                f"{rx.name} ({rx.fills_per_year}x/year)" for rx in usage.prescriptions
            )
            lines.append(f"Prescriptions: {rx_list}")

        if usage.procedures:
            proc_list = ", ".join(
                f"{p.name} ({p.count}x/year)" for p in usage.procedures
            )
            lines.append(f"Procedures: {proc_list}")

        lines.append("")
        lines.append("## Plans (ranked by total cost, cheapest first)")
        lines.append("")

        for i, r in enumerate(results, 1):
            lines.append(f"### #{i}: {r.plan_name} ({r.plan_id})")
            lines.append(f"- Annual Premium: ${r.annual_premium:.2f}")
            lines.append(f"- Annual Care Cost: ${r.annual_care_cost:.2f}")
            lines.append(f"- **Total Annual Cost: ${r.total_annual_cost:.2f}**")
            lines.append(f"- Doctor Visits: ${r.breakdown.doctor_visit_costs:.2f}")
            lines.append(f"- Prescriptions: ${r.breakdown.prescription_costs:.2f}")
            lines.append(f"- Procedures: ${r.breakdown.procedure_costs:.2f}")
            if r.breakdown.oop_cap_applied:
                lines.append(f"- OOP Max Cap Applied (saved ${r.breakdown.total_before_oop_cap - r.breakdown.final_care_cost:.2f})")

            if r.prescription_details:
                for rx in r.prescription_details:
                    fills = int(rx.annual_cost / rx.cost_per_fill) if rx.cost_per_fill > 0 else 0
                    lines.append(f"  - {rx.name}: ${rx.cost_per_fill:.2f}/fill x {fills} = ${rx.annual_cost:.2f}/year")

            lines.append("")

        lines.append(
            "Recommend the best plan for this user's usage. Focus on total annual cost "
            "and where the savings come from. Do NOT give medical advice."
        )

        return "\n".join(lines)
