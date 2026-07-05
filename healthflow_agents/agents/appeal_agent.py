"""Appeal agent, ported from healthflow.agents.appeal_agent.

The refine prompt, fallback constants, orchestration flow, and the
phi_redacted audit contract are verbatim; only construction (AgentBase
injection) and the system-prompt source (prompts/appeal_agent.md) changed.
"""
from typing import Any

from healthflow_agents.contracts import CoverageArgument, DenialAnalysis
from healthflow_agents.core.base import AgentBase
from healthflow_agents.core.client import extract_text
from healthflow_agents.core.models import CLAUDE_MODEL_OPUS
from healthflow_agents.redaction.prompt_inputs import AppealPromptInput
from healthflow_agents.tools.appeal_writer import AppealWriter
from healthflow_agents.tools.denial_codes import DenialCodeDB
from healthflow_agents.tools.denial_parser import DenialParser

FALLBACK_CMS_RULE = (
    "Medicare beneficiaries have the right to appeal any coverage denial under "
    "42 CFR §405.904. The appeals process includes redetermination, reconsideration, "
    "ALJ hearing, Medicare Appeals Council review, and federal court review."
)

FALLBACK_APPEAL_GROUNDS = [
    "Request a detailed explanation of the denial reason",
    "Provide complete medical records and clinical documentation",
    "Include a physician letter supporting the medical necessity of the service",
    "Reference applicable Medicare coverage guidelines (LCD/NCD)",
    "Request a peer-to-peer review with the plan's medical director",
]

FALLBACK_PRECEDENTS = [
    "42 CFR §405.904 — Medicare appeals rights",
    "42 CFR §405.940-405.958 — Redetermination process",
    "CMS Medicare Claims Processing Manual Chapter 29 — Appeals",
]


class AppealAgent(AgentBase):
    """Orchestrates the full appeal process: redact, parse, lookup, write, refine."""

    model = CLAUDE_MODEL_OPUS
    agent_name = "appeal"
    prompt_file = "appeal_agent.md"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.parser = DenialParser()
        self.code_db = DenialCodeDB()
        self.writer = AppealWriter()

    def process_appeal(
        self,
        denial_text: str,
        additional_context: str,
    ) -> tuple[DenialAnalysis, CoverageArgument, str, str]:
        """Process a denial letter and generate an appeal.

        Returns:
            (analysis, coverage_argument, appeal_letter, refined_recommendation)
        """
        with self.invocations(
            agent=self.agent_name, event_type="process_appeal", model=self.model
        ) as inv:
            return self._process_appeal_inner(inv, denial_text, additional_context)

    def _process_appeal_inner(
        self, inv: Any, denial_text: str, additional_context: str
    ) -> tuple[DenialAnalysis, CoverageArgument, str, str]:
        # Step 1: Redact PHI — AppealPromptInput is the single redaction boundary.
        prompt_input = AppealPromptInput(
            denial_text=denial_text,
            additional_context=additional_context,
        )
        redacted_denial = prompt_input.redacted_denial
        redacted_context = prompt_input.redacted_context

        self.audit.log("phi_redacted", prompt_input.redaction_summary)

        # Step 2: Parse denial details
        analysis = self.parser.parse(redacted_denial)

        self.audit.log("denial_parsed", {
            "code": analysis.denial_reason_code,
            "treatment": analysis.treatment_denied,
            "has_deadline": analysis.appeal_deadline is not None,
        })

        # Step 3: Look up denial code
        code_entry = None
        if analysis.denial_reason_code:
            code_entry = self.code_db.lookup(analysis.denial_reason_code)

        # Step 4: If not found, try keyword search
        if code_entry is None and analysis.denial_reason:
            code_entry = self.code_db.search_by_keyword(analysis.denial_reason)

        # Step 5: Build coverage argument
        if code_entry:
            argument = CoverageArgument(
                cms_rule=code_entry["cms_rule"],
                common_appeal_grounds=code_entry["appeal_grounds"],
                success_precedents=code_entry["precedents"],
            )
        else:
            argument = CoverageArgument(
                cms_rule=FALLBACK_CMS_RULE,
                common_appeal_grounds=FALLBACK_APPEAL_GROUNDS,
                success_precedents=FALLBACK_PRECEDENTS,
            )

        # Step 6: Generate appeal letter
        appeal_letter = self.writer.generate(analysis, argument)

        # Step 7: Call Claude to refine (redacted text only)
        refined_recommendation = self._refine_with_claude(
            redacted_denial, redacted_context, analysis, argument
        )

        self.audit.log("appeal_generated", {
            "code": analysis.denial_reason_code,
            "code_found_in_db": code_entry is not None,
            "letter_length": len(appeal_letter),
        })

        inv.details = {
            "code": analysis.denial_reason_code,
            "code_found_in_db": code_entry is not None,
            "letter_length": len(appeal_letter),
            "refined_length": len(refined_recommendation),
        }
        return analysis, argument, appeal_letter, refined_recommendation

    def _refine_with_claude(
        self,
        redacted_denial: str,
        redacted_context: str,
        analysis: DenialAnalysis,
        argument: CoverageArgument,
    ) -> str:
        """Call Claude with redacted text to refine appeal arguments."""
        user_prompt_parts = [
            "Denial letter (PHI redacted):",
            redacted_denial,
            "",
            f"Denial Code: {analysis.denial_reason_code or 'Not identified'}",
            f"Denial Reason: {analysis.denial_reason}",
            f"Treatment Denied: {analysis.treatment_denied}",
            "",
            f"CMS Rule: {argument.cms_rule}",
            "",
            "Current appeal grounds:",
        ]
        for ground in argument.common_appeal_grounds:
            user_prompt_parts.append(f"- {ground}")

        if redacted_context:
            user_prompt_parts.append("")
            user_prompt_parts.append(f"Additional context: {redacted_context}")

        user_prompt_parts.append("")
        user_prompt_parts.append(
            "Based on the denial details above, suggest any additional appeal arguments, "
            "documentation to include, or procedural steps the patient should consider. "
            "Be specific and reference applicable regulations."
        )

        user_prompt = "\n".join(user_prompt_parts)

        self.audit.log("tool_called", {
            "tool": "claude_api",
            "model": self.model,
            "task": "appeal_refine",
        })

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=self.system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        recommendation = extract_text(response)
        self.audit.log("recommendation_generated", {
            "length": len(recommendation),
            "task": "appeal_refine",
        })
        return recommendation
