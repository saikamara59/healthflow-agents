"""Anthropic client factory and response helpers."""
import anthropic

DEFAULT_MAX_RETRIES = 2
DEFAULT_TIMEOUT_SECONDS = 60.0


def create_client(
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> anthropic.Anthropic:
    """Build the Anthropic client used by all agents.

    Retry-with-backoff and the request timeout are delegated to the SDK:
    `max_retries` retries with exponential backoff on connection errors,
    408/429, and 5xx responses; `timeout` bounds each request in seconds.
    """
    return anthropic.Anthropic(max_retries=max_retries, timeout=timeout)


def extract_text(response) -> str:
    """Pull the first text block out of an Anthropic Messages response.

    Skips non-text content blocks (e.g. tool_use) and tolerates empty content.
    """
    for block in getattr(response, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            return text
    return ""


def strip_code_fence(text: str) -> str:
    """Strip a leading/trailing ```lang ... ``` fence if present.

    Claude sometimes wraps JSON output in a fence despite system-prompt
    instructions to the contrary. Callers that want to json.loads(...) the
    text should pass it through this first.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    # Drop the opening fence (and optional language tag) up to the first newline.
    first_newline = stripped.find("\n")
    if first_newline == -1:
        return stripped
    body = stripped[first_newline + 1 :]
    # Drop the closing fence.
    if body.rstrip().endswith("```"):
        body = body.rstrip()[: -len("```")]
    return body.strip()
