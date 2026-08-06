# Batch insights input is structured aggregates only — no free text crosses

`BatchInsightsAgent` takes a frozen `BatchAggregates` contract of counts,
dollars, buckets, and enum-keyed rollups; denial free text, letters, and
refined recommendations never reach it. This keeps the insights prompt
entirely outside the PHI-redaction boundary (there is no BAA with Anthropic —
see `docs/2026-05-14-phi-redaction-design.md`): with no free-text field in the
contract, redaction correctness is guaranteed by construction rather than by
recall. The trade-off is a shallower narrative — the agent can name *which*
CARC codes and payers dominate, but cannot quote *why* individual claims were
denied.

## Consequences

- Adding any free-text field to `BatchAggregates` (denial reason samples,
  dismissal notes, letter excerpts) re-opens the redaction question and must
  route through a frozen `PromptInput` model in `redaction/` like every other
  free-text path. Do not add one casually; the omission is deliberate.
- CARC descriptions in the prompt come from the package's curated
  `DenialCodeDB` (agent-side enrichment), never from host-supplied text.
- Dismissal-reason counts are keyed by the host's closed enum
  (`payer_correct | too_small | deadline_passed | other`), not user prose.
