"""Shared test doubles for agent tests."""
from contextlib import contextmanager
from typing import Iterator
from unittest.mock import MagicMock


def make_mock_client(response_text: str = "Recommendation") -> MagicMock:
    """Mock Anthropic client whose messages.create returns `response_text`."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=response_text)]
    mock_client.messages.create.return_value = mock_response
    return mock_client


class RecordingAuditSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def log(self, event_type: str, details: dict) -> None:
        self.events.append((event_type, details))

    def event_types(self) -> list[str]:
        return [event_type for event_type, _ in self.events]


class RecordingInvocationTracker:
    def __init__(self) -> None:
        self.records: list[MagicMock] = []
        self.calls: list[dict] = []

    @contextmanager
    def __call__(
        self, *, agent: str, event_type: str, model: str | None = None
    ) -> Iterator[MagicMock]:
        self.calls.append({"agent": agent, "event_type": event_type, "model": model})
        record = MagicMock()
        record.details = {}
        self.records.append(record)
        yield record
