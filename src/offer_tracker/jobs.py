"""Run one long task at a time in the background so the dashboard stays responsive."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

log = logging.getLogger(__name__)


class JobBusy(RuntimeError):
    pass


@dataclass
class JobState:
    name: str | None = None
    status: str = "idle"  # idle | running | succeeded | failed
    message: str = ""
    started_at: str | None = None
    finished_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# A job receives a `progress` callback and returns its final message.
JobFn = Callable[[Callable[[str], None]], str]


class JobRunner:
    def __init__(self, describe_error: Callable[[BaseException], str] | None = None) -> None:
        self._describe_error = describe_error or (lambda exc: f"{type(exc).__name__}: {exc}")
        self._lock = threading.Lock()
        self._state = JobState()
        self._thread: threading.Thread | None = None

    @property
    def state(self) -> JobState:
        with self._lock:
            return JobState(**self._state.to_dict())

    def start(self, name: str, fn: JobFn) -> JobState:
        with self._lock:
            if self._state.status == "running":
                raise JobBusy(f"'{self._state.name}' is still running")
            self._state = JobState(
                name=name,
                status="running",
                message="Starting…",
                started_at=datetime.now(UTC).isoformat(),
            )
            self._thread = threading.Thread(target=self._run, args=(fn,), daemon=True)
            self._thread.start()
            return JobState(**self._state.to_dict())

    def wait(self, timeout: float | None = None) -> None:
        """Block until the current job finishes. Used by tests."""
        if self._thread:
            self._thread.join(timeout)

    def _progress(self, message: str) -> None:
        with self._lock:
            self._state.message = message

    def _run(self, fn: JobFn) -> None:
        try:
            message = fn(self._progress)
            status = "succeeded"
        except Exception as exc:
            log.exception("Job failed")
            message, status = self._describe_error(exc), "failed"
        with self._lock:
            self._state.status = status
            self._state.message = message
            self._state.finished_at = datetime.now(UTC).isoformat()
