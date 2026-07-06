# healthflow-agents

Claude agents for both sides of a health-insurance claim, as a standalone,
installable Python package. Patient-side: plan comparison, cost calculation,
network verification, coverage translation, and denial appeals (these power
[HealthFlow](https://github.com/saikamara59/healthflow)). Provider-side:
batch denial management for revenue-cycle teams — remittance ingestion,
bulk appeal generation, and a deadline/dollar-prioritized worklist.

## Install

```
pip install git+https://github.com/saikamara59/healthflow-agents.git
```

## Usage

Agents run standalone with zero host dependencies — logging defaults to
stdout JSON lines:

```python
from healthflow_agents import ComparisonAgent

agent = ComparisonAgent()  # needs ANTHROPIC_API_KEY in the environment
recommendation = agent.recommend(plans=plans, age=65, income_level="low")
```

Host applications inject their real audit and invocation-tracking
implementations — anything satisfying the `AuditSink` and
`InvocationTracker` Protocols in `healthflow_agents.core.logging`:

```python
agent = ComparisonAgent(
    audit_sink=my_audit_logger,          # .log(event_type, details)
    invocation_tracker=my_invocation,    # with tracker(agent=..., event_type=..., model=...) as inv:
)
```

Each agent is pinned to a Claude model tier matched to its task complexity
(and cost): Opus for high-stakes regulatory reasoning (appeals), Sonnet for
nuanced extraction from policy text (translation), Haiku for agents that
only narrate tool-computed structured data (comparison, cost, network). The
tier contract is locked by tests.

## Threat model

This package assumes **no BAA with Anthropic**, so prompts sent to Claude
must not carry HIPAA identifiers. Free-text fields (denial letters, document
content, user questions) are redacted at construction time by `PHIRedactor`
inside frozen `PromptInput` Pydantic models — the only code path to a prompt
body — replacing patient names, SSNs, DOBs, member IDs, phone numbers, and
emails with typed placeholders. De-identified medical content (medication and
procedure names, and provider names/NPIs, which are public NPPES registry
data) passes through by design. See the full design in
[docs/2026-05-14-phi-redaction-design.md](docs/2026-05-14-phi-redaction-design.md).

Redaction is audited: every redacting agent emits a `phi_redacted` audit
event whose payload is `{"count": <n>, "types": ["[DOB]", ...]}` — counts and
placeholder types only, never the raw or redacted text.

## Provider-side (RCM) batch denial management

The same AppealAgent also serves the provider side: ingest denied claims
from a remittance (simplified CSV/JSON for now — X12 835 is a stubbed
production path), run appeals in bulk with per-record error isolation, and
rank the results into a worklist by appeal-deadline proximity and dollars
at stake. Free text from remittances crosses the same PHI redaction
boundary as patient-side denial letters.

```python
from datetime import date

from healthflow_agents import AppealAgent
from healthflow_agents.batch import BatchRunner, prioritize_worklist
from healthflow_agents.tools.remittance_parser import load_remittance

agent = AppealAgent(audit_sink=..., invocation_tracker=...)
result = BatchRunner(agent).run(load_remittance("remit.csv"))
worklist = prioritize_worklist(result, today=date.today())
```

See it end to end (offline, synthetic data, no API key needed):

```
python -m examples.provider_demo
```

## Layout

```
healthflow_agents/
  core/        # AgentBase, client factory, logging Protocols, safety harness, model tiers
  redaction/   # PHIRedactor + frozen PromptInput models (the LLM redaction boundary)
  contracts/   # Pydantic schemas the agents consume (incl. DenialRecord/BatchResult)
  tools/       # deterministic tools the agents orchestrate
  agents/      # the five agents
  batch/       # provider-side batch runner + worklist prioritization
  prompts/     # versioned system prompts (.md), loaded byte-identical at init
evals/         # eval harnesses (translate accuracy benchmark; not shipped in the wheel)
examples/      # provider_demo.py — offline, synthetic-data portfolio demo
tests/         # 240+ tests: golden prompt byte-identity, redaction invariants, batch isolation
```

## Development

```
pip install -e ".[dev]"
pytest
```

The suite includes golden tests generated from the original HealthFlow
implementation (prompts must stay byte-identical), redaction-boundary
invariants (frozen models, raw text never stored, bypass construction
rejected), the model-tier contract, and an AST check that no agent can
reach a prompt body without a `PromptInput`. All data in tests and demos
is synthetic.
