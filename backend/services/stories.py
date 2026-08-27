"""
Story management module.
"""

from typing import List, Optional
from datetime import datetime
import logging
import uuid
import tempfile
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import func

logger = logging.getLogger(__name__)

from .. import config
from ..models import (
    StoryCreate,
    StoryResponse,
    StoryDetailResponse,
    StoryItemDetail,
    StoryItemCreate,
    StoryItemBatchUpdate,
    StoryItemMove,
    StoryItemTrim,
    StoryItemVolumeUpdate,
    StoryItemSplit,
    StoryItemVersionUpdate,
    MarkdownImportRequest,
    MarkdownImportPreview,
    MarkdownImportCommitRequest,
    StoryChapterCreate,
    StoryChapterUpdate,
    StoryChapterResponse,
    StorySegmentCreate,
    StorySegmentUpdate,
    StorySegmentResponse,
    StoryCharacterCreate,
    StoryCharacterUpdate,
    StoryCharacterResponse,
)
from ..database import (
    Story as DBStory,
    StoryItem as DBStoryItem,
    StoryChapter as DBStoryChapter,
    StorySegment as DBStorySegment,
    StoryCharacter as DBStoryCharacter,
    Generation as DBGeneration,
    VoiceProfile as DBVoiceProfile,
)
from .history import _get_versions_for_generation
from ..utils.audio import load_audio, save_audio
import numpy as np


def _build_item_detail(
    item: DBStoryItem,
    generation: DBGeneration,
    profile_name: str,
    db: Session,
) -> StoryItemDetail:
    """Build a StoryItemDetail with version info from a story item and its generation."""
    versions, active_version_id = _get_versions_for_generation(generation.id, db)

    # Resolve the audio path: if version_id is set, use that version's audio
    audio_path = generation.audio_path
    if item.version_id and versions:
        for v in versions:
            if v.id == item.version_id:
                audio_path = v.audio_path
                break

    return StoryItemDetail(
        id=item.id,
        story_id=item.story_id,
        generation_id=item.generation_id,
        version_id=getattr(item, "version_id", None),
        start_time_ms=item.start_time_ms,
        track=item.track,
        trim_start_ms=getattr(item, "trim_start_ms", 0),
        trim_end_ms=getattr(item, "trim_end_ms", 0),
        created_at=item.created_at,
        profile_id=generation.profile_id,
        profile_name=profile_name,
        text=generation.text,
        language=generation.language,
        audio_path=audio_path,
        duration=generation.duration,
        seed=generation.seed,
        instruct=generation.instruct,
        engine=generation.engine,
        volume=getattr(item, "volume", 1.0),
        generation_created_at=generation.created_at,
        versions=versions,
        active_version_id=active_version_id,
    )


