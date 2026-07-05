"""Injected logging interfaces.

Agents never construct their own loggers. They receive an `AuditSink` and an
`InvocationTracker` at construction time; both are structural Protocols so the
host application injects its real implementations without importing anything
from this package's default classes. HealthFlow's `AuditLogger` instance and
its `invocation` singleton satisfy these Protocols as-is.

Standalone use (no injection) falls back to the stdout implementations below,
so the package runs with zero host dependencies.
"""
import json
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, ContextManager, Iterator, Protocol, runtime_checkable


@runtime_checkable
class AuditSink(Protocol):
    """Where agents send audit events (e.g. "phi_redacted", "tool_called")."""

    def log(self, event_type: str, details: dict) -> None: ...


class InvocationRecord(Protocol):
    """The mutable record yielded by an InvocationTracker context manager.

    Agents set `details` inside the wrapped block; everything else belongs to
    the tracker implementation.
    """

    details: dict


class InvocationTracker(Protocol):
    """Context-manager factory wrapping one agent operation.

    Called as `with tracker(agent=..., event_type=..., model=...) as inv:`.
    The yielded record must expose a mutable `details` dict. Implementations
    are expected to record duration and errors on context exit; failures in
    the tracker itself must never break the wrapped operation.
    """

    def __call__(
        self,
        *,
        agent: str,
        event_type: str,
        model: str | None = None,
    ) -> ContextManager[InvocationRecord]: ...


class StdoutAuditSink:
    """Default AuditSink: one JSON line per event to stdout."""

    def log(self, event_type: str, details: dict) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "details": details,
        }
        print(json.dumps(entry, default=str))


@dataclass
class _StdoutInvocationRecord:
    agent: str
    event_type: str
    model_used: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: int | None = None


class StdoutInvocationTracker:
    """Default InvocationTracker: one JSON line per invocation to stdout.

    Mirrors the host-side contract: the record is written on exit whether the
    body succeeded or raised, and exceptions from the body propagate.
    """

    @contextmanager
    def __call__(
        self,
        *,
        agent: str,
        event_type: str,
        model: str | None = None,
    ) -> Iterator[_StdoutInvocationRecord]:
        record = _StdoutInvocationRecord(
            agent=agent, event_type=event_type, model_used=model
        )
        start = time.monotonic()
        try:
            yield record
        except BaseException as exc:
            record.error = f"{type(exc).__name__}: {exc}"[:512]
            raise
        finally:
            record.duration_ms = int((time.monotonic() - start) * 1000)
            print(
                json.dumps(
                    {"event_type": "agent_invocation", **asdict(record)},
                    default=str,
                )
            )
