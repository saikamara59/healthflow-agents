# healthflow-agents — project instructions

Agent package consumed by thin hosts (Overturn CLI/server) via a pinned git tag —
`overturn/pyproject.toml` pins `healthflow-agents @ ...@vX.Y.Z`. All agent logic,
prompts, and contracts live HERE; hosts add none. Ship changes as a new tag; hosts
bump their pin.

## Conventions

- Agents subclass `core.base.AgentBase` with `model` / `agent_name` / `prompt_file`
  class attrs; system prompts are markdown files in `healthflow_agents/prompts/`.
- Contracts are frozen pydantic models in `healthflow_agents/contracts/`.
- The redaction boundary (`redaction/`) is inviolable: raw PHI text never reaches a
  prompt input that isn't redacted at construction. Aggregate-only contracts must
  stay free-text-free.
- `DryRunClient` must answer every agent's call shape with canned output — the
  dry-run contract is full pipeline, zero network.
- Tests: pytest, CI matrix py3.10–3.13 + offline demo smoke.

## Agent skills

Global defaults apply (issue tracker: Linear; default triage labels; single-context
domain docs — see `~/.claude/CLAUDE.md`). Repo specifics:

- **Linear team: Overturn (`OVE`)** — package work shares the host's team. Batch
  Insights work belongs to the existing project **"Denial Intelligence"**.
- Work streams follow the same `branch:<git-branch>` label discipline as the
  Overturn repo.
