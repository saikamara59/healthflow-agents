# evals

Agent evaluation harnesses. These live in the repo but are NOT shipped in the
wheel — they score agent behavior during development.

## translate — coverage-translation accuracy benchmark

Migrated from HealthFlow (`healthflow/evals/translate/`). Runs the
TranslationAgent over curated Q&A cases built from a real Summary of Benefits
document (see `translate/fixtures/provenance.md`), grades answerable cases
with an LLM judge (Sonnet), and checks abstention on unanswerable ones.

```bash
pip install -e ".[evals]"
LIVE_EVAL=1 ANTHROPIC_API_KEY=sk-... python -m evals.translate.run
```

- `LIVE_EVAL=1` is a guard — the run calls the live Anthropic API.
- Output: summary to stdout + `evals/translate/report.json` (last committed
  report is the current benchmark baseline).
- Unit tests for the harness itself (loader, judge parsing, scorer, report)
  run offline as part of the normal suite: `pytest`.
