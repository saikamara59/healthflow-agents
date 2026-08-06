# Batch Insights (BatchInsightsAgent) — package design

2026-08-05. Package-side companion to the Overturn host spec's "Stage 2 —
Batch insights panel" section, which defines what the host feeds and renders.
Vocabulary per CONTEXT.md; boundary decision recorded in ADR 0001.

## Problem Statement

An RCM manager working a batch of denied claims in Overturn sees deterministic
bars only — counts, dollars, statuses. Nothing answers "why do my claims keep
denying, and what should we fix upstream?" The host's batch insights panel is
specced and ready to build, but it is blocked on this package providing the
agent, its input contract, and a release tag.

## Solution

A new Sonnet-tier **BatchInsightsAgent** turns a frozen, aggregates-only view
of a batch (**Batch Aggregates**) into a short three-section markdown
narrative (**Batch Insights**): what's driving denials, payer patterns, and
what to fix upstream. No free text enters the prompt, so the PHI-redaction
boundary is untouched by construction. Hosts build the agent with the same
injection kwargs as every existing agent, and render the narrative through
their vetted markdown renderer.

## User Stories

1. As an RCM manager, I want a plain-English narrative of why my batch's claims denied, so that I understand root causes without reading every claim.
2. As an RCM manager, I want the narrative to surface payer patterns (concentration, outliers), so that I know which payers to escalate or renegotiate.
3. As an RCM manager, I want concrete upstream prevention recommendations, so that I can fix intake/coding process gaps and reduce future denials.
4. As an RCM manager, I want deadline pressure (overdue and due-soon counts) reflected in the narrative, so that time-critical appeals get triaged first.
5. As an RCM manager, I want every number in the narrative traceable to my batch's actual aggregates, so that I can trust the figures it cites.
6. As an RCM manager, I want CARC codes explained with their descriptions, so that I don't have to look up remittance codes by hand.
7. As an RCM manager, I want the same three-section structure on every analysis, so that repeated analyses of a batch are comparable.
8. As an RCM manager, I want the narrative concise (roughly 350 words), so that it reads as a panel, not a report.
9. As an RCM manager, I want a failed analysis to show as failed with a retry path, so that I never mistake an error for a delivered insight.
10. As a compliance officer, I want no patient free text sent to the LLM for insights, so that the no-BAA redaction stance holds by construction rather than by recall.
11. As a compliance officer, I want insights invocations tracked and audited like every other agent call, so that the audit trail stays complete.
12. As an Overturn host developer, I want a frozen pydantic input contract, so that my worker computes aggregates against a stable, validated shape.
13. As an Overturn host developer, I want construction-time validation to reject degenerate aggregates (negative counts, empty batch) before any API spend, so that bad host data fails fast and cheap.
14. As an Overturn host developer, I want constructor parity with existing agents (client, audit sink, invocation tracker kwargs), so that the worker wires insights identically to appeals.
15. As an Overturn host developer, I want the agent's model exposed the standard way, so that I can persist which model produced each analysis.
16. As an Overturn host developer, I want a package-shipped canned dry-run narrative, so that my dry-run client and demo seed render a realistic populated panel with zero network.
17. As an Overturn host developer, I want the narrative restricted to my renderer's markdown subset, so that nothing silently degrades to plain text in the panel.
18. As a public-demo visitor, I want the demo batch's insights panel populated with a clearly-labeled placeholder, so that I can see the feature without anyone spending API money.
19. As a package maintainer, I want the new contract purely additive (Batch Summary untouched), so that existing consumers upgrade the pin without changes.
20. As a package maintainer, I want the Sonnet tier locked by the tiering tests with its rationale recorded, so that nobody "optimizes" it to Haiku without seeing why it isn't.
21. As a package maintainer, I want the dry-run narrative and the output format defined in the same repo and tag, so that the placeholder can never drift from the real format.
22. As a QA engineer, I want a grounding eval over synthetic aggregate fixtures with a committed baseline, so that fabricated numbers or entities are measurable regressions.
23. As a QA engineer, I want all agent behavior testable offline through injected stubs, so that keyless CI covers the feature end to end.

## Implementation Decisions

- New **BatchInsightsAgent** in the agents module, following the established
  agent base pattern: hardcoded Sonnet-tier class attribute, agent name
  `batch_insights`, versioned markdown system-prompt file, keyword-only
  injection kwargs passed through to the base.
- Public API: `generate_insights(aggregates) -> str`, returning the markdown
  narrative. "Insights" is the package term; "analysis" is host persistence
  vocabulary (glossary). No output wrapper model — the host maps the string
  itself; contract evolution is additive if metadata is ever needed.
- New insights contracts module holding frozen pydantic v2 models,
  flat-re-exported like all contracts. Shape agreed in design review:

  ```python
  class PayerAggregate(BaseModel):   # frozen
      payer: str
      records: int                   # ge=0
      billed_amount: float           # ge=0

  class CarcAggregate(BaseModel):    # frozen; bare code — agent enriches
      carc_code: str
      records: int
      billed_amount: float

  class DeadlineBuckets(BaseModel):  # frozen; fixed buckets per host spec
      overdue: int
      due_within_7_days: int
      due_7_to_30_days: int
      due_beyond_30_days: int
      unknown: int

  class BatchTotals(BaseModel):      # frozen
      records: int                   # ge=1 — empty batch rejected
      billed_amount: float
      drafted: int
      failed: int
      submitted: int
      dismissed: int

  class BatchAggregates(BaseModel):  # frozen
      totals: BatchTotals
      by_payer: list[PayerAggregate]
      by_carc: list[CarcAggregate]
      deadlines: DeadlineBuckets
      dismissals_by_reason: dict[str, int]  # host's closed enum as keys
      service_date_start: date | None       # pair: both set & ordered,
      service_date_end: date | None         # or both None
  ```

