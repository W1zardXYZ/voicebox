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


@pytest.mark.asyncio
async def test_generate_segment_uses_project_default_engine_and_language(monkeypatch):
    """Project-wide default engine/language apply when a segment doesn't override
    them, and an explicit per-segment override wins."""
    from backend.services import stories

    factory, tmp = _fresh_session()
    try:
        db = factory()
        story, profile = _seed_story_and_voice(db)
        story.default_voice_profile_id = profile.id
        story.default_engine = "kokoro"
        story.default_language = "de"
        db.commit()

        chapter = await stories.create_chapter(
            story.id, StoryChapterCreate(title="Kapitel A"), db
        )
        seg = await stories.create_segment(
            story.id,
            StorySegmentCreate(chapter_id=chapter.id, text="Ein Satz."),
            db,
        )

        async def fake_enqueue(generation_id, coro):
            pass

        monkeypatch.setattr(
            "backend.services.task_queue.enqueue_generation", fake_enqueue
        )

        import backend.services.history as history_service

        real_create = history_service.create_generation
        create_calls = []

        async def spy_create(**kwargs):
            create_calls.append(
                {
                    "engine": kwargs.get("engine"),
                    "language": kwargs.get("language"),
                }
            )
            return await real_create(**kwargs)

        monkeypatch.setattr(
            "backend.services.history.create_generation", spy_create
        )

        await stories.generate_segment(
            story.id, seg.id, StorySegmentGenerateRequest(), db
        )
        assert create_calls, "create_generation should have been called"
        assert create_calls[0]["engine"] == "kokoro"
        assert create_calls[0]["language"] == "de"

        # Explicit per-segment override wins over the project default.
        seg_row = db.query(db_models.StorySegment).filter_by(id=seg.id).first()
        seg_row.engine = "chatterbox"
        seg_row.language = "en"
        db.commit()
        create_calls.clear()
        await stories.generate_segment(
            story.id, seg.id, StorySegmentGenerateRequest(), db
        )
        assert create_calls[0]["engine"] == "chatterbox"
        assert create_calls[0]["language"] == "en"
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.asyncio
async def test_segment_pause_default_update_and_chapter_override():
    """The project-wide segment pause defaults to 400 ms, is updatable, and a
    chapter can override it."""
    from backend.services import stories
    from backend.models import StoryCreate

    factory, tmp = _fresh_session()
    try:
        db = factory()
        story, _profile = _seed_story_and_voice(db)
        # New stories default to 400 ms pause.
        assert db.refresh(story) is None or True
        assert story.segment_pause_ms == 400

        updated = await stories.update_story(
            story.id, StoryCreate(name="Buch", segment_pause_ms=800), db
        )
        assert updated.segment_pause_ms == 800

        ch = await stories.create_chapter(
            story.id, StoryChapterCreate(title="K", segment_pause_ms=600), db
        )
        assert ch.segment_pause_ms == 600

        # A chapter with no override exposes None (falls back to the story).
        ch2 = await stories.create_chapter(
            story.id, StoryChapterCreate(title="K2"), db
        )
        assert ch2.segment_pause_ms is None
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.asyncio
async def test_regenerate_segment_replaces_item(monkeypatch):
    """Regenerating a segment drops the previous story item so only the current
    version occupies the story/export (old generation stays in history)."""
    from backend.services import stories

    factory, tmp = _fresh_session()
    try:
        db = factory()
        story, profile = _seed_story_and_voice(db)
        story.default_voice_profile_id = profile.id
        db.commit()

        chapter = await stories.create_chapter(
            story.id, StoryChapterCreate(title="Kapitel A"), db
        )
        seg = await stories.create_segment(
            story.id, StorySegmentCreate(chapter_id=chapter.id, text="Ein Satz."), db
        )

        async def fake_enqueue(generation_id, coro):
            pass

        monkeypatch.setattr("backend.services.task_queue.enqueue_generation", fake_enqueue)

        r1 = await stories.generate_segment(
            story.id, seg.id, StorySegmentGenerateRequest(), db
        )
        items1 = db.query(db_models.StoryItem).filter_by(story_segment_id=seg.id).count()

        r2 = await stories.generate_segment(
            story.id, seg.id, StorySegmentGenerateRequest(), db
        )
        items2 = db.query(db_models.StoryItem).filter_by(story_segment_id=seg.id).count()

        assert items1 == 1
        assert items2 == 1  # replaced, not duplicated
        assert r1.generation_id != r2.generation_id
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.asyncio
async def test_get_story_materializes_chapters_for_legacy_flat_story():
    """A legacy story (items, no chapters) gets a default chapter on first read
    so the chapter/segment editor always appears (spec §4.6)."""
    from backend.services import stories

    factory, tmp = _fresh_session()
    try:
        db = factory()
        story, profile = _seed_story_and_voice(db)

        gen = db_models.Generation(
            id=str(uuid.uuid4()),
            profile_id=profile.id,
            text="Ein alter Satz.",
            language="de",
            audio_path="/tmp/x.wav",
            duration=2.0,
            status="completed",
            engine="qwen",
        )
        db.add(gen)
        db.add(
            db_models.StoryItem(
                id=str(uuid.uuid4()),
                story_id=story.id,
                generation_id=gen.id,
                start_time_ms=0,
                track=0,
            )
        )
        db.commit()

        detail = await stories.get_story(story.id, db)
        assert detail.chapters, "legacy story should be materialized into a chapter"
        chapter = detail.chapters[0]
        assert chapter.title == "Chapter 1"
        assert len(chapter.segments) == 1
        seg = chapter.segments[0]
        assert seg.text == "Ein alter Satz."
        assert seg.generation_id == gen.id
        assert seg.status == "completed"
        assert seg.profile_id == profile.id

        # Idempotent: a second read does not duplicate chapters.
        detail2 = await stories.get_story(story.id, db)
        assert len(detail2.chapters) == 1
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.asyncio
async def test_materialize_skips_when_chapters_exist():
    from backend.services import stories

    factory, tmp = _fresh_session()
    try:
        db = factory()
        story, profile = _seed_story_and_voice(db)
        chapter = await stories.create_chapter(
            story.id, StoryChapterCreate(title="Bestehend"), db
        )
        await stories.create_segment(
            story.id,
            StorySegmentCreate(chapter_id=chapter.id, text="Satz."),
            db,
        )
        # A story with existing chapters must not be re-materialized.
        gen = db_models.Generation(
            id=str(uuid.uuid4()),
            profile_id=profile.id,
            text="Zweiter Satz.",
            language="de",
            audio_path="/tmp/y.wav",
            duration=1.0,
            status="completed",
        )
        db.add(gen)
        db.add(
            db_models.StoryItem(
                id=str(uuid.uuid4()),
                story_id=story.id,
                generation_id=gen.id,
                start_time_ms=0,
            )
        )
        db.commit()

        detail = await stories.get_story(story.id, db)
        assert [c.title for c in detail.chapters] == ["Bestehend"]
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_apply_fades_shapes_edges():
    import numpy as np
    from backend.utils.audio import apply_fades

    sr = 16000
    audio = np.ones(sr * 2, dtype=np.float32)  # 2s of constant 1.0
    faded = apply_fades(audio, sr, fade_in_ms=500, fade_out_ms=500)

    assert faded.shape == audio.shape
    # First sample faded toward 0
    assert faded[0] < 0.05
    # Middle stays full
    assert faded[sr] == pytest.approx(1.0, abs=0.05)
    # Last sample faded toward 0
    assert faded[-1] < 0.05


