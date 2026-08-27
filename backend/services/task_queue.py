"""
Serial generation queue — ensures only one TTS inference runs at a time
to avoid GPU contention.
"""

import asyncio
import traceback
from dataclasses import dataclass
from typing import Coroutine, Literal

# Keep references to fire-and-forget background tasks to prevent GC
_background_tasks: set = set()


@dataclass
class GenerationJob:
    """Queued generation work plus the generation ID it belongs to."""

    generation_id: str
    coro: Coroutine


# Generation queue — serializes TTS inference to avoid GPU contention
_generation_queue: asyncio.Queue = None  # type: ignore  # initialized at startup
_generation_worker_task: asyncio.Task | None = None
_queued_generation_ids: set[str] = set()
# FIFO order of queued generations (a set has no order; the snapshot needs one)
_queued_generation_order: list[str] = []
_running_generation_tasks: dict[str, asyncio.Task] = {}
_cancelled_generation_ids: set[str] = set()
# Set while shutting down so the worker can tell "my own cancellation" apart
# from "one of my job tasks was cancelled" (cancel_generation). The worker must
# swallow the latter but never the former — otherwise a shutdown cancel that
# lands mid-job is consumed and the worker keeps running forever.
_shutdown_requested = False


def create_background_task(coro) -> asyncio.Task:
    """Create a background task and prevent it from being garbage collected."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def _generation_worker():
    """Worker that processes generation tasks one at a time."""
    while True:
        job = await _generation_queue.get()
        try:
            if job.generation_id in _cancelled_generation_ids:
                _cancelled_generation_ids.discard(job.generation_id)
                _discard_queued_order(job.generation_id)
                job.coro.close()
                continue

            task = asyncio.create_task(job.coro)
            _running_generation_tasks[job.generation_id] = task
            _queued_generation_ids.discard(job.generation_id)
            _discard_queued_order(job.generation_id)
            try:
                await task
            except asyncio.CancelledError:
                # A cancelled *job* (cancel_generation) ends this job but not
                # the worker. A shutdown cancellation is signalled through
                # _shutdown_requested and must always propagate — swallowing it
                # here would leave the worker running forever.
                if _shutdown_requested:
                    raise
                if not task.cancelled():
                    raise
        except Exception:
            traceback.print_exc()
            await _force_fail_if_active(
                job.generation_id,
                "Worker exited without writing terminal status",
            )
        finally:
            _running_generation_tasks.pop(job.generation_id, None)
            _queued_generation_ids.discard(job.generation_id)
            _discard_queued_order(job.generation_id)
            _generation_queue.task_done()


def _discard_queued_order(generation_id: str) -> None:
    """Remove *generation_id* from the FIFO order list (in place, no-op if absent)."""
    try:
        _queued_generation_order.remove(generation_id)
    except ValueError:
        pass


async def _force_fail_if_active(generation_id: str, error: str) -> None:
    """Best-effort recovery — flip an active row to failed if the worker
    bailed before writing a terminal status. Catches the case where the gen
    coroutine's own status-write raised (e.g. SQLite lock contention)."""
    try:
        from ..database import Generation as DBGeneration, get_db
        from . import history

        db = next(get_db())
        try:
            gen = db.query(DBGeneration).filter_by(id=generation_id).first()
            if gen is None:
                return
            if (gen.status or "completed") not in ("loading_model", "generating"):
                return
            await history.update_generation_status(
                generation_id=generation_id,
                status="failed",
                db=db,
                error=error,
            )
        finally:
            db.close()
    except Exception:
        traceback.print_exc()


def enqueue_generation(generation_id: str, coro):
    """Add a generation coroutine to the serial queue."""
    if _generation_queue is None:
        raise RuntimeError("Generation queue has not been initialized")

    _queued_generation_ids.add(generation_id)
    _queued_generation_order.append(generation_id)
    _generation_queue.put_nowait(GenerationJob(generation_id=generation_id, coro=coro))


def cancel_generation(generation_id: str) -> Literal["queued", "running"] | None:
    """Cancel a queued or running generation if it is still active."""
    running_task = _running_generation_tasks.get(generation_id)
    if running_task is not None:
        running_task.cancel()
        return "running"

    if generation_id in _queued_generation_ids:
        _queued_generation_ids.discard(generation_id)
        _discard_queued_order(generation_id)
        _cancelled_generation_ids.add(generation_id)
        return "queued"

    return None


def get_queue_snapshot() -> list[dict]:
    """Return an ordered snapshot of the generation queue (spec §6.2.1).

    Running task first, then queued jobs in FIFO order. Each entry is
    ``{"generation_id": str, "state": "queued" | "running"}``. Live progress
    lives in the TaskManager, keyed by the same generation id.
    """
    entries: list[dict] = [
        {"generation_id": gen_id, "state": "running"}
        for gen_id in list(_running_generation_tasks.keys())
    ]
    for gen_id in _queued_generation_order:
        if gen_id in _queued_generation_ids:
            entries.append({"generation_id": gen_id, "state": "queued"})
    return entries


def init_queue(force: bool = False):
    """Initialize the generation queue and start the worker.

    Must be called once during application startup (inside a running event loop).
    """
    global _generation_queue, _generation_worker_task
    global _queued_generation_ids, _running_generation_tasks, _cancelled_generation_ids
    global _queued_generation_order, _shutdown_requested

    if _generation_worker_task is not None and not _generation_worker_task.done():
        if not force:
            return
        shutdown_queue()

    _generation_queue = asyncio.Queue()
    _queued_generation_ids = set()
    _queued_generation_order = []
    _running_generation_tasks = {}
    _cancelled_generation_ids = set()
    _shutdown_requested = False
    _generation_worker_task = create_background_task(_generation_worker())


def shutdown_queue() -> None:
    """Stop the worker and cancel any running generations.

    Used by tests and application shutdown. Safe to call multiple times.
    """
    global _generation_worker_task, _shutdown_requested
    _shutdown_requested = True
    worker = _generation_worker_task
    _generation_worker_task = None
    if worker is not None and not worker.done():
        try:
            worker.cancel()
        except RuntimeError:
            # The worker belongs to an already-closed event loop (test
            # teardown crossing function-scoped loops) — nothing to cancel.
            pass
    for task in list(_running_generation_tasks.values()):
        task.cancel()
    _running_generation_tasks.clear()
    _queued_generation_ids.clear()
    _queued_generation_order.clear()
    _cancelled_generation_ids.clear()
