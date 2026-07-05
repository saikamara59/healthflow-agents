"""Network-verification agent, ported from healthflow.agents.network_agent.

Prompt-building and verification logic are verbatim; only construction
(AgentBase injection) and the system-prompt source (prompts/network_agent.md)
changed.
"""
from typing import Any

from healthflow_agents.contracts import (
    FormularyResult,
    PlanNetworkResult,
    PlanSummary,
    ProviderInput,
    ProviderResult,
)
from healthflow_agents.core.base import AgentBase
from healthflow_agents.core.client import extract_text
from healthflow_agents.core.models import CLAUDE_MODEL_HAIKU
from healthflow_agents.redaction.prompt_inputs import NetworkPromptInput
from healthflow_agents.tools.formulary_checker import FormularyChecker
from healthflow_agents.tools.provider_cache import InMemoryProviderCache
from healthflow_agents.tools.provider_checker import ProviderChecker


class NetworkAgent(AgentBase):
    model = CLAUDE_MODEL_HAIKU
    agent_name = "network"
    prompt_file = "network_agent.md"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._cache = InMemoryProviderCache()
        self._provider_checker = ProviderChecker(cache=self._cache)
        self._formulary_checker = FormularyChecker()

    def verify(
        self,
        plans: list[PlanSummary],
        providers: list[ProviderInput],
        prescriptions: list[str],
    ) -> tuple[list[PlanNetworkResult], str]:
        with self.invocations(
            agent=self.agent_name, event_type="verify", model=self.model
        ) as inv:
            inv.details = {
                "plans": len(plans),
                "providers": len(providers),
                "prescriptions": len(prescriptions),
            }
            return self._verify_inner(plans, providers, prescriptions)

    def _verify_inner(
        self,
        plans: list[PlanSummary],
        providers: list[ProviderInput],
        prescriptions: list[str],
    ) -> tuple[list[PlanNetworkResult], str]:
        plan_results: list[PlanNetworkResult] = []

        for plan in plans:
            provider_results: list[ProviderResult] = []
            for provider in providers:
                result = self._provider_checker.check(
                    provider.name, provider.npi, plan.plan_id
                )
                provider_results.append(result)
                self.audit.log("provider_checked", {
                    "provider": provider.name,
                    "plan_id": plan.plan_id,
                    "in_network": result.in_network,
                })

            formulary_results: list[FormularyResult] = []
            for drug_name in prescriptions:
                result = self._formulary_checker.check(
                    drug_name, plan.plan_id, plan.plan_type
                )
                formulary_results.append(result)
                self.audit.log("formulary_checked", {
                    "drug": drug_name,
                    "plan_id": plan.plan_id,
                    "on_formulary": result.on_formulary,
                })

            plan_results.append(PlanNetworkResult(
                plan_name=plan.plan_name,
                plan_id=plan.plan_id,
                provider_results=provider_results,
                formulary_results=formulary_results,
            ))

        # Sort: most in-network providers first, then most on-formulary drugs
        plan_results.sort(
            key=lambda r: (
                sum(1 for p in r.provider_results if p.in_network),
                sum(1 for f in r.formulary_results if f.on_formulary),
            ),
            reverse=True,
        )

        recommendation = self._get_recommendation(plan_results)

        return plan_results, recommendation

    def _build_prompt(self, prompt_input: NetworkPromptInput) -> str:
        plan_results = prompt_input.plan_results

        lines = ["Network verification results:\n"]
        for pr in plan_results:
            in_net = sum(1 for p in pr.provider_results if p.in_network)
            total_prov = len(pr.provider_results)
            on_form = sum(1 for f in pr.formulary_results if f.on_formulary)
            total_drugs = len(pr.formulary_results)

            lines.append(f"Plan: {pr.plan_name} ({pr.plan_id})")
            lines.append(f"  Providers in-network: {in_net}/{total_prov}")
            for p in pr.provider_results:
                status = "IN-NETWORK" if p.in_network else "OUT-OF-NETWORK"
                lines.append(f"    - {p.name}: {status} (NPI verified: {p.npi_verified})")
                if p.warning:
                    lines.append(f"      Warning: {p.warning}")

            lines.append(f"  Drugs on formulary: {on_form}/{total_drugs}")
            for f in pr.formulary_results:
                status = "ON FORMULARY" if f.on_formulary else "NOT ON FORMULARY"
                tier_info = f" ({f.tier}, ${f.copay}/mo)" if f.tier and f.copay else ""
                lines.append(f"    - {f.drug_name}: {status}{tier_info}")
                if f.warning:
                    lines.append(f"      Warning: {f.warning}")

            lines.append("")

        lines.append(
            "Based on these results, which plan(s) offer the best network "
            "coverage? Summarize key findings concisely."
        )
        return "\n".join(lines)

    def _get_recommendation(self, plan_results: list[PlanNetworkResult]) -> str:
        prompt_input = NetworkPromptInput(plan_results=plan_results)
        user_prompt = self._build_prompt(prompt_input)

        self.audit.log(
            "tool_called",
            {"tool": "claude_api", "model": self.model, "task": "network_verify"},
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=self.system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        return extract_text(response)