def test_apply_fades_noop_when_zero():
    import numpy as np
    from backend.utils.audio import apply_fades

    audio = np.ones(100, dtype=np.float32)
    out = apply_fades(audio, 16000, 0, 0)
    assert out is audio


@pytest.mark.asyncio
async def test_commit_import_sets_narrator_and_defaults_segments():
    from backend.services import stories
    from backend.models import MarkdownChapterCommit, MarkdownSegmentCommit

    factory, tmp = _fresh_session()
    try:
        db = factory()
        story, narrator_profile = _seed_story_and_voice(db)

        commit = MarkdownImportCommitRequest(
            chapters=[
                MarkdownChapterCommit(
                    title="Kapitel",
                    segments=[MarkdownSegmentCommit(text="Erster Satz.")],
                )
            ],
            narrator_name="Erzähler",
            narrator_profile_id=narrator_profile.id,
        )
        detail = await stories.commit_markdown_import(story.id, commit, db)
        assert detail is not None

        # Narrator character created.
        assert len(detail.characters) == 1
        narrator = detail.characters[0]
        assert narrator.name == "Erzähler"
        assert narrator.is_narrator is True
        assert narrator.profile_id == narrator_profile.id

        # Every segment defaults to the narrator character + its voice.
        seg = detail.chapters[0].segments[0]
        assert seg.character_id == narrator.id
        assert seg.character_name == "Erzähler"
        # Voice is derived from the character at generation time.
        resolved = stories._resolve_segment_profile(seg, db, None)
        assert resolved is not None and resolved.id == narrator_profile.id
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.asyncio
async def test_segment_resolves_voice_from_assigned_character():
    from backend.services import stories

    factory, tmp = _fresh_session()
    try:
        db = factory()
        story, narrator_profile = _seed_story_and_voice(db)
        other_profile = db_models.VoiceProfile(id=str(uuid.uuid4()), name="Hexe", language="de")
        db.add(other_profile)
        db.commit()

        narrator = await stories.create_character(
            story.id, __test_create_character("Narrator", narrator_profile.id, is_narrator=True), db
        )
        witch = await stories.create_character(
            story.id, __test_create_character("Hexe", other_profile.id, is_narrator=False), db
        )

        chapter = await stories.create_chapter(story.id, StoryChapterCreate(title="K"), db)
        seg = await stories.create_segment(
            story.id, StorySegmentCreate(chapter_id=chapter.id, text="Satz."), db
        )
        # No character/profile → resolves to narrator.
        resolved = stories._resolve_segment_profile(seg, db, None)
        assert resolved is not None and resolved.id == narrator_profile.id

        # Assign the witch character → voice switches.
        seg = await stories.update_segment(
            story.id, seg.id, StorySegmentUpdate(character_id=witch.id), db
        )
        assert seg.character_name == "Hexe"
        assert seg.profile_id == other_profile.id
        resolved2 = stories._resolve_segment_profile(seg, db, None)
        assert resolved2.id == other_profile.id
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def __test_create_character(name, profile_id, is_narrator=False):
    from backend.models import StoryCharacterCreate

    return StoryCharacterCreate(name=name, profile_id=profile_id, is_narrator=is_narrator)