- Validation is light guardrails only: `ge=0` on every count/amount,
  `totals.records ge=1`, the service-date pair validator. Deliberately **no**
  cross-dimension sum invariants — the host owns aggregation semantics, and
  dollar rounding drifts by cents.
- Fields are snake_case; the host converts to camelCase on its side of the seam.
- CARC descriptions are **agent-enriched** from the package's curated denial
  code database at prompt-build time; unknown codes fall back to the bare
  code. The contract carries bare codes so hosts stay thin and insight quality
  never depends on a host remembering to enrich.
- Dismissal-reason counts are an enum-keyed dict (host's closed set:
  `payer_correct | too_small | deadline_passed | other`), so a new host reason
  never forces a package tag.
- Model tier: Sonnet, hardcoded, per host spec and package convention. The
  tiering test gains the case plus a rationale note: this is inference over
  aggregates (root causes, recommendations), not Haiku-tier narration of
  tool-computed results.
- Prompt: static system prompt in the versioned prompt file; all dynamic
  content in a deterministically-built user message (golden-testable).
- Output contract enforced by the prompt: exactly three sections — what's
  driving denials / payer patterns / what to fix upstream — ~350-word cap,
  markdown restricted to the host renderer's subset (headings, bold, flat
  bullet/numbered lists, paragraphs; no tables, links, italics, or code).
- Token ceiling stays at the package-wide 1024 (≈2× headroom over the word
  cap). A truncation guard reads the stop reason defensively (canned clients
  without the attribute pass) and raises when output was cut off.
- Failure semantics: SDK/network errors propagate untouched; `ValueError` on
  empty or truncated output. A degenerate narrative is never returned as
  success — the host maps exceptions to its failed state, error message,
  and failure audit event.
- Dry-run: the package exports **`DRY_RUN_NARRATIVE`** — a realistic,
  format-true sample opening with a dry-run placeholder label. The host's
  dry-run client (host-owned code) serves it; the demo seed renders it;
  package tests reuse it as the stub response. Format and placeholder ship
  in the same tag and cannot drift apart.
- Observability per convention: the invocation tracker wraps
  `generate_insights`; `tool_called` before the model call,
  `insights_generated` (with length) after. No `phi_redacted` event — nothing
  crosses the redaction boundary, by construction (ADR 0001).
- Release: version bump to 0.5.0 and tag; hosts bump their pin.

## Testing Decisions

A good test exercises external behavior through a public seam — feed
aggregates, assert on the returned narrative, the raised error, or the
emitted events — never private helpers. Prompt content is asserted only via
committed goldens.

- **Primary seam — `generate_insights` with an injected stub client** (prior
  art: the eval judge's fake client, the offline example stub). Covers golden
  user-prompt construction (including CARC enrichment and unknown-code
  fallback), narrative pass-through, empty-response `ValueError`, truncation
  `ValueError`, and audit/invocation event emission. Hermetic; keyless CI safe.
- **Contract seam — aggregates construction**: guardrail rejections, frozen
  immutability, unknown dismissal-reason keys accepted.
- **Tiering seam**: the existing locked-tier test gains the Sonnet case.
- **Dry-run narrative compliance**: deterministic assertions that the
  exported constant carries the dry-run label, exactly the three sections,
  and only renderer-safe markdown.
- **Eval vertical** (prior art: the translate eval): synthetic aggregate
  fixtures; deterministic grounding checks (sections present; every named
  payer, CARC, and number traceable to the fixture) plus a Sonnet judge for
  faithfulness; offline harness unit tests in the normal pytest suite; the
  live run stays gated behind the live-eval flag; baseline report committed.

## Out of Scope

- Any free-text input to insights — denial reason text, letters, dismissal
  notes (ADR 0001; would re-open the redaction question).
- All host-side Stage 2 work: endpoint, worker job, migration, panel states,
  dry-run client wiring, demo seed (the host spec owns these).
- Per-org or per-host model choice; a constructor model override.
- Outcome-aware insights, win-likelihood scoring, trend-over-time analysis.
- Any change to Batch Summary, Batch Result, or the appeal batch pipeline.
- A CLI analyze command; streaming output.

## Further Notes

- Glossary (CONTEXT.md): **Batch Aggregates** (host-fed workflow view) vs
  **Batch Summary** (package execution rollup) vs **Batch Insights** (the
  narrative); "analysis" is reserved for host persistence vocabulary.
- ADR 0001 records the aggregates-only input boundary and its consequences.
- Handoff correction, for the record: the dry-run client lives in the *host*,
  not this package; the package's obligations are the exported narrative
  constant and tolerance of canned responses.
- Host regression flag: bumping the pin from v0.3.0 to v0.5.0 silently
  absorbs v0.4.0 (redaction-recall — ALL-CAPS names, phone/SSN variants;
  numeric-only member IDs now log as `[SSN]`). The host session should
  regression-check audit expectations when bumping.
