"""Private cancellation primitives shared by long-running operations."""

from __future__ import annotations

import threading
from _thread import RLock
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum


class OperationCancelled(Exception):
    """Raised when a cancellable operation reaches a cancellation checkpoint."""


class OperationState(StrEnum):
    """Lifecycle state used to establish a synchronous execution barrier."""

    READY = "ready"
    EXECUTING = "executing"
    CANCELLING = "cancelling"
    TERMINAL = "terminal"


class OperationToken:
    """Thread-safe cancellation state shared by one local operation."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        """Mark the operation as cancelled."""

        self._cancelled.set()

    @property
    def is_cancelled(self) -> bool:
        """Return whether cancellation has been requested."""

        return self._cancelled.is_set()

    def raise_if_cancelled(self) -> None:
        """Raise when a cancellation checkpoint is reached."""

        if self.is_cancelled:
            raise OperationCancelled("Operation cancelled.")


@dataclass(slots=True)
class OperationContext:
    """Shared cancellation state and an engine-owned best-effort interrupt."""

    token: OperationToken
    _interrupt: Callable[[], None] | None = None
    # This is reentrant because an interrupt callback may detach its own owner.
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _interrupt_requested: bool = field(default=False, init=False, repr=False)
    _state: OperationState = field(
        default=OperationState.READY,
        init=False,
        repr=False,
    )
    _terminal: threading.Event = field(
        default_factory=threading.Event,
        init=False,
        repr=False,
    )

    @property
    def state(self) -> OperationState:
        """Return the current execution lifecycle state."""

        with self._lock:
            return self._state

    def attach_interrupt(self, callback: Callable[[], None]) -> None:
        """Register the interrupt callback while its owner is live."""

        with self._lock:
            self._interrupt = callback

    def detach_interrupt(self) -> None:
        """Discard the interrupt callback after its owner has closed."""

        with self._lock:
            self._interrupt = None

    def checkpoint(self) -> None:
        """Stop work when cancellation has been requested."""

        self.token.raise_if_cancelled()

    def begin_execution(self) -> None:
        """Acquire one serial execution phase and clear its terminal barrier."""

        self.token.raise_if_cancelled()
        with self._lock:
            if self._state in {
                OperationState.EXECUTING,
                OperationState.CANCELLING,
            }:
                raise RuntimeError("Operation execution is already active.")
            self._terminal.clear()
            self._state = OperationState.EXECUTING

    def mark_terminal(self) -> None:
        """Mark execution terminal and wake cleanup waiters."""

        with self._lock:
            self._state = OperationState.TERMINAL
            self._terminal.set()

    def await_terminal(self, *, timeout: float | None = None) -> bool:
        """Wait for the current execution phase to reach a terminal state."""

        return self._terminal.wait(timeout=timeout)

    def request_cancel(self) -> None:
        """Mark cancellation, then make one best-effort interrupt request."""

        self.token.cancel()
        with self._lock:
            if self._state is not OperationState.TERMINAL:
                self._state = OperationState.CANCELLING
            if self._interrupt_requested or self._interrupt is None:
                return
            callback = self._interrupt
            self._interrupt_requested = True
            try:
                callback()
            except Exception:
                # An interrupt is advisory; cancellation and caller cleanup still proceed.
                pass
