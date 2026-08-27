"""Spec §6 — GET /generate/queue route: joins the task-queue snapshot with the
generations table and the TaskManager progress registry."""

import asyncio
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import models as db_models  # noqa: F401  (register tables)
from backend.database.models import Base
from backend.services import task_queue
from backend.utils.tasks import get_task_manager


@pytest.fixture(autouse=True)
async def _queue_lifecycle():
    task_queue.init_queue(force=True)
    yield
    task_queue.shutdown_queue()
    await asyncio.sleep(0)
    get_task_manager().clear_all()


def _fresh_session():
    tmp = Path(tempfile.mkdtemp(prefix="queue_route_test_"))
    engine = create_engine(f"sqlite:///{tmp/'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    from backend.database import session as db_session

    db_session.SessionLocal = factory
    return factory, tmp


@pytest.mark.asyncio
async def test_generate_queue_route_reflects_queued_and_running():
    from backend.routes.generations import get_generation_queue

    factory, tmp = _fresh_session()
    try:
        db = factory()

        # A real generation row, as /generate would create.
        profile_id = str(uuid.uuid4())
        gen_id = str(uuid.uuid4())
        db.add(
            db_models.VoiceProfile(
                id=profile_id, name="Queue Test Voice", language="de"
            )
        )
        db.add(
            db_models.Generation(
                id=gen_id,
                profile_id=profile_id,
                text="Ein kurzer Testabsatz fuer die Warteschlange.",
                language="de",
                status="generating",
                engine="qwen",
            )
        )
        db.commit()

        task_manager = get_task_manager()
        task_manager.start_generation(gen_id, profile_id, "Ein kurzer Testabsatz")

        # queued (not yet picked up by the worker because it's parked on get)
        task_queue.enqueue_generation(gen_id, asyncio.sleep(0))

        response = await get_generation_queue(db)
        items = response["items"]
        assert any(
            i["generation_id"] == gen_id and i["state"] in ("queued", "running")
            for i in items
        )
        entry = next(i for i in items if i["generation_id"] == gen_id)
        assert entry["profile_id"] == profile_id
        assert entry["text_preview"].startswith("Ein kurzer")
        assert entry["enqueued_at"] is not None

        # progress registry is joined in
        task_manager.update_generation_progress(
            gen_id,
            state="generating",
            progress=0.5,
            chunk_index=1,
            chunk_count=2,
            message="Synthesizing chunk 1/2",
        )
        response2 = await get_generation_queue(db)
        entry2 = next(i for i in response2["items"] if i["generation_id"] == gen_id)
        assert entry2["state"] == "generating"
        assert entry2["progress"] == 0.5
        assert entry2["chunk_count"] == 2

        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