async def create_story(
    data: StoryCreate,
    db: Session,
) -> StoryResponse:
    """
    Create a new story.

    Args:
        data: Story creation data
        db: Database session

    Returns:
        Created story
    """
    db_story = DBStory(
        id=str(uuid.uuid4()),
        name=data.name,
        description=data.description,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    db.add(db_story)
    db.commit()
    db.refresh(db_story)

    item_count = db.query(func.count(DBStoryItem.id)).filter(DBStoryItem.story_id == db_story.id).scalar()

    response = StoryResponse.model_validate(db_story)
    response.item_count = item_count
    return response


async def list_stories(
    db: Session,
) -> List[StoryResponse]:
    """
    List all stories.

    Args:
        db: Database session

    Returns:
        List of stories with item counts
    """
    stories = db.query(DBStory).order_by(DBStory.updated_at.desc()).all()

    if not stories:
        return []

    # Batch-fetch all story item counts in one query to avoid an N+1 pattern
    # (previously there was one COUNT query per story in the loop below).
    story_ids = [s.id for s in stories]
    count_rows = (
        db.query(DBStoryItem.story_id, func.count(DBStoryItem.id).label("cnt"))
        .filter(DBStoryItem.story_id.in_(story_ids))
        .group_by(DBStoryItem.story_id)
        .all()
    )
    item_counts = {row.story_id: row.cnt for row in count_rows}

    result = []
    for story in stories:
        response = StoryResponse.model_validate(story)
        response.item_count = item_counts.get(story.id, 0)
        result.append(response)

    return result


async def get_story(
    story_id: str,
    db: Session,
) -> Optional[StoryDetailResponse]:
    """
    Get a story with all its items.

    Legacy stories (flat item lists) are auto-materialized into a single
    chapter of one segment-per-item on first read, so the chapter/segment
    editor is the visible experience for every story (spec §4.6). The
    materialization is idempotent and non-destructive — existing items and
    their generations are untouched; segments are linked back to them.

    Args:
        story_id: Story ID
        db: Database session

    Returns:
        Story with items or None if not found
    """
    story = db.query(DBStory).filter_by(id=story_id).first()
    if not story:
        return None

    _materialize_default_chapters(story_id, db)

    items = (
        db.query(DBStoryItem, DBGeneration, DBVoiceProfile.name.label("profile_name"))
        .join(DBGeneration, DBStoryItem.generation_id == DBGeneration.id)
        .join(DBVoiceProfile, DBGeneration.profile_id == DBVoiceProfile.id)
        .filter(DBStoryItem.story_id == story_id)
        .order_by(DBStoryItem.start_time_ms)
        .all()
    )

    item_details = []
    for item, generation, profile_name in items:
        item_details.append(_build_item_detail(item, generation, profile_name, db))

    response = StoryDetailResponse.model_validate(story)
    response.items = item_details
    response.chapters = _list_chapters(story_id, db)
    response.characters = _list_characters(story_id, db)
    return response


async def update_story(
    story_id: str,
    data: StoryCreate,
    db: Session,
) -> Optional[StoryResponse]:
    """
    Update a story.

    Args:
        story_id: Story ID
        data: Update data
        db: Database session

    Returns:
        Updated story or None if not found
    """
    story = db.query(DBStory).filter_by(id=story_id).first()
    if not story:
        return None

    story.name = data.name
    story.description = data.description
    story.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(story)

    item_count = db.query(func.count(DBStoryItem.id)).filter(DBStoryItem.story_id == story.id).scalar()

    response = StoryResponse.model_validate(story)
    response.item_count = item_count
    return response


async def delete_story(
    story_id: str,
    db: Session,
) -> bool:
    """
    Delete a story and all its items.

    Args:
        story_id: Story ID
        db: Database session

    Returns:
        True if deleted, False if not found
    """
    story = db.query(DBStory).filter_by(id=story_id).first()
    if not story:
        return False

    # Delete all items
    db.query(DBStoryItem).filter_by(story_id=story_id).delete()

    # Delete story
    db.delete(story)
    db.commit()

    return True


async def add_item_to_story(
    story_id: str,
    data: StoryItemCreate,
    db: Session,
) -> Optional[StoryItemDetail]:
    """
    Add a generation to a story.

    Args:
        story_id: Story ID
        data: Item creation data
        db: Database session

    Returns:
        Created item detail or None if story/generation not found
    """
    # Verify story exists
    story = db.query(DBStory).filter_by(id=story_id).first()
    if not story:
        return None

    # Verify generation exists
    generation = db.query(DBGeneration).filter_by(id=data.generation_id).first()
    if not generation:
        return None

    # Check if generation is already in story
    existing = db.query(DBStoryItem).filter_by(story_id=story_id, generation_id=data.generation_id).first()
    if existing:
        # Return existing item
        profile = db.query(DBVoiceProfile).filter_by(id=generation.profile_id).first()
        return _build_item_detail(existing, generation, profile.name if profile else "Unknown", db)

    # Get track from data or default to 0
    track = data.track if data.track is not None else 0

    # Calculate start_time_ms if not provided
    if data.start_time_ms is not None:
        start_time_ms = data.start_time_ms
    else:
        existing_items = (
            db.query(DBStoryItem, DBGeneration)
            .join(DBGeneration, DBStoryItem.generation_id == DBGeneration.id)
            .filter(
                DBStoryItem.story_id == story_id,
                DBStoryItem.track == track,
            )
            .all()
        )

        if not existing_items:
            start_time_ms = 0
        else:
            max_end_time_ms = 0
            for item, gen in existing_items:
                item_end_ms = item.start_time_ms + int(gen.duration * 1000)
                max_end_time_ms = max(max_end_time_ms, item_end_ms)

            # Add 200ms gap after the last item
            start_time_ms = max_end_time_ms + 200

    # Create item
    item = DBStoryItem(
        id=str(uuid.uuid4()),
        story_id=story_id,
        generation_id=data.generation_id,
        start_time_ms=start_time_ms,
        track=track,
        created_at=datetime.utcnow(),
    )

    db.add(item)

    # Update story updated_at
    story.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(item)

    # Get profile name
    profile = db.query(DBVoiceProfile).filter_by(id=generation.profile_id).first()

    return _build_item_detail(item, generation, profile.name if profile else "Unknown", db)


async def move_story_item(
    story_id: str,
    item_id: str,
    data: StoryItemMove,
    db: Session,
) -> Optional[StoryItemDetail]:
    """
    Move a story item (update position and/or track).

    Applies overlap resolution (spec §5.2): the requested placement is nudged
    forward to the first free gap on the target track when it would overlap an
    existing item's ``[start, start+duration)`` range, so the timeline can
    never hold two fully-overlapping clips on one track. The returned detail
    reflects the final (possibly nudged) placement.

    Args:
        story_id: Story ID
        item_id: Story item ID
        data: New position and track data
        db: Database session

    Returns:
        Updated item detail or None if not found
    """
    # Get the item
    item = (
        db.query(DBStoryItem)
        .filter_by(
            id=item_id,
            story_id=story_id,
        )
        .first()
    )
    if not item:
        return None

    # Get the generation
    generation = db.query(DBGeneration).filter_by(id=item.generation_id).first()
    if not generation:
        return None

    requested_start = data.start_time_ms
    requested_track = data.track

    final_start = _resolve_collision_free_placement(
        db,
        story_id=story_id,
        exclude_item_id=item.id,
        track=requested_track,
        start_ms=requested_start,
        duration_ms=int((generation.duration or 0) * 1000),
    )

    # Update position and track
    item.start_time_ms = final_start
    item.track = requested_track

    # Update story updated_at
    story = db.query(DBStory).filter_by(id=story_id).first()
    if story:
        story.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(item)

    # Get profile name
    profile = db.query(DBVoiceProfile).filter_by(id=generation.profile_id).first()

    return _build_item_detail(item, generation, profile.name if profile else "Unknown", db)


def _resolve_collision_free_placement(
    db: Session,
    *,
    story_id: str,
    exclude_item_id: str,
    track: int,
    start_ms: int,
    duration_ms: int,
    gap_ms: int = 100,
) -> int:
    """Return the first placement on *track* that does not overlap another item.

    Starts at *start_ms* and nudges forward past any overlapping item (plus a
    *gap_ms* cushion). An item with unknown/zero duration is treated as a
    point at its ``start_time_ms`` so it can never block the timeline
    forever. Pure query logic — no writes.
    """
    if duration_ms <= 0:
        duration_ms = 1

    others = (
        db.query(DBStoryItem, DBGeneration)
        .join(DBGeneration, DBStoryItem.generation_id == DBGeneration.id)
        .filter(
            DBStoryItem.story_id == story_id,
            DBStoryItem.track == track,
            DBStoryItem.id != exclude_item_id,
        )
        .all()
    )

    candidate = max(0, start_ms)
    while True:
        blocker_end = None
        for other_item, other_gen in others:
            other_dur = int((other_gen.duration or 0) * 1000)
            if other_dur <= 0:
                other_dur = 1
            other_start = other_item.start_time_ms
            # [candidate, candidate+duration) ∩ [other_start, other_start+other_dur)
            if candidate < other_start + other_dur and other_start < candidate + duration_ms:
                blocker_end = max(blocker_end or 0, other_start + other_dur)
        if blocker_end is None:
            return candidate
        candidate = blocker_end + gap_ms


async def remove_item_from_story(
    story_id: str,
    item_id: str,
    db: Session,
) -> bool:
    """
    Remove a story item from a story.

    Args:
        story_id: Story ID
        item_id: Story item ID to remove
        db: Database session

    Returns:
        True if removed, False if not found
    """
    item = (
        db.query(DBStoryItem)
        .filter_by(
            id=item_id,
            story_id=story_id,
        )
        .first()
    )
    if not item:
        return False

    # Delete item
    db.delete(item)

    # Update story updated_at
    story = db.query(DBStory).filter_by(id=story_id).first()
    if story:
        story.updated_at = datetime.utcnow()

    db.commit()
    return True


async def trim_story_item(
    story_id: str,
    item_id: str,
    data: StoryItemTrim,
    db: Session,
) -> Optional[StoryItemDetail]:
    """
    Trim a story item (update trim_start_ms and trim_end_ms).

    Args:
        story_id: Story ID
        item_id: Story item ID
        data: Trim data (trim_start_ms, trim_end_ms)
        db: Database session

    Returns:
        Updated item detail or None if not found
    """
    # Get the item
    item = (
        db.query(DBStoryItem)
        .filter_by(
            id=item_id,
            story_id=story_id,
        )
        .first()
    )
    if not item:
        return None

    # Get the generation
    generation = db.query(DBGeneration).filter_by(id=item.generation_id).first()
    if not generation:
        return None

    # Validate trim values don't exceed duration
    max_duration_ms = int(generation.duration * 1000)
    if data.trim_start_ms + data.trim_end_ms >= max_duration_ms:
        return None  # Invalid trim - would result in zero or negative duration

    # Update trim values
    item.trim_start_ms = data.trim_start_ms
    item.trim_end_ms = data.trim_end_ms

    # Update story updated_at
    story = db.query(DBStory).filter_by(id=story_id).first()
    if story:
        story.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(item)

    # Get profile name
    profile = db.query(DBVoiceProfile).filter_by(id=generation.profile_id).first()

    return _build_item_detail(item, generation, profile.name if profile else "Unknown", db)


async def update_story_item_volume(
    story_id: str,
    item_id: str,
    data: StoryItemVolumeUpdate,
    db: Session,
) -> Optional[StoryItemDetail]:
    """Update a story item's playback volume (per-clip linear gain)."""
    item = (
        db.query(DBStoryItem)
        .filter_by(id=item_id, story_id=story_id)
        .first()
    )
    if not item:
        return None
    generation = db.query(DBGeneration).filter_by(id=item.generation_id).first()
    if not generation:
        return None

    item.volume = data.volume

    story = db.query(DBStory).filter_by(id=story_id).first()
    if story:
        story.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(item)

    profile = db.query(DBVoiceProfile).filter_by(id=generation.profile_id).first()
    return _build_item_detail(item, generation, profile.name if profile else "Unknown", db)


async def split_story_item(
    story_id: str,
    item_id: str,
    data: StoryItemSplit,
    db: Session,
) -> Optional[List[StoryItemDetail]]:
    """
    Split a story item at a given time, creating two clips.

    Args:
        story_id: Story ID
        item_id: Story item ID to split
        data: Split data (split_time_ms - time within clip to split at)
        db: Database session

    Returns:
        List of two updated item details (original and new) or None if not found/invalid
    """
    # Get the item with a row lock to prevent concurrent splits on the
    # same clip (e.g. from rapid double-clicks racing each other).
    item = (
        db.query(DBStoryItem)
        .filter_by(
            id=item_id,
            story_id=story_id,
        )
        .with_for_update()
        .first()
    )
    if not item:
        return None

    # Get the generation
    generation = db.query(DBGeneration).filter_by(id=item.generation_id).first()
    if not generation:
        return None

    # Calculate effective duration and validate split point
    current_trim_start = getattr(item, "trim_start_ms", 0)
    current_trim_end = getattr(item, "trim_end_ms", 0)
    original_duration_ms = int(generation.duration * 1000)
    effective_duration_ms = original_duration_ms - current_trim_start - current_trim_end

    # Validate split_time_ms is within the effective duration
    if data.split_time_ms <= 0 or data.split_time_ms >= effective_duration_ms:
        return None  # Invalid split point

    # Calculate the absolute time in the original audio where we're splitting
    absolute_split_ms = current_trim_start + data.split_time_ms

    # Update original clip: trim from the end
    item.trim_end_ms = original_duration_ms - absolute_split_ms

    # Create new clip: starts after the split, trimmed from the start
    new_item = DBStoryItem(
        id=str(uuid.uuid4()),
        story_id=story_id,
        generation_id=item.generation_id,  # Same generation, different trim
        version_id=getattr(item, "version_id", None),  # Preserve pinned version
        start_time_ms=item.start_time_ms + data.split_time_ms,
        track=item.track,
        trim_start_ms=absolute_split_ms,
        trim_end_ms=current_trim_end,
        volume=getattr(item, "volume", 1.0),
        created_at=datetime.utcnow(),
    )

    db.add(new_item)

    # Update story updated_at
    story = db.query(DBStory).filter_by(id=story_id).first()
    if story:
        story.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(item)
    db.refresh(new_item)

    # Get profile name
    profile = db.query(DBVoiceProfile).filter_by(id=generation.profile_id).first()
    profile_name = profile.name if profile else "Unknown"

    return [
        _build_item_detail(item, generation, profile_name, db),
        _build_item_detail(new_item, generation, profile_name, db),
    ]


async def duplicate_story_item(
    story_id: str,
    item_id: str,
    db: Session,
) -> Optional[StoryItemDetail]:
    """
    Duplicate a story item, creating a copy with all properties.

    Args:
        story_id: Story ID
        item_id: Story item ID to duplicate
        db: Database session

    Returns:
        New item detail or None if not found
    """
    # Get the original item
    original_item = (
        db.query(DBStoryItem)
        .filter_by(
            id=item_id,
            story_id=story_id,
        )
        .first()
    )
    if not original_item:
        return None

    # Get the generation
    generation = db.query(DBGeneration).filter_by(id=original_item.generation_id).first()
    if not generation:
        return None

    # Calculate effective duration
    current_trim_start = getattr(original_item, "trim_start_ms", 0)
    current_trim_end = getattr(original_item, "trim_end_ms", 0)
    original_duration_ms = int(generation.duration * 1000)
    effective_duration_ms = original_duration_ms - current_trim_start - current_trim_end

    # Create duplicate item - place it right after the original
    new_item = DBStoryItem(
        id=str(uuid.uuid4()),
        story_id=story_id,
        generation_id=original_item.generation_id,  # Same generation as original
        version_id=getattr(original_item, "version_id", None),  # Preserve pinned version
        start_time_ms=original_item.start_time_ms + effective_duration_ms + 200,  # 200ms gap
        track=original_item.track,
        trim_start_ms=current_trim_start,
        trim_end_ms=current_trim_end,
        volume=getattr(original_item, "volume", 1.0),
        created_at=datetime.utcnow(),
    )

    db.add(new_item)

    # Update story updated_at
    story = db.query(DBStory).filter_by(id=story_id).first()
    if story:
        story.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(new_item)

    # Get profile name
    profile = db.query(DBVoiceProfile).filter_by(id=generation.profile_id).first()

    return _build_item_detail(new_item, generation, profile.name if profile else "Unknown", db)


async def update_story_item_times(
    story_id: str,
    data: StoryItemBatchUpdate,
    db: Session,
) -> bool:
    """
    Update story item timecodes.

    Args:
        story_id: Story ID
        data: Batch update data with timecodes
        db: Database session

    Returns:
        True if updated, False if story not found or invalid
    """
    story = db.query(DBStory).filter_by(id=story_id).first()
    if not story:
        return False

    # Get all items for this story
    items = db.query(DBStoryItem).filter_by(story_id=story_id).all()
    item_map = {item.generation_id: item for item in items}

    # Verify all generation IDs belong to this story and update timecodes
    for update in data.updates:
        if update.generation_id not in item_map:
            return False
        item_map[update.generation_id].start_time_ms = update.start_time_ms

    # Update story updated_at
    story.updated_at = datetime.utcnow()

    db.commit()
    return True


async def reorder_story_items(
    story_id: str,
    generation_ids: List[str],
    db: Session,
    gap_ms: int = 200,
) -> Optional[List[StoryItemDetail]]:
    """
    Reorder story items and recalculate timecodes.

    Args:
        story_id: Story ID
        generation_ids: List of generation IDs in the desired order
        db: Database session
        gap_ms: Gap in milliseconds between items (default 200ms)

    Returns:
        Updated list of story items with new timecodes, or None if invalid
    """
    story = db.query(DBStory).filter_by(id=story_id).first()
    if not story:
        return None

    # Get all items for this story with their generation data
    items_with_gen = (
        db.query(DBStoryItem, DBGeneration, DBVoiceProfile.name.label("profile_name"))
        .join(DBGeneration, DBStoryItem.generation_id == DBGeneration.id)
        .join(DBVoiceProfile, DBGeneration.profile_id == DBVoiceProfile.id)
        .filter(DBStoryItem.story_id == story_id)
        .all()
    )

    # Create maps for quick lookup
    item_map = {item.generation_id: (item, gen, profile_name) for item, gen, profile_name in items_with_gen}

    # Verify all generation IDs belong to this story
    if set(generation_ids) != set(item_map.keys()):
        return None

    # Recalculate timecodes based on new order
    current_time_ms = 0
    updated_items = []

    for gen_id in generation_ids:
        item, generation, profile_name = item_map[gen_id]

        # Update the item's start time
        item.start_time_ms = current_time_ms

        # Calculate the duration in ms
        duration_ms = int(generation.duration * 1000)

        # Move to next position (current end + gap)
        current_time_ms += duration_ms + gap_ms

        # Build the response item
        updated_items.append(_build_item_detail(item, generation, profile_name, db))

    # Update story updated_at
    story.updated_at = datetime.utcnow()

    db.commit()
    return updated_items


async def set_story_item_version(
    story_id: str,
    item_id: str,
    data: StoryItemVersionUpdate,
    db: Session,
) -> Optional[StoryItemDetail]:
    """
    Pin a story item to a specific generation version.

    Args:
        story_id: Story ID
        item_id: Story item ID
        data: Version update data (version_id or null for default)
        db: Database session

    Returns:
        Updated item detail or None if not found
    """
    item = (
        db.query(DBStoryItem)
        .filter_by(
            id=item_id,
            story_id=story_id,
        )
        .first()
    )
    if not item:
        return None

    generation = db.query(DBGeneration).filter_by(id=item.generation_id).first()
    if not generation:
        return None

    # Validate version_id belongs to this generation if provided
    if data.version_id:
        from ..database import GenerationVersion as DBGenerationVersion

        version = (
            db.query(DBGenerationVersion)
            .filter_by(
                id=data.version_id,
                generation_id=item.generation_id,
            )
            .first()
        )
        if not version:
            return None

    item.version_id = data.version_id

    # Update story updated_at
    story = db.query(DBStory).filter_by(id=story_id).first()
    if story:
        story.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(item)

    profile = db.query(DBVoiceProfile).filter_by(id=generation.profile_id).first()

    return _build_item_detail(item, generation, profile.name if profile else "Unknown", db)


async def export_story_audio(
    story_id: str,
    db: Session,
) -> Optional[bytes]:
    """
    Export story as single mixed audio file with timecode-based mixing.

    Args:
        story_id: Story ID
        db: Database session

    Returns:
        Audio file bytes or None if story not found
    """
    story = db.query(DBStory).filter_by(id=story_id).first()
    if not story:
        return None

    # Get all items ordered by start_time_ms
    items = (
        db.query(DBStoryItem, DBGeneration)
        .join(DBGeneration, DBStoryItem.generation_id == DBGeneration.id)
        .filter(DBStoryItem.story_id == story_id)
        .order_by(DBStoryItem.start_time_ms)
        .all()
    )

    if not items:
        return None

    # Load all audio files and calculate total duration
    audio_data = []
    sample_rate = 24000  # Default sample rate

    for item, generation in items:
        # Resolve audio path: use pinned version if set, otherwise generation default
        resolved_audio_path = generation.audio_path
        if getattr(item, "version_id", None):
            from ..database import GenerationVersion as DBGenerationVersion

            version = db.query(DBGenerationVersion).filter_by(id=item.version_id).first()
            if version:
                resolved_audio_path = version.audio_path

        audio_path = config.resolve_storage_path(resolved_audio_path)
        if audio_path is None or not audio_path.exists():
            continue

        try:
            audio, sr = load_audio(str(audio_path), sample_rate=sample_rate)
            sample_rate = sr  # Use actual sample rate from first file

            # Get trim values
            trim_start_ms = getattr(item, "trim_start_ms", 0)
            trim_end_ms = getattr(item, "trim_end_ms", 0)

            # Calculate effective duration
            original_duration_ms = int(generation.duration * 1000)
            effective_duration_ms = original_duration_ms - trim_start_ms - trim_end_ms

            # Slice audio based on trim values
            trim_start_sample = int((trim_start_ms / 1000.0) * sample_rate)
            trim_end_sample = int((trim_end_ms / 1000.0) * sample_rate)

            # Extract the trimmed portion
            if trim_end_ms > 0:
                trimmed_audio = (
                    audio[trim_start_sample:-trim_end_sample] if trim_end_sample > 0 else audio[trim_start_sample:]
                )
            else:
                trimmed_audio = audio[trim_start_sample:]

            # Apply per-clip volume to the export mix.
            volume = float(getattr(item, "volume", 1.0) or 1.0)
            if volume != 1.0:
                trimmed_audio = trimmed_audio * volume

            # Store audio with its timecode info
            start_time_ms = item.start_time_ms

            audio_data.append(
                {
                    "audio": trimmed_audio,
                    "start_time_ms": start_time_ms,
                    "duration_ms": effective_duration_ms,
                }
            )
        except Exception:
            # Skip files that can't be loaded
            continue

    if not audio_data:
        return None

    # Calculate total duration: max(start_time_ms + duration_ms)
    max_end_time_ms = max((data["start_time_ms"] + data["duration_ms"] for data in audio_data), default=0)

    # Convert to samples
    total_samples = int((max_end_time_ms / 1000.0) * sample_rate)

    # Create output buffer initialized to zeros
    final_audio = np.zeros(total_samples, dtype=np.float32)

    # Mix each audio segment at its timecode position
    for data in audio_data:
        audio = data["audio"]
        start_time_ms = data["start_time_ms"]

        # Calculate start sample index
        start_sample = int((start_time_ms / 1000.0) * sample_rate)

        # Ensure we don't exceed buffer bounds
        audio_length = len(audio)
        end_sample = min(start_sample + audio_length, total_samples)

        if start_sample < total_samples:
            # Trim audio if it extends beyond buffer
            audio_to_mix = audio[: end_sample - start_sample]

            # Mix: add audio to existing buffer (overlapping audio will sum)
            # Normalize to prevent clipping (simple approach: divide by max)
            final_audio[start_sample:end_sample] += audio_to_mix

    # Normalize to prevent clipping
    max_val = np.abs(final_audio).max()
    if max_val > 1.0:
        final_audio = final_audio / max_val

    # Save to temporary file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        save_audio(final_audio, tmp_path, sample_rate)

        # Read file bytes
        with open(tmp_path, "rb") as f:
            audio_bytes = f.read()

        return audio_bytes
    finally:
        # Clean up temp file
        Path(tmp_path).unlink(missing_ok=True)


# ── Chapters / segments (spec §4) ──────────────────────────────────────────


def _segment_response(segment: DBStorySegment, db: Session) -> StorySegmentResponse:
    """Build a StorySegmentResponse, denormalizing the profile name, its
    character (speaker), and the linked timeline clip's volume."""
    profile_name = None
    if segment.profile_id:
        profile = db.query(DBVoiceProfile).filter_by(id=segment.profile_id).first()
        profile_name = profile.name if profile else None

    character_name = None
    if segment.character_id:
        character = db.query(DBStoryCharacter).filter_by(id=segment.character_id).first()
        if character is not None:
            character_name = character.name

    volume = 1.0
    if segment.generation_id:
        linked_item = (
            db.query(DBStoryItem)
            .filter_by(generation_id=segment.generation_id)
            .order_by(DBStoryItem.created_at.desc())
            .first()
        )
        if linked_item is not None:
            volume = getattr(linked_item, "volume", 1.0) or 1.0

    return StorySegmentResponse(
        id=segment.id,
        chapter_id=segment.chapter_id,
        order_index=segment.order_index,
        text=segment.text,
        profile_id=segment.profile_id,
        profile_name=profile_name,
        character_id=getattr(segment, "character_id", None),
        character_name=character_name,
        tag=getattr(segment, "tag", None),
        engine=segment.engine,
        model_size=segment.model_size,
        language=segment.language,
        status=segment.status,
        generation_id=segment.generation_id,
        fade_in_ms=getattr(segment, "fade_in_ms", 0),
        fade_out_ms=getattr(segment, "fade_out_ms", 0),
        volume=volume,
        created_at=segment.created_at,
        updated_at=segment.updated_at,
    )


def _character_response(character: DBStoryCharacter, db: Session) -> StoryCharacterResponse:
    profile_name = None
    if character.profile_id:
        profile = db.query(DBVoiceProfile).filter_by(id=character.profile_id).first()
        profile_name = profile.name if profile else None
    return StoryCharacterResponse(
        id=character.id,
        story_id=character.story_id,
        name=character.name,
        profile_id=character.profile_id,
        profile_name=profile_name,
        is_narrator=character.is_narrator,
        order_index=character.order_index,
        created_at=character.created_at,
        updated_at=character.updated_at,
    )


def _list_characters(story_id: str, db: Session) -> list[StoryCharacterResponse]:
    characters = (
        db.query(DBStoryCharacter)
        .filter_by(story_id=story_id)
        .order_by(DBStoryCharacter.order_index)
        .all()
    )
    return [_character_response(c, db) for c in characters]


def _ensure_character_order(db: Session, story_id: str) -> None:
    characters = (
        db.query(DBStoryCharacter)
        .filter_by(story_id=story_id)
        .order_by(DBStoryCharacter.order_index, DBStoryCharacter.created_at)
        .all()
    )
    for i, char in enumerate(characters):
        if char.order_index != i:
            char.order_index = i
    db.flush()


def _chapter_response(chapter: DBStoryChapter, db: Session) -> StoryChapterResponse:
    segments = (
        db.query(DBStorySegment)
        .filter_by(chapter_id=chapter.id)
        .order_by(DBStorySegment.order_index)
        .all()
    )
    return StoryChapterResponse(
        id=chapter.id,
        story_id=chapter.story_id,
        title=chapter.title,
        source=chapter.source,
        order_index=chapter.order_index,
        created_at=chapter.created_at,
        updated_at=chapter.updated_at,
        segments=[_segment_response(s, db) for s in segments],
    )


def _list_chapters(story_id: str, db: Session) -> list[StoryChapterResponse]:
    chapters = (
        db.query(DBStoryChapter)
        .filter_by(story_id=story_id)
        .order_by(DBStoryChapter.order_index)
        .all()
    )
    return [_chapter_response(c, db) for c in chapters]


def _materialize_default_chapters(story_id: str, db: Session) -> None:
    """Give a legacy flat story a chapter structure so the chapter editor shows.

    If a story has items but no chapters, create a single "Chapter 1" with one
    segment per item (in timeline order), each linked to the item's existing
    generation so nothing is re-synthesized. Idempotent — a no-op once chapters
    exist. Non-destructive: items and generations are left untouched.
    """
    if db.query(DBStoryChapter).filter_by(story_id=story_id).count() > 0:
        return

    items = (
        db.query(DBStoryItem, DBGeneration)
        .join(DBGeneration, DBStoryItem.generation_id == DBGeneration.id)
        .filter(DBStoryItem.story_id == story_id)
        .order_by(DBStoryItem.start_time_ms)
        .all()
    )
    if not items:
        return

    chapter = DBStoryChapter(
        id=str(uuid.uuid4()),
        story_id=story_id,
        title="Chapter 1",
        order_index=0,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(chapter)

    for i, (item, generation) in enumerate(items):
        db.add(
            DBStorySegment(
                id=str(uuid.uuid4()),
                chapter_id=chapter.id,
                order_index=i,
                text=generation.text,
                profile_id=generation.profile_id,
                engine=generation.engine,
                model_size=generation.model_size,
                language=generation.language,
                status="completed" if (generation.status or "") == "completed" else "draft",
                generation_id=generation.id,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )

    db.commit()
    logger.info("Materialized default chapter for story %s (%d segments)", story_id, len(items))


def _ensure_chapter_order(db: Session, story_id: str) -> None:
    """Re-index chapter order_index to 0..n-1 after insert/delete/reorder."""
    chapters = (
        db.query(DBStoryChapter)
        .filter_by(story_id=story_id)
        .order_by(DBStoryChapter.order_index, DBStoryChapter.created_at)
        .all()
    )
    for i, chapter in enumerate(chapters):
        if chapter.order_index != i:
            chapter.order_index = i
    db.flush()


def _ensure_segment_order(db: Session, chapter_id: str) -> None:
    """Re-index segment order_index to 0..n-1 after insert/delete."""
    segments = (
        db.query(DBStorySegment)
        .filter_by(chapter_id=chapter_id)
        .order_by(DBStorySegment.order_index, DBStorySegment.created_at)
        .all()
    )
    for i, segment in enumerate(segments):
        if segment.order_index != i:
            segment.order_index = i
    db.flush()


def import_markdown_preview(data: MarkdownImportRequest) -> MarkdownImportPreview:
    """Segment *markdown* into a preview (spec §4.3) — nothing is written."""
    from .story_markdown import segment_markdown
    from ..models import MarkdownChapterPreview, MarkdownSegmentPreview

    chapters = segment_markdown(
        data.markdown,
        mode=data.mode,
        speak_untagged=data.speak_untagged,
        combine_max_chars=data.combine_max_chars,
        custom_open_tag=data.custom_open_tag,
        custom_close_tag=data.custom_close_tag,
    )
    return MarkdownImportPreview(
        chapters=[
            MarkdownChapterPreview(
                title=c.title,
                level=c.level,
                segments=[
                    MarkdownSegmentPreview(
                        text=s.text,
                        source_span=s.source_span,
                        tags=s.tags,
                        speaker_hint=s.speaker_hint,
                    )
                    for s in c.segments
                ],
            )
            for c in chapters
        ]
    )


async def commit_markdown_import(
    story_id: str,
    data: MarkdownImportCommitRequest,
    db: Session,
) -> Optional[StoryDetailResponse]:
    """Persist an approved segmentation as chapters + segments (spec §4.3).

    When ``narrator_profile_id`` is provided, a narrator character is created
    (or reused) and assigned to every imported segment, so the project has a
    sensible default voice before any manual assignment.
    """
    story = db.query(DBStory).filter_by(id=story_id).first()
    if not story:
        return None

    narrator_character_id = None
    if data.narrator_profile_id:
        narrator = (
            db.query(DBStoryCharacter)
            .filter_by(story_id=story_id, is_narrator=True)
            .order_by(DBStoryCharacter.order_index)
            .first()
        )
        if narrator is not None:
            narrator.profile_id = data.narrator_profile_id
            if data.narrator_name:
                narrator.name = data.narrator_name
            narrator.updated_at = datetime.utcnow()
            narrator_character_id = narrator.id
        else:
            narrator = DBStoryCharacter(
                id=str(uuid.uuid4()),
                story_id=story_id,
                name=data.narrator_name or "Narrator",
                profile_id=data.narrator_profile_id,
                is_narrator=True,
                order_index=0,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(narrator)
            db.flush()
            narrator_character_id = narrator.id

    existing_count = db.query(DBStoryChapter).filter_by(story_id=story_id).count()

    for ch_index, chapter in enumerate(data.chapters):
        db_chapter = DBStoryChapter(
            id=str(uuid.uuid4()),
            story_id=story_id,
            title=chapter.title or "Untitled",
            order_index=existing_count + ch_index,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(db_chapter)

        for seg_index, seg in enumerate(chapter.segments):
            profile_id = seg.profile_id
            if profile_id is None and seg.speaker_hint:
                # Look up an existing profile by (case-insensitive) name so a
                # `[read aloud: Narrator]` hint maps to a real voice when one
                # exists; otherwise the segment stays unassigned.
                match = (
                    db.query(DBVoiceProfile)
                    .filter(func.lower(DBVoiceProfile.name) == seg.speaker_hint.lower())
                    .first()
                )
                if match:
                    profile_id = match.id

            db.add(
                DBStorySegment(
                    id=str(uuid.uuid4()),
                    chapter_id=db_chapter.id,
                    order_index=seg_index,
                    text=seg.text,
                    profile_id=profile_id,
                    # Default every imported segment to the narrator.
                    character_id=narrator_character_id,
                    tag=seg.tag,
                    status="draft",
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )

    story.updated_at = datetime.utcnow()
    db.commit()
    return await get_story(story_id, db)


async def create_character(
    story_id: str,
    data: StoryCharacterCreate,
    db: Session,
) -> Optional[StoryCharacterResponse]:
    story = db.query(DBStory).filter_by(id=story_id).first()
    if not story:
        return None
    next_index = (
        db.query(func.max(DBStoryCharacter.order_index)).filter_by(story_id=story_id).scalar() or 0
    )
    character = DBStoryCharacter(
        id=str(uuid.uuid4()),
        story_id=story_id,
        name=data.name,
        profile_id=data.profile_id,
        is_narrator=data.is_narrator,
        order_index=next_index,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(character)
    story.updated_at = datetime.utcnow()
    db.commit()
    _ensure_character_order(db, story_id)
    db.commit()
    db.refresh(character)
    return _character_response(character, db)


async def update_character(
    story_id: str,
    character_id: str,
    data: StoryCharacterUpdate,
    db: Session,
) -> Optional[StoryCharacterResponse]:
    character = (
        db.query(DBStoryCharacter)
        .filter_by(id=character_id, story_id=story_id)
        .first()
    )
    if not character:
        return None
    if data.name is not None:
        character.name = data.name
    if data.profile_id is not None:
        character.profile_id = data.profile_id
    if data.is_narrator is not None:
        # Only one narrator — clear the flag from others.
        if data.is_narrator:
            db.query(DBStoryCharacter).filter_by(story_id=story_id, is_narrator=True).update(
                {"is_narrator": False}
            )
        character.is_narrator = data.is_narrator
    character.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(character)
    return _character_response(character, db)


async def delete_character(story_id: str, character_id: str, db: Session) -> bool:
    character = (
        db.query(DBStoryCharacter)
        .filter_by(id=character_id, story_id=story_id)
        .first()
    )
    if not character:
        return False
    # Detach segments that referenced this character.
    db.query(DBStorySegment).filter_by(character_id=character_id).update(
        {"character_id": None}
    )
    db.delete(character)
    db.commit()
    _ensure_character_order(db, story_id)
    db.commit()
    return True


async def create_chapter(
    story_id: str,
    data: StoryChapterCreate,
    db: Session,
) -> Optional[StoryChapterResponse]:
    story = db.query(DBStory).filter_by(id=story_id).first()
    if not story:
        return None
    next_index = db.query(func.max(DBStoryChapter.order_index)).filter_by(story_id=story_id).scalar() or 0
    chapter = DBStoryChapter(
        id=str(uuid.uuid4()),
        story_id=story_id,
        title=data.title,
        order_index=next_index,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(chapter)
    story.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(chapter)
    return _chapter_response(chapter, db)


async def update_chapter(
    story_id: str,
    chapter_id: str,
    data: StoryChapterUpdate,
    db: Session,
) -> Optional[StoryChapterResponse]:
    chapter = (
        db.query(DBStoryChapter).filter_by(id=chapter_id, story_id=story_id).first()
    )
    if not chapter:
        return None
    if data.title is not None:
        chapter.title = data.title
    if data.order_index is not None:
        chapter.order_index = data.order_index
    chapter.updated_at = datetime.utcnow()
    db.commit()
    _ensure_chapter_order(db, story_id)
    db.commit()
    db.refresh(chapter)
    return _chapter_response(chapter, db)


async def delete_chapter(story_id: str, chapter_id: str, db: Session) -> bool:
    chapter = (
        db.query(DBStoryChapter).filter_by(id=chapter_id, story_id=story_id).first()
    )
    if not chapter:
        return False
    db.query(DBStorySegment).filter_by(chapter_id=chapter_id).delete()
    db.delete(chapter)
    db.commit()
    _ensure_chapter_order(db, story_id)
    db.commit()
    return True


async def create_segment(
    story_id: str,
    data: StorySegmentCreate,
    db: Session,
) -> Optional[StorySegmentResponse]:
    chapter = (
        db.query(DBStoryChapter).filter_by(id=data.chapter_id, story_id=story_id).first()
    )
    if not chapter:
        return None
    next_index = (
        db.query(func.max(DBStorySegment.order_index)).filter_by(chapter_id=chapter.id).scalar() or 0
    )
    segment = DBStorySegment(
        id=str(uuid.uuid4()),
        chapter_id=chapter.id,
        order_index=data.order_index if data.order_index is not None else next_index,
        text=data.text,
        profile_id=data.profile_id,
        status="draft",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(segment)
    chapter.updated_at = datetime.utcnow()
    db.commit()
    _ensure_segment_order(db, chapter.id)
    db.commit()
    db.refresh(segment)
    return _segment_response(segment, db)


async def update_segment(
    story_id: str,
    segment_id: str,
    data: StorySegmentUpdate,
    db: Session,
) -> Optional[StorySegmentResponse]:
    segment = (
        db.query(DBStorySegment)
        .join(DBStoryChapter, DBStorySegment.chapter_id == DBStoryChapter.id)
        .filter(
            DBStorySegment.id == segment_id,
            DBStoryChapter.story_id == story_id,
        )
        .first()
    )
    if not segment:
        return None
    if data.text is not None:
        segment.text = data.text
    if data.profile_id is not None:
        segment.profile_id = data.profile_id
    if data.character_id is not None:
        segment.character_id = data.character_id
        # Resolve the voice from the character when one is assigned.
        character = db.query(DBStoryCharacter).filter_by(id=data.character_id).first()
        if character is not None:
            segment.profile_id = character.profile_id
    if data.engine is not None:
        segment.engine = data.engine
    if data.model_size is not None:
        segment.model_size = data.model_size
    if data.language is not None:
        segment.language = data.language
    if data.fade_in_ms is not None:
        segment.fade_in_ms = data.fade_in_ms
    if data.fade_out_ms is not None:
        segment.fade_out_ms = data.fade_out_ms
    # Editing a segment invalidates any completed generation.
    if data.text is not None:
        segment.status = "draft"
    segment.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(segment)
    return _segment_response(segment, db)


async def delete_segment(story_id: str, segment_id: str, db: Session) -> bool:
    segment = (
        db.query(DBStorySegment)
        .join(DBStoryChapter, DBStorySegment.chapter_id == DBStoryChapter.id)
        .filter(
            DBStorySegment.id == segment_id,
            DBStoryChapter.story_id == story_id,
        )
        .first()
    )
    if not segment:
        return False
    chapter_id = segment.chapter_id
    db.delete(segment)
    db.commit()
    _ensure_segment_order(db, chapter_id)
    db.commit()
    return True


async def set_segment_volume(
    story_id: str,
    segment_id: str,
    volume: float,
    db: Session,
) -> Optional[StorySegmentResponse]:
    """Set a segment's clip volume by updating its linked StoryItem.

    The segment's generation is placed on the timeline as a StoryItem, so the
    per-segment volume control updates that clip's linear gain.
    """
    segment = (
        db.query(DBStorySegment)
        .join(DBStoryChapter, DBStorySegment.chapter_id == DBStoryChapter.id)
        .filter(
            DBStorySegment.id == segment_id,
            DBStoryChapter.story_id == story_id,
        )
        .first()
    )
    if not segment:
        return None
    if segment.generation_id:
        item = (
            db.query(DBStoryItem)
            .filter_by(story_id=story_id, generation_id=segment.generation_id)
            .first()
        )
        if item is not None:
            item.volume = max(0.0, min(2.0, volume))
            db.commit()
    segment.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(segment)
    return _segment_response(segment, db)


def _resolve_segment_profile(
    segment: DBStorySegment,
    db: Session,
    override_profile_id: str | None,
) -> Optional[DBVoiceProfile]:
    """Segment voice resolution (spec: characters system).

    Order: request override → the segment's assigned character's voice → the
    segment's own ``profile_id`` → the story's narrator → the story's default
    voice profile.
    """
    if override_profile_id:
        profile = db.query(DBVoiceProfile).filter_by(id=override_profile_id).first()
        if profile:
            return profile

    if getattr(segment, "character_id", None):
        character = db.query(DBStoryCharacter).filter_by(id=segment.character_id).first()
        if character is not None and character.profile_id:
            profile = db.query(DBVoiceProfile).filter_by(id=character.profile_id).first()
            if profile:
                return profile

    if segment.profile_id:
        profile = db.query(DBVoiceProfile).filter_by(id=segment.profile_id).first()
        if profile:
            return profile

    chapter = db.query(DBStoryChapter).filter_by(id=segment.chapter_id).first()
    if chapter is not None:
        story = db.query(DBStory).filter_by(id=chapter.story_id).first()
        if story is not None:
            # Narrator character (is_narrator) first.
            narrator = (
                db.query(DBStoryCharacter)
                .filter_by(story_id=story.id, is_narrator=True)
                .order_by(DBStoryCharacter.order_index)
                .first()
            )
            if narrator is not None and narrator.profile_id:
                profile = db.query(DBVoiceProfile).filter_by(id=narrator.profile_id).first()
                if profile:
                    return profile
            default_id = getattr(story, "default_voice_profile_id", None)
            if default_id:
                profile = db.query(DBVoiceProfile).filter_by(id=default_id).first()
                if profile:
                    return profile
    return None


def _estimate_duration_ms(text: str) -> int:
    """Rough duration estimate for a clip whose generation hasn't completed
    yet. German TTS runs at roughly 14 chars/second, so sequential segment
    items placed at enqueue time (duration still 0 in the DB) would otherwise
    stack on top of each other once their generations finish."""
    if not text:
        return 0
    return int(max(800, (len(text) / 14.0) * 1000))


def _append_segment_story_item(
    db: Session,
    *,
    story_id: str,
    generation_id: str,
    segment_id: str,
    track: int = 0,
) -> DBStoryItem:
    """Append a generation to the story timeline after the current end.

    Mirrors add_item_to_story's auto-placement (max end + 200ms gap) so
    sequentially generated segments line up without overlapping. Clips whose
    generation is still queued have duration 0 in the DB, so an estimate is
    used for them to keep the chain from stacking.
    """
    existing = (
        db.query(DBStoryItem, DBGeneration)
        .join(DBGeneration, DBStoryItem.generation_id == DBGeneration.id)
        .filter(DBStoryItem.story_id == story_id, DBStoryItem.track == track)
        .all()
    )
    if not existing:
        start_time_ms = 0
    else:
        max_end = 0
        for item, gen in existing:
            duration_ms = int((gen.duration or 0) * 1000)
            if duration_ms <= 0:
                duration_ms = _estimate_duration_ms(gen.text)
            max_end = max(max_end, item.start_time_ms + duration_ms)
        start_time_ms = max_end + 200

    item = DBStoryItem(
        id=str(uuid.uuid4()),
        story_id=story_id,
        generation_id=generation_id,
        start_time_ms=start_time_ms,
        track=track,
        story_segment_id=segment_id,
        created_at=datetime.utcnow(),
    )
    db.add(item)
    db.flush()
    return item


async def generate_segment(
    story_id: str,
    segment_id: str,
    data: "StorySegmentGenerateRequest",
    db: Session,
) -> Optional[StorySegmentResponse]:
    """Synthesize one segment: create a Generation, enqueue it, and place a
    StoryItem on the timeline traced back to the segment (spec §4.5/§4.7)."""
    from ..services import history as history_service
    from ..services.task_queue import enqueue_generation
    from ..services.generation import run_generation
    from ..utils.tasks import get_task_manager

    segment = (
        db.query(DBStorySegment)
        .join(DBStoryChapter, DBStorySegment.chapter_id == DBStoryChapter.id)
        .filter(
            DBStorySegment.id == segment_id,
            DBStoryChapter.story_id == story_id,
        )
        .first()
    )
    if not segment:
        return None

    profile = _resolve_segment_profile(segment, db, data.profile_id)
    if profile is None:
        raise ValueError(
            "No voice assigned to this segment. Assign a voice profile to the "
            "segment or the story first."
        )

    engine = (
        segment.engine
        or getattr(profile, "default_engine", None)
        or getattr(profile, "preset_engine", None)
        or "qwen"
    )
    model_size = segment.model_size or "1.7B"
    language = data.language or segment.language or profile.language or "en"

    from ..backends import engine_has_model_sizes

    generation_id = str(uuid.uuid4())
    generation = await history_service.create_generation(
        profile_id=profile.id,
        text=segment.text,
        language=language,
        audio_path="",
        duration=0,
        seed=None,
        db=db,
        generation_id=generation_id,
        status="generating",
        engine=engine,
        model_size=model_size if engine_has_model_sizes(engine) else None,
        source="story_segment",
    )

    task_manager = get_task_manager()
    task_manager.start_generation(generation_id, profile.id, segment.text)

    segment.generation_id = generation_id
    segment.status = "queued"
    segment.updated_at = datetime.utcnow()
    db.commit()

    _append_segment_story_item(
        db,
        story_id=story_id,
        generation_id=generation_id,
        segment_id=segment.id,
    )
    db.commit()

    enqueue_generation(
        generation_id,
        run_generation(
            generation_id=generation_id,
            profile_id=profile.id,
            text=segment.text,
            language=language,
            engine=engine,
            model_size=model_size,
            seed=None,
            normalize=True,
            mode="generate",
            fade_in_ms=segment.fade_in_ms if getattr(segment, "fade_in_ms", 0) else None,
            fade_out_ms=segment.fade_out_ms if getattr(segment, "fade_out_ms", 0) else None,
        ),
    )

    db.refresh(segment)
    return _segment_response(segment, db)


async def generate_many_segments(
    story_id: str,
    data: "StorySegmentsGenerateManyRequest",
    db: Session,
) -> list[StorySegmentResponse]:
    """Enqueue several segments at once (spec §4.7 generate-many, §6 queue)."""
    from ..services.task_queue import enqueue_generation
    from ..services.generation import run_generation
    from ..services import history as history_service
    from ..utils.tasks import get_task_manager
    from ..backends import engine_has_model_sizes

    story = db.query(DBStory).filter_by(id=story_id).first()
    if not story:
        raise ValueError("Story not found")

    segments = (
        db.query(DBStorySegment)
        .join(DBStoryChapter, DBStorySegment.chapter_id == DBStoryChapter.id)
        .filter(
            DBStorySegment.id.in_(data.segment_ids),
            DBStoryChapter.story_id == story_id,
        )
        .order_by(DBStoryChapter.order_index, DBStorySegment.order_index)
        .all()
    )
    found = {s.id for s in segments}
    missing = [sid for sid in data.segment_ids if sid not in found]
    if missing:
        raise ValueError(f"Segments not found in this story: {missing}")

    task_manager = get_task_manager()
    results: list[StorySegmentResponse] = []

    for segment in segments:
        profile = _resolve_segment_profile(segment, db, data.profile_id)
        if profile is None:
            segment.status = "error"
            segment.updated_at = datetime.utcnow()
            db.commit()
            results.append(_segment_response(segment, db))
            continue

        engine = (
            segment.engine
            or getattr(profile, "default_engine", None)
            or getattr(profile, "preset_engine", None)
            or "qwen"
        )
        model_size = segment.model_size or "1.7B"
        language = segment.language or profile.language or "en"

        generation_id = str(uuid.uuid4())
        await history_service.create_generation(
            profile_id=profile.id,
            text=segment.text,
            language=language,
            audio_path="",
            duration=0,
            seed=None,
            db=db,
            generation_id=generation_id,
            status="generating",
            engine=engine,
            model_size=model_size if engine_has_model_sizes(engine) else None,
            source="story_segment",
        )
        task_manager.start_generation(generation_id, profile.id, segment.text)

        segment.generation_id = generation_id
        segment.status = "queued"
        segment.updated_at = datetime.utcnow()
        db.commit()

        _append_segment_story_item(
            db,
            story_id=story_id,
            generation_id=generation_id,
            segment_id=segment.id,
        )
        db.commit()

        enqueue_generation(
            generation_id,
            run_generation(
                generation_id=generation_id,
                profile_id=profile.id,
                text=segment.text,
                language=language,
                engine=engine,
                model_size=model_size,
                seed=None,
                normalize=True,
                mode="generate",
                fade_in_ms=segment.fade_in_ms if getattr(segment, "fade_in_ms", 0) else None,
                fade_out_ms=segment.fade_out_ms if getattr(segment, "fade_out_ms", 0) else None,
            ),
        )
        db.refresh(segment)
        results.append(_segment_response(segment, db))

    story.updated_at = datetime.utcnow()
    db.commit()
    return results


async def reorder_segments(
    story_id: str,
    segment_ids: list[str],
    db: Session,
) -> Optional[list[StorySegmentResponse]]:
    """Re-number segments in document order (spec 2:3 dot-grid drag reorder).

    ``segment_ids`` is the full desired order for one chapter. Re-numbers the
    members 0..n-1 and returns them in order. Returns None if any id is not in
    this story (a malformed request).
    """
    segs = (
        db.query(DBStorySegment)
        .join(DBStoryChapter, DBStorySegment.chapter_id == DBStoryChapter.id)
        .filter(
            DBStorySegment.id.in_(segment_ids),
            DBStoryChapter.story_id == story_id,
        )
        .all()
    )
    found_ids = {s.id for s in segs}
    if len(found_ids) != len(set(segment_ids)):
        return None

    by_id = {s.id: s for s in segs}
    for i, sid in enumerate(segment_ids):
        seg = by_id[sid]
        seg.order_index = i
        seg.updated_at = datetime.utcnow()
    db.commit()

    chapter_id = (db.query(DBStorySegment).filter_by(id=segment_ids[0]).first().chapter_id)
    ordered = sorted(segs, key=lambda s: segment_ids.index(s.id))
    return [_segment_response(s, db) for s in ordered]


async def move_segment(
    story_id: str,
    segment_id: str,
    *,
    to_chapter_id: str,
    db: Session,
) -> Optional[StorySegmentResponse]:
    """Move a segment to another chapter (appended at the end)."""
    segment = (
        db.query(DBStorySegment)
        .join(DBStoryChapter, DBStorySegment.chapter_id == DBStoryChapter.id)
        .filter(
            DBStorySegment.id == segment_id,
            DBStoryChapter.story_id == story_id,
        )
        .first()
    )
    if not segment:
        return None
    target = (
        db.query(DBStoryChapter)
        .filter_by(id=to_chapter_id, story_id=story_id)
        .first()
    )
    if target is None:
        return None

    old_chapter_id = segment.chapter_id
    segment.chapter_id = to_chapter_id
    segment.updated_at = datetime.utcnow()
    db.flush()
    _ensure_segment_order(db, old_chapter_id)
    _ensure_segment_order(db, to_chapter_id)
    db.commit()
    db.refresh(segment)
    return _segment_response(segment, db)
