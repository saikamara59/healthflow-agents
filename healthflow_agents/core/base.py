"""AgentBase — shared construction for the five HealthFlow agents.

Each agent subclass declares three class attributes:

- `model`: the Claude model tier this agent's work needs (see core.models)
- `agent_name`: the name recorded on invocation-tracker entries
- `prompt_file`: the system-prompt file under healthflow_agents/prompts/

The base owns Anthropic client creation (retry with backoff + timeout via
the SDK), loads the system prompt at init, and wires the injected logging
interfaces. With no arguments, agents run standalone using stdout defaults.
"""
import importlib.resources

import anthropic

from healthflow_agents.core.client import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    create_client,
)
from healthflow_agents.core.logging import (
    AuditSink,
    InvocationTracker,
    StdoutAuditSink,
    StdoutInvocationTracker,
)


def load_system_prompt(filename: str) -> str:
    """Load a versioned system prompt from healthflow_agents/prompts/.

    Only trailing newlines are stripped, so the loaded string is
    byte-identical to the original inline SYSTEM_PROMPT constant.
    """
    resource = importlib.resources.files("healthflow_agents.prompts").joinpath(filename)
    return resource.read_text(encoding="utf-8").rstrip("\n")


class AgentBase:
    model: str
    agent_name: str
    prompt_file: str

    def __init__(
        self,
        *,
        audit_sink: AuditSink | None = None,
        invocation_tracker: InvocationTracker | None = None,
        client: anthropic.Anthropic | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        for attr in ("model", "agent_name", "prompt_file"):
            if not hasattr(type(self), attr):
                raise TypeError(
                    f"{type(self).__name__} must define the `{attr}` class attribute"
                )
        self.audit: AuditSink = audit_sink if audit_sink is not None else StdoutAuditSink()
        self.invocations: InvocationTracker = (
            invocation_tracker
            if invocation_tracker is not None
            else StdoutInvocationTracker()
        )
        self.client: anthropic.Anthropic = (
            client
            if client is not None
            else create_client(max_retries=max_retries, timeout=timeout)
        )
        self.system_prompt: str = load_system_prompt(self.prompt_file)
