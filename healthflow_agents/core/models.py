"""Claude model tier constants.

Agent models are tiered by task complexity to control token cost. Each agent
declares the tier its work actually needs via its `model` class attribute:
- OPUS: high-stakes regulatory/legal reasoning over denials (appeals).
- SONNET: nuanced extraction from unstructured policy text (translation).
- HAIKU: narrating data already computed deterministically by tools
  (comparison, cost, network) — the LLM only summarizes structured input.
"""

CLAUDE_MODEL_OPUS = "claude-opus-4-8"
CLAUDE_MODEL_SONNET = "claude-sonnet-4-6"
CLAUDE_MODEL_HAIKU = "claude-haiku-4-5"

# Backwards-compatible default (Sonnet). New code should import the tier it
# needs rather than relying on this alias.
CLAUDE_MODEL = CLAUDE_MODEL_SONNET

# Smaller/faster model used by classifier-style agents (e.g. HealthFlow's
# Temporal Awareness) where the LLM job is structured-output extraction, not
# free-form generation.
CLAUDE_CLASSIFIER_MODEL = "claude-haiku-4-5-20251001"
