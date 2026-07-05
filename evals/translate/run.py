from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env before constructing clients: the live run needs
# ANTHROPIC_API_KEY in the environment.
load_dotenv()

import anthropic  # noqa: E402

from healthflow_agents import TranslationAgent  # noqa: E402
from evals.translate.judge import judge  # noqa: E402
from evals.translate.loader import load_cases  # noqa: E402
from evals.translate.report import aggregate, render_summary, write_report  # noqa: E402
from evals.translate.runner import run_case  # noqa: E402
from evals.translate.scorer import score  # noqa: E402

_HERE = Path(__file__).parent
CASES_PATH = _HERE / "cases.yaml"
REPORT_PATH = _HERE / "report.json"


def main() -> int:
    if os.getenv("LIVE_EVAL") != "1":
        print("Refusing to run: set LIVE_EVAL=1 (this calls the live Anthropic API). "
              "Run: LIVE_EVAL=1 python -m evals.translate.run", file=sys.stderr)
        return 2
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return 2

    cases = load_cases(CASES_PATH)
    agent = TranslationAgent()
    client = anthropic.Anthropic()

    scores = []
    for case in cases:
        run = run_case(agent, case)
        verdict = None
        if case.answerable:
            verdict = judge(client, case.sections, case.question, case.gold_answer, run.answer)
        scores.append(score(run, verdict))

    report = aggregate(scores)
    write_report(report, REPORT_PATH)
    print(render_summary(report))
    print(f"\nWrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
