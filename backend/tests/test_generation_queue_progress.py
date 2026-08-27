"""Spec §6 — generation queue visibility + progress.

Covers: the FIFO queue snapshot (running first), the TaskManager progress
registry, and chunk-level progress callbacks from ``generate_chunked``.
"""

import asyncio

import numpy as np
import pytest

from backend.services import task_queue
from backend.utils.tasks import TaskManager


@pytest.fixture(autouse=True)
async def _queue_lifecycle():
    """Start a fresh queue per test and tear the worker down inside the event
    loop afterwards.

    The worker task runs forever; if it is still pending when pytest-asyncio
    closes the loop, ``Runner.close()``'s ``_cancel_all_tasks`` hangs. An async
    fixture lets us ``await`` the cancellation to settle before loop teardown.
    """
    task_queue.init_queue(force=True)
    yield
    task_queue.shutdown_queue()
    # Let the worker's cancellation propagate before the loop is torn down.
    await asyncio.sleep(0)


# -- task_queue snapshot -----------------------------------------------------


def _reset_queue():
    task_queue.init_queue(force=True)


@pytest.mark.asyncio
async def test_queue_snapshot_orders_queued_fifo():
    _reset_queue()
    task_queue.enqueue_generation("gen-a", asyncio.sleep(0))
    task_queue.enqueue_generation("gen-b", asyncio.sleep(0))
    task_queue.enqueue_generation("gen-c", asyncio.sleep(0))

    snap = task_queue.get_queue_snapshot()
    queued = [e for e in snap if e["state"] == "queued"]
    assert [e["generation_id"] for e in queued] == ["gen-a", "gen-b", "gen-c"]


@pytest.mark.asyncio
async def test_queue_snapshot_running_before_queued():
    _reset_queue()

    running_started = asyncio.Event()
    release_running = asyncio.Event()

    async def running_job():
        running_started.set()
        await release_running.wait()

    task_queue.enqueue_generation("gen-running", running_job())
    await asyncio.wait_for(running_started.wait(), timeout=1)
    task_queue.enqueue_generation("gen-queued", asyncio.sleep(0))

    snap = task_queue.get_queue_snapshot()
    assert [e["state"] for e in snap] == ["running", "queued"]
    assert snap[0]["generation_id"] == "gen-running"

    release_running.set()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_cancel_queued_removes_from_snapshot():
    _reset_queue()
    task_queue.enqueue_generation("gen-x", asyncio.sleep(0))
    assert task_queue.cancel_generation("gen-x") == "queued"
    snap = task_queue.get_queue_snapshot()
    assert all(e["generation_id"] != "gen-x" for e in snap)


# -- TaskManager progress registry ------------------------------------------


def test_task_manager_progress_lifecycle():
    tm = TaskManager()
    tm.start_generation("gen-1", "profile-1", "Hello world, this is a long text")

    assert tm.get_active_generation("gen-1") is not None

    tm.update_generation_progress(
        "gen-1",
        state="generating",
        progress=0.5,
        chunk_index=2,
        chunk_count=4,
        message="Synthesizing chunk 2/4",
    )
    progress = tm.get_generation_progress("gen-1")
    assert progress["state"] == "generating"
    assert progress["progress"] == 0.5
    assert progress["chunk_index"] == 2
    assert progress["chunk_count"] == 4
    assert progress["message"] == "Synthesizing chunk 2/4"

    tm.complete_generation("gen-1")
    assert tm.get_generation_progress("gen-1") is None


def test_task_manager_update_unknown_generation_is_noop():
    tm = TaskManager()
    tm.update_generation_progress("missing", state="generating", progress=1.0)
    assert tm.get_generation_progress("missing") is None


# -- chunk-level progress callback ------------------------------------------


class _SilentBackend:
    """Minimal TTSBackend that returns silence — enough for chunked_tts."""

    async def generate(self, text, voice_prompt, language="en", seed=None, instruct=None):
        return np.zeros(16000, dtype=np.float32), 16000


@pytest.mark.asyncio
async def test_generate_chunked_single_shot_reports_one_chunk():
    from backend.utils.chunked_tts import generate_chunked

    calls: list[tuple] = []

    def cb(index, total, message):
        calls.append((index, total, message))

    audio, sr = await generate_chunked(
        _SilentBackend(),
        "Kurzer Text.",
        {},
        max_chunk_chars=800,
        progress_callback=cb,
    )
    assert sr == 16000
    assert len(audio) > 0
    assert calls == [(1, 1, "Synthesizing")]


@pytest.mark.asyncio
async def test_generate_chunked_long_text_advances_progress():
    from backend.utils.chunked_tts import generate_chunked

    # ~20 sentences — forces multiple chunks at max_chunk_chars=60.
    text = " ".join(
        f"Dies ist der Satz Nummer {i} mit ausreichend Worten fuer einen Chunk." for i in range(20)
    )
    calls: list[tuple] = []

    def cb(index, total, message):
        calls.append((index, total, message))

    audio, sr = await generate_chunked(
        _SilentBackend(),
        text,
        {},
        max_chunk_chars=60,
        progress_callback=cb,
    )
    assert sr == 16000
    assert len(calls) >= 2
    total = calls[0][1]
    assert total == len(calls)
    assert calls[-1][0] == total
    # Progress strictly advances chunk by chunk.
    indexes = [c[0] for c in calls]
    assert indexes == list(range(1, total + 1))