@pytest.mark.asyncio
async def test_reorder_segments_renumbers():
    from backend.services import stories

    factory, tmp = _fresh_session()
    try:
        db = factory()
        story, profile = _seed_story_and_voice(db)
        chapter = await stories.create_chapter(story.id, StoryChapterCreate(title="K"), db)
        s1 = await stories.create_segment(story.id, StorySegmentCreate(chapter_id=chapter.id, text="eins"), db)
        s2 = await stories.create_segment(story.id, StorySegmentCreate(chapter_id=chapter.id, text="zwei"), db)
        s3 = await stories.create_segment(story.id, StorySegmentCreate(chapter_id=chapter.id, text="drei"), db)

        ordered = await stories.reorder_segments(story.id, [s3.id, s1.id, s2.id], db)
        assert ordered is not None
        assert [s.text for s in ordered] == ["drei", "eins", "zwei"]
        assert [s.order_index for s in ordered] == [0, 1, 2]
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.asyncio
async def test_move_segment_to_other_chapter():
    from backend.services import stories

    factory, tmp = _fresh_session()
    try:
        db = factory()
        story, _profile = _seed_story_and_voice(db)
        ch1 = await stories.create_chapter(story.id, StoryChapterCreate(title="A"), db)
        ch2 = await stories.create_chapter(story.id, StoryChapterCreate(title="B"), db)
        seg = await stories.create_segment(story.id, StorySegmentCreate(chapter_id=ch1.id, text="beweg mich"), db)

        moved = await stories.move_segment(story.id, seg.id, to_chapter_id=ch2.id, db=db)
        assert moved is not None
        assert moved.chapter_id == ch2.id
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
