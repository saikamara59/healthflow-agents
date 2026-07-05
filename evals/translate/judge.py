from __future__ import annotations

import json
from dataclasses import dataclass

from healthflow_agents.core.client import extract_text, strip_code_fence
from healthflow_agents.core.models import CLAUDE_MODEL_SONNET
from healthflow_agents.contracts import DocumentSection

SYSTEM_PROMPT = (
    "You are a strict grader for an insurance-document Q&A assistant. "
    "You judge ONLY whether the assistant's answer is supported by the provided "
    "document sections — never by your own knowledge of insurance. "
    "Respond with a single JSON object and nothing else."
)


@dataclass(frozen=True)
class JudgeVerdict:
    faithful: bool
    hallucinated: bool
    contradicts_gold: bool
    rationale: str


def _build_prompt(sections, question, gold_answer, agent_answer) -> str:
    lines = ["DOCUMENT SECTIONS:", ""]
    for s in sections:
        lines += [f"## {s.title}", s.content, ""]
    lines += [
        "---",
        f"QUESTION: {question}",
        f"REFERENCE (known-correct) ANSWER: {gold_answer}",
        f"ASSISTANT ANSWER: {agent_answer}",
        "",
        "Judge the assistant answer. Return JSON with exactly these keys:",
        '{"faithful": bool, "hallucinated": bool, "contradicts_gold": bool, "rationale": "one short sentence"}',
        "- faithful: every claim in the assistant answer is supported by the document sections.",
        "- hallucinated: the assistant answer asserts a benefit/number NOT in the document sections.",
        "- contradicts_gold: the assistant answer disagrees with the reference answer.",
    ]
    return "\n".join(lines)


def _parse(text: str) -> JudgeVerdict:
    data = json.loads(strip_code_fence(text))
    return JudgeVerdict(
        faithful=bool(data["faithful"]),
        hallucinated=bool(data["hallucinated"]),
        contradicts_gold=bool(data["contradicts_gold"]),
        rationale=str(data.get("rationale", "")),
    )


def judge(client, sections: list[DocumentSection], question: str, gold_answer: str, agent_answer: str) -> JudgeVerdict:
    """Grade an agent answer with an LLM judge. Retries once on malformed JSON."""
    prompt = _build_prompt(sections, question, gold_answer, agent_answer)
    last_err: Exception | None = None
    for _ in range(2):
        resp = client.messages.create(
            model=CLAUDE_MODEL_SONNET,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            return _parse(extract_text(resp))
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            last_err = e
    raise ValueError(f"judge returned unparseable output twice: {last_err}")
