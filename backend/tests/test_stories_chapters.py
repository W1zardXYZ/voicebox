"""Spec §4 — stories chapter/segment hierarchy + markdown import (real SQLite)."""

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
from backend.models import (
    MarkdownImportCommitRequest,
    MarkdownImportRequest,
    MarkdownChapterCommit,
    MarkdownSegmentCommit,
    StoryChapterCreate,
    StoryChapterUpdate,
    StorySegmentCreate,
    StorySegmentGenerateRequest,
    StorySegmentUpdate,
)
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
    tmp = Path(tempfile.mkdtemp(prefix="stories_chapters_"))
    engine = create_engine(f"sqlite:///{tmp/'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    from backend.database import session as db_session

    db_session.SessionLocal = factory
    return factory, tmp


def _seed_story_and_voice(db):
    story = db_models.Story(id=str(uuid.uuid4()), name="Buch")
    profile = db_models.VoiceProfile(
        id=str(uuid.uuid4()), name="Narrator", language="de"
    )
    db.add_all([story, profile])
    db.commit()
    return story, profile


MARKDOWN = """# Kapitel Eins

Der Wind wehte kalt über die Ebene.

[read aloud: Narrator]
Es war einmal ein König.
[/read aloud]

# Kapitel Zwei

Am Morgen erreichten sie das Tor.
"""


@pytest.mark.asyncio
async def test_import_preview_and_commit_hierarchy():
    from backend.services import stories

    factory, tmp = _fresh_session()
    try:
        db = factory()
        story, profile = _seed_story_and_voice(db)

        preview = stories.import_markdown_preview(
            MarkdownImportRequest(markdown=MARKDOWN, mode="h1")
        )
        assert [c.title for c in preview.chapters] == ["Kapitel Eins", "Kapitel Zwei"]
        # The read-aloud region is a segment with the narrator hint.
        hints = [s.speaker_hint for s in preview.chapters[0].segments]
        assert "Narrator" in hints

        commit = MarkdownImportCommitRequest(
            chapters=[
                MarkdownChapterCommit(
                    title=c.title,
                    segments=[
                        MarkdownSegmentCommit(text=s.text, speaker_hint=s.speaker_hint)
                        for s in c.segments
                    ],
                )
                for c in preview.chapters
            ]
        )
        detail = await stories.commit_markdown_import(story.id, commit, db)
        assert detail is not None
        assert len(detail.chapters) == 2
        segs = [s for c in detail.chapters for s in c.segments]
        assert len(segs) == 3
        # Speaker-hint lookup assigned the existing "Narrator" profile.
        assigned = next(s for s in segs if s.profile_id is not None)
        assert assigned.profile_id == profile.id
        assert assigned.profile_name == "Narrator"
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.asyncio
async def test_segment_crud_roundtrip():
    from backend.services import stories

    factory, tmp = _fresh_session()
    try:
        db = factory()
        story, profile = _seed_story_and_voice(db)

        chapter = await stories.create_chapter(
            story.id, StoryChapterCreate(title="Kapitel A"), db
        )
        assert chapter.title == "Kapitel A"

        seg = await stories.create_segment(
            story.id,
            StorySegmentCreate(chapter_id=chapter.id, text="Erster Satz.", profile_id=profile.id),
            db,
        )
        assert seg.status == "draft"
        assert seg.profile_id == profile.id

        updated = await stories.update_segment(
            story.id,
            seg.id,
            StorySegmentUpdate(text="Geänderter Satz."),
            db,
        )
        assert updated.text == "Geänderter Satz."

        chapter2 = await stories.update_chapter(
            story.id, chapter.id, StoryChapterUpdate(title="Kapitel B"), db
        )
        assert chapter2.title == "Kapitel B"

        assert await stories.delete_segment(story.id, seg.id, db) is True
        assert await stories.delete_chapter(story.id, chapter.id, db) is True
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.asyncio
async def test_generate_segment_enqueues_and_places_clip(monkeypatch):
    from backend.services import stories

    factory, tmp = _fresh_session()
    try:
        db = factory()
        story, profile = _seed_story_and_voice(db)
        # Story default voice — segments without an explicit speaker use it.
        story.default_voice_profile_id = profile.id
        db.commit()

        chapter = await stories.create_chapter(
            story.id, StoryChapterCreate(title="Kapitel A"), db
        )
        seg = await stories.create_segment(
            story.id,
            StorySegmentCreate(chapter_id=chapter.id, text="Ein Satz."),
            db,
        )

        captured = []

        def fake_enqueue(generation_id, coro):
            captured.append((generation_id, coro))

        monkeypatch.setattr(
            "backend.services.task_queue.enqueue_generation", fake_enqueue
        )

        result = await stories.generate_segment(
            story.id, seg.id, StorySegmentGenerateRequest(), db
        )
        assert result.status == "queued"
        assert result.generation_id
        assert len(captured) == 1

        # The timeline clip is placed and traced back to the segment.
        item = (
            db.query(db_models.StoryItem)
            .filter_by(story_segment_id=seg.id)
            .first()
        )
        assert item is not None
        assert item.generation_id == result.generation_id
        assert item.start_time_ms == 0
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.asyncio
async def test_generate_segment_requires_voice():
    from backend.services import stories

    factory, tmp = _fresh_session()
    try:
        db = factory()
        story, _profile = _seed_story_and_voice(db)
        chapter = await stories.create_chapter(
            story.id, StoryChapterCreate(title="Kapitel A"), db
        )
        seg = await stories.create_segment(
            story.id, StorySegmentCreate(chapter_id=chapter.id, text="Ein Satz."), db
        )

        with pytest.raises(ValueError, match="No voice assigned"):
            await stories.generate_segment(
                story.id, seg.id, StorySegmentGenerateRequest(), db
            )
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
