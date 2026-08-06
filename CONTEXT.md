# healthflow-agents

Agent package for health-insurance denial management: LLM agents, their prompts,
and the frozen data contracts thin hosts (Overturn CLI/server) build against.

## Language

### Provider-side (RCM) batch

**Batch**:
A set of denied claims processed together. The package's unit of provider-side
work; hosts may call their persisted equivalent a "run".
_Avoid_: Run (host vocabulary)

**Batch Summary**:
The package-computed numeric rollup of one batch *execution* — how appeal
generation went (succeeded/failed counts, dollars by CARC). Produced by the
package itself.
_Avoid_: Aggregates

**Batch Aggregates**:
The host-computed, aggregates-only view of a batch's *workflow state* (lifecycle
counts, payer/CARC/deadline/dismissal dimensions), fed to the insights agent.
Contains no free text; the input side of the redaction-safe insights boundary.
_Avoid_: Summary, statistics, metrics

**Batch Insights**:
The LLM-written markdown narrative over Batch Aggregates — root causes, payer
patterns, prevention recommendations.
_Avoid_: Analysis (host persistence vocabulary: analysis_status, analysis_md)
