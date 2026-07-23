"""Private cancellation primitives shared by long-running operations."""

from __future__ import annotations

import threading
from _thread import RLock
from collections.abc import Callable
from dataclasses import dataclass, field


class OperationCancelled(Exception):
    """Raised when a cancellable operation reaches a cancellation checkpoint."""


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

    def request_cancel(self) -> None:
        """Mark cancellation, then make one best-effort interrupt request."""

        self.token.cancel()
        with self._lock:
            if self._interrupt_requested or self._interrupt is None:
                return
            callback = self._interrupt
            self._interrupt_requested = True
            try:
                callback()
            except Exception:
                # An interrupt is advisory; cancellation and caller cleanup still proceed.
                pass
