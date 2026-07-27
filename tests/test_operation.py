"""Behavioral tests for the private shared operation contract."""

import threading
from importlib.util import find_spec

import pytest

from csvql.operation import (
    OperationCancelled,
    OperationContext,
    OperationState,
    OperationToken,
)


def test_private_operation_contract_has_its_own_module() -> None:
    """Cancellation is owned outside the atomic-write compatibility facade."""

    assert find_spec("csvql.operation") is not None


def test_token_cancellation_is_safe_under_concurrent_requests() -> None:
    """Concurrent cancellers leave the shared token permanently cancelled."""

    token = OperationToken()
    start = threading.Barrier(5)
    workers = [threading.Thread(target=lambda: (start.wait(), token.cancel())) for _ in range(4)]
    for worker in workers:
        worker.start()
    start.wait()
    for worker in workers:
        worker.join()

    assert token.is_cancelled
    with pytest.raises(OperationCancelled, match="Operation cancelled"):
        token.raise_if_cancelled()


def test_request_cancel_interrupts_once_and_checkpoints() -> None:
    """Cancellation marks first, invokes one interrupt, then stops later work."""

    calls: list[str] = []
    context = OperationContext(OperationToken())
    context.attach_interrupt(lambda: calls.append("interrupt"))

    context.request_cancel()
    context.request_cancel()

    assert context.token.is_cancelled
    assert calls == ["interrupt"]
    with pytest.raises(OperationCancelled):
        context.checkpoint()


def test_detached_interrupt_is_not_requested() -> None:
    """Detaching an engine interrupt leaves cancellation and checkpoints intact."""

    calls: list[str] = []
    context = OperationContext(OperationToken())
    context.attach_interrupt(lambda: calls.append("interrupt"))
    context.detach_interrupt()

    context.request_cancel()

    assert context.token.is_cancelled
    assert calls == []
    with pytest.raises(OperationCancelled):
        context.checkpoint()


def test_raising_interrupt_does_not_block_cancellation_or_checkpoint() -> None:
    """Best-effort interruption cannot erase cancellation after an engine failure."""

    context = OperationContext(OperationToken())

    def fail_interrupt() -> None:
        raise RuntimeError("interrupt unavailable")

    context.attach_interrupt(fail_interrupt)

    context.request_cancel()

    assert context.token.is_cancelled
    with pytest.raises(OperationCancelled):
        context.checkpoint()


def test_detach_waits_for_an_in_flight_interrupt_callback() -> None:
    """An owner cannot finish detaching while its interrupt callback is still running."""

    callback_started = threading.Event()
    callback_finished = threading.Event()
    release_callback = threading.Event()
    detach_attempted = threading.Event()
    detach_returned = threading.Event()
    context = OperationContext(OperationToken())

    def interrupt() -> None:
        callback_started.set()
        release_callback.wait()
        callback_finished.set()

    def request_cancel() -> None:
        context.request_cancel()

    def detach_interrupt() -> None:
        context.detach_interrupt()
        detach_returned.set()

    context.attach_interrupt(interrupt)
    requester = threading.Thread(target=request_cancel)
    requester.start()
    assert callback_started.wait(timeout=1)

    original_lock = context._lock

    class LifecycleLock:
        def __enter__(self) -> "LifecycleLock":
            detach_attempted.set()
            original_lock.acquire()
            return self

        def __exit__(self, *_: object) -> None:
            original_lock.release()

    context._lock = LifecycleLock()  # type: ignore[assignment]
    detacher = threading.Thread(target=detach_interrupt)
    detacher.start()
    assert detach_attempted.wait(timeout=1)

    try:
        assert not detach_returned.wait(timeout=0.2)
    finally:
        release_callback.set()
        requester.join(timeout=1)
        detacher.join(timeout=1)

    assert callback_finished.is_set()
    assert detach_returned.is_set()


def test_concurrent_cancel_requests_invoke_one_callback_and_preserve_cancellation() -> None:
    """Concurrent requests keep cancellation permanent while selecting one interrupt."""

    calls = 0
    calls_lock = threading.Lock()
    context = OperationContext(OperationToken())

    def interrupt() -> None:
        nonlocal calls
        with calls_lock:
            calls += 1

    context.attach_interrupt(interrupt)
    start = threading.Barrier(5)
    workers = [
        threading.Thread(target=lambda: (start.wait(), context.request_cancel())) for _ in range(4)
    ]
    for worker in workers:
        worker.start()
    start.wait()
    for worker in workers:
        worker.join(timeout=1)

    assert calls == 1
    assert context.token.is_cancelled
    with pytest.raises(OperationCancelled):
        context.checkpoint()


def test_execution_state_reaches_a_terminal_barrier_after_cancellation() -> None:
    """Cleanup must be able to distinguish a requested interrupt from terminal execution."""

    context = OperationContext(OperationToken())
    context.begin_execution()

    context.request_cancel()
    assert context.state is OperationState.CANCELLING
    assert not context.await_terminal(timeout=0)

    context.mark_terminal()

    assert context.state is OperationState.TERMINAL
    assert context.await_terminal(timeout=0)


def test_serial_execution_can_reenter_after_a_normal_terminal_state() -> None:
    """A clean engine session may reuse bindings across serial queries."""

    context = OperationContext(OperationToken())
    context.begin_execution()
    context.mark_terminal()

    context.begin_execution()

    assert context.state is OperationState.EXECUTING
    assert not context.await_terminal(timeout=0)
