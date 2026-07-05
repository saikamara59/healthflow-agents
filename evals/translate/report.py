from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from evals.translate.scorer import CaseScore


@dataclass(frozen=True)
class EvalReport:
    faithfulness_rate: float | None
    abstention_accuracy: float | None
    hallucination_rate: float | None
    pass_rate: float | None
    cases: list[CaseScore]


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 3)


def aggregate(scores: list[CaseScore]) -> EvalReport:
    answerable = [s for s in scores if s.answerable]
    unanswerable = [s for s in scores if not s.answerable]
    return EvalReport(
        faithfulness_rate=_rate(sum(1 for s in answerable if s.faithful), len(answerable)),
        hallucination_rate=_rate(sum(1 for s in answerable if s.hallucinated), len(answerable)),
        abstention_accuracy=_rate(sum(1 for s in unanswerable if s.abstained), len(unanswerable)),
        pass_rate=_rate(sum(1 for s in scores if s.passed), len(scores)),
        cases=list(scores),
    )


def _fmt(rate: float | None) -> str:
    return "n/a" if rate is None else f"{rate:.1%}"


def render_summary(report: EvalReport) -> str:
    lines = [
        "Translate accuracy benchmark",
        "============================",
        f"  pass rate           : {_fmt(report.pass_rate)}",
        f"  faithfulness        : {_fmt(report.faithfulness_rate)}",
        f"  hallucination rate  : {_fmt(report.hallucination_rate)}",
        f"  abstention accuracy : {_fmt(report.abstention_accuracy)}",
        "",
    ]
    for c in report.cases:
        flag = "PASS" if c.passed else "FAIL"
        lines.append(f"  [{flag}] {c.case_id}")
    return "\n".join(lines)


def write_report(report: EvalReport, path: Path) -> None:
    payload = {
        "faithfulness_rate": report.faithfulness_rate,
        "abstention_accuracy": report.abstention_accuracy,
        "hallucination_rate": report.hallucination_rate,
        "pass_rate": report.pass_rate,
        "cases": [asdict(c) for c in report.cases],
    }
    Path(path).write_text(json.dumps(payload, indent=2))
