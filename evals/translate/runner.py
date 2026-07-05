from __future__ import annotations

from dataclasses import dataclass

from evals.translate.loader import EvalCase


@dataclass(frozen=True)
class AgentRun:
    case: EvalCase
    answer: str


def run_case(agent, case: EvalCase) -> AgentRun:
    """Invoke the translation agent on one case and capture its answer.

    `agent` is any object with `.translate(sections, question) -> (answer, titles)`
    — the real `TranslationAgent` in production, a fake in tests. The echoed
    section titles are intentionally discarded (the agent doesn't emit true
    citations; see the spec's non-goals).
    """
    answer, _titles = agent.translate(case.sections, case.question)
    return AgentRun(case=case, answer=answer)
