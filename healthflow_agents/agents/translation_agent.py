"""Document-translation agent, ported from healthflow.agents.translation_agent.

Prompt-building logic and the phi_redacted audit contract are verbatim; only
construction (AgentBase injection) and the system-prompt source
(prompts/translation_agent.md) changed.
"""
from healthflow_agents.contracts import DocumentSection
from healthflow_agents.core.base import AgentBase
from healthflow_agents.core.client import extract_text
from healthflow_agents.core.models import CLAUDE_MODEL_SONNET
from healthflow_agents.redaction.prompt_inputs import (
    RedactedSection,
    TranslationPromptInput,
)


class TranslationAgent(AgentBase):
    model = CLAUDE_MODEL_SONNET
    agent_name = "translation"
    prompt_file = "translation_agent.md"

    def translate(
        self,
        sections: list[DocumentSection],
        question: str,
    ) -> tuple[str, list[str]]:
        with self.invocations(
            agent=self.agent_name, event_type="translate", model=self.model
        ) as inv:
            prompt_input = TranslationPromptInput(
                sections=tuple(
                    RedactedSection(title=s.title, content=s.content) for s in sections
                ),
                question=question,
            )
            section_titles = [s.title for s in prompt_input.sections]

            self.audit.log("phi_redacted", prompt_input.redaction_summary)

            user_prompt = self._build_prompt(prompt_input)

            self.audit.log(
                "tool_called",
                {"tool": "claude_api", "model": self.model, "task": "translate"},
            )

            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=self.system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            answer = extract_text(response)
            self.audit.log("recommendation_generated", {"length": len(answer), "task": "translate"})
            inv.details = {"length": len(answer), "section_count": len(section_titles)}
            return answer, section_titles

    def _build_prompt(self, prompt_input: TranslationPromptInput) -> str:
        lines = [
            "Below are relevant sections from a health insurance Summary of Benefits document.",
            "",
        ]

        for section in prompt_input.sections:
            lines.append(f"## {section.title}")
            lines.append(section.content)
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append(f"Question: {prompt_input.question}")
        lines.append("")
        lines.append(
            "Answer this question in plain English based on the document sections above. "
            "Be specific about dollar amounts, copays, and conditions. "
            "If the information is not in the document, say so clearly."
        )

        return "\n".join(lines)
