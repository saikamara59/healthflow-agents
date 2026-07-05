# healthflow-agents

HealthFlow's five insurance-navigation Claude agents as a standalone,
installable Python package: plan comparison, cost calculation, network
verification, coverage translation, and denial appeals.

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

## Layout

```
healthflow_agents/
  core/        # AgentBase, client factory, logging Protocols, safety harness, model tiers
  redaction/   # PHIRedactor + frozen PromptInput models (the LLM redaction boundary)
  contracts/   # Pydantic schemas the agents consume
  tools/       # deterministic tools the agents orchestrate
  agents/      # the five agents
  prompts/     # versioned system prompts (.md), loaded byte-identical at init
```
