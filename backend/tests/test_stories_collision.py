"""Spec §5.2 — timeline overlap resolution in ``move_story_item``.

Moving a clip to a position that would overlap another clip on the same track
must nudge the placement to the first free gap instead of stacking clips.
"""

import shutil
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import models as db_models  # noqa: F401  (register tables)
from backend.database.models import Base
from backend.models import StoryItemMove


def _fresh_session():
    tmp = Path(tempfile.mkdtemp(prefix="stories_collision_"))
    engine = create_engine(f"sqlite:///{tmp/'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return factory, tmp


def _seed(db, story_id, profile_id):
    """Two generations on the same story: A (1s) at 0ms, B (2s) at 2000ms."""
    gen_a = db_models.Generation(
        id=str(uuid.uuid4()),
        profile_id=profile_id,
        text="A",
        language="en",
        audio_path="/tmp/a.wav",
        duration=1.0,
        status="completed",
    )
    gen_b = db_models.Generation(
        id=str(uuid.uuid4()),
        profile_id=profile_id,
        text="B",
        language="en",
        audio_path="/tmp/b.wav",
        duration=2.0,
        status="completed",
    )
    db.add_all([gen_a, gen_b])
    item_a = db_models.StoryItem(
        id=str(uuid.uuid4()),
        story_id=story_id,
        generation_id=gen_a.id,
        start_time_ms=0,
        track=0,
    )
    item_b = db_models.StoryItem(
        id=str(uuid.uuid4()),
        story_id=story_id,
        generation_id=gen_b.id,
        start_time_ms=2000,
        track=0,
    )
    db.add_all([item_a, item_b])
    db.commit()
    return gen_a, gen_b, item_a, item_b


@pytest.mark.asyncio
async def test_move_to_free_position_keeps_requested_time():
    from backend.services.stories import move_story_item

    factory, tmp = _fresh_session()
    try:
        db = factory()
        story = db_models.Story(id=str(uuid.uuid4()), name="s")
        profile = db_models.VoiceProfile(id=str(uuid.uuid4()), name="v", language="en")
        db.add_all([story, profile])
        db.commit()
        _, _, item_a, _ = _seed(db, story.id, profile.id)

        # Move A to 5000ms on track 0 — free (A:[5000,6000), B:[2000,4000)).
        moved = await move_story_item(
            story.id, item_a.id, StoryItemMove(start_time_ms=5000, track=0), db
        )
        assert moved.start_time_ms == 5000
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.asyncio
async def test_move_into_overlap_nudges_to_free_gap():
    from backend.services.stories import move_story_item

    factory, tmp = _fresh_session()
    try:
        db = factory()
        story = db_models.Story(id=str(uuid.uuid4()), name="s")
        profile = db_models.VoiceProfile(id=str(uuid.uuid4()), name="v", language="en")
        db.add_all([story, profile])
        db.commit()
        gen_a, _, item_a, item_b = _seed(db, story.id, profile.id)

        # Move B (2s) to 500ms — overlaps A (0..1000) and B's own old spot is
        # vacated, so the free gap starts after A: 1000 + 100 gap = 1100.
        moved = await move_story_item(
            story.id, item_b.id, StoryItemMove(start_time_ms=500, track=0), db
        )
        assert moved.start_time_ms == 1100, "should nudge past A + 100ms gap"
        assert moved.track == 0
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.asyncio
async def test_overlap_resolution_chain_nudges_past_second_item():
    from backend.services.stories import move_story_item

    factory, tmp = _fresh_session()
    try:
        db = factory()
        story = db_models.Story(id=str(uuid.uuid4()), name="s")
        profile = db_models.VoiceProfile(id=str(uuid.uuid4()), name="v", language="en")
        db.add_all([story, profile])
        db.commit()
        gen_a, gen_b, item_a, item_b = _seed(db, story.id, profile.id)

        # A third item C (3s) placed at 1500ms on track 0: overlaps B (2000..4000)
        # and A is before it — nudges past B: 4000 + 100 = 4100.
        gen_c = db_models.Generation(
            id=str(uuid.uuid4()),
            profile_id=profile.id,
            text="C",
            language="en",
            audio_path="/tmp/c.wav",
            duration=3.0,
            status="completed",
        )
        db.add(gen_c)
        item_c = db_models.StoryItem(
            id=str(uuid.uuid4()),
            story_id=story.id,
            generation_id=gen_c.id,
            start_time_ms=1500,
            track=0,
        )
        db.add(item_c)
        db.commit()

        moved = await move_story_item(
            story.id, item_c.id, StoryItemMove(start_time_ms=1500, track=0), db
        )
        assert moved.start_time_ms == 4100, "should nudge past B (ends 4000) + gap"
        db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
