"""Story endpoints."""

import io

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import database, models
from ..services import stories
from ..app import safe_content_disposition
from ..database import get_db

router = APIRouter()


@router.get("/stories", response_model=list[models.StoryResponse])
async def list_stories(db: Session = Depends(get_db)):
    """List all stories."""
    return await stories.list_stories(db)


@router.post("/stories", response_model=models.StoryResponse)
async def create_story(
    data: models.StoryCreate,
    db: Session = Depends(get_db),
):
    """Create a new story."""
    try:
        return await stories.create_story(data, db)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/stories/{story_id}", response_model=models.StoryDetailResponse)
async def get_story(
    story_id: str,
    db: Session = Depends(get_db),
):
    """Get a story with all its items."""
    story = await stories.get_story(story_id, db)
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")
    return story


@router.put("/stories/{story_id}", response_model=models.StoryResponse)
async def update_story(
    story_id: str,
    data: models.StoryCreate,
    db: Session = Depends(get_db),
):
    """Update a story."""
    story = await stories.update_story(story_id, data, db)
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")
    return story


@router.delete("/stories/{story_id}")
async def delete_story(
    story_id: str,
    db: Session = Depends(get_db),
):
    """Delete a story."""
    success = await stories.delete_story(story_id, db)
    if not success:
        raise HTTPException(status_code=404, detail="Story not found")
    return {"message": "Story deleted successfully"}


@router.post("/stories/{story_id}/items", response_model=models.StoryItemDetail)
async def add_story_item(
    story_id: str,
    data: models.StoryItemCreate,
    db: Session = Depends(get_db),
):
    """Add a generation to a story."""
    item = await stories.add_item_to_story(story_id, data, db)
    if not item:
        raise HTTPException(status_code=404, detail="Story or generation not found")
    return item


@router.delete("/stories/{story_id}/items/{item_id}")
async def remove_story_item(
    story_id: str,
    item_id: str,
    db: Session = Depends(get_db),
):
    """Remove a story item from a story."""
    success = await stories.remove_item_from_story(story_id, item_id, db)
    if not success:
        raise HTTPException(status_code=404, detail="Story item not found")
    return {"message": "Item removed successfully"}


@router.put("/stories/{story_id}/items/times")
async def update_story_item_times(
    story_id: str,
    data: models.StoryItemBatchUpdate,
    db: Session = Depends(get_db),
):
    """Update story item timecodes."""
    success = await stories.update_story_item_times(story_id, data, db)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid timecode update request")
    return {"message": "Item timecodes updated successfully"}


@router.put("/stories/{story_id}/items/reorder", response_model=list[models.StoryItemDetail])
async def reorder_story_items(
    story_id: str,
    data: models.StoryItemReorder,
    db: Session = Depends(get_db),
):
    """Reorder story items and recalculate timecodes."""
    items = await stories.reorder_story_items(story_id, data.generation_ids, db)
    if items is None:
        raise HTTPException(
            status_code=400, detail="Invalid reorder request - ensure all generation IDs belong to this story"
        )
    return items


@router.put("/stories/{story_id}/items/{item_id}/move", response_model=models.StoryItemDetail)
async def move_story_item(
    story_id: str,
    item_id: str,
    data: models.StoryItemMove,
    db: Session = Depends(get_db),
):
    """Move a story item (update position and/or track)."""
    item = await stories.move_story_item(story_id, item_id, data, db)
    if item is None:
        raise HTTPException(status_code=404, detail="Story item not found")
    return item


@router.put("/stories/{story_id}/items/{item_id}/trim", response_model=models.StoryItemDetail)
async def trim_story_item(
    story_id: str,
    item_id: str,
    data: models.StoryItemTrim,
    db: Session = Depends(get_db),
):
    """Trim a story item."""
    item = await stories.trim_story_item(story_id, item_id, data, db)
    if item is None:
        raise HTTPException(status_code=404, detail="Story item not found or invalid trim values")
    return item


@router.put("/stories/{story_id}/items/{item_id}/volume", response_model=models.StoryItemDetail)
async def update_story_item_volume(
    story_id: str,
    item_id: str,
    data: models.StoryItemVolumeUpdate,
    db: Session = Depends(get_db),
):
    """Set a story item's per-clip volume (linear gain, 0.0–2.0)."""
    item = await stories.update_story_item_volume(story_id, item_id, data, db)
    if item is None:
        raise HTTPException(status_code=404, detail="Story item not found")
    return item


@router.post("/stories/{story_id}/items/{item_id}/split", response_model=list[models.StoryItemDetail])
async def split_story_item(
    story_id: str,
    item_id: str,
    data: models.StoryItemSplit,
    db: Session = Depends(get_db),
):
    """Split a story item at a given time, creating two clips."""
    items = await stories.split_story_item(story_id, item_id, data, db)
    if items is None:
        raise HTTPException(status_code=404, detail="Story item not found or invalid split point")
    return items


@router.post("/stories/{story_id}/items/{item_id}/duplicate", response_model=models.StoryItemDetail)
async def duplicate_story_item(
    story_id: str,
    item_id: str,
    db: Session = Depends(get_db),
):
    """Duplicate a story item."""
    item = await stories.duplicate_story_item(story_id, item_id, db)
    if item is None:
        raise HTTPException(status_code=404, detail="Story item not found")
    return item


@router.put("/stories/{story_id}/items/{item_id}/version", response_model=models.StoryItemDetail)
async def set_story_item_version(
    story_id: str,
    item_id: str,
    data: models.StoryItemVersionUpdate,
    db: Session = Depends(get_db),
):
    """Pin a story item to a specific generation version."""
    item = await stories.set_story_item_version(story_id, item_id, data, db)
    if item is None:
        raise HTTPException(status_code=404, detail="Story item or version not found")
    return item


@router.get("/stories/{story_id}/export-audio")
async def export_story_audio(
    story_id: str,
    format: str = Query("wav", pattern="^(wav|mp3)$"),
    scope: str = Query("all", pattern="^(all|chapters)$"),
    db: Session = Depends(get_db),
):
    """Export story as a mixed audio file (``format``=wav|mp3). Pass
    ``scope=chapters`` to get a ZIP with one file per chapter."""
    try:
        story = db.query(database.Story).filter_by(id=story_id).first()
        if not story:
            raise HTTPException(status_code=404, detail="Story not found")

        audio_bytes = await stories.export_story_audio(story_id, db, fmt=format, scope=scope)
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Story has no audio items")

        safe_name = "".join(c for c in story.name if c.isalnum() or c in (" ", "-", "_")).strip()
        if not safe_name:
            safe_name = "story"

        if scope == "chapters":
            filename = f"{safe_name}-chapters.zip"
            media_type = "application/zip"
        else:
            ext = "mp3" if format == "mp3" else "wav"
            filename = f"{safe_name}.{ext}"
            media_type = "audio/mpeg" if format == "mp3" else "audio/wav"

        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type=media_type,
            headers={"Content-Disposition": safe_content_disposition("attachment", filename)},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Chapters / segments / markdown import (spec §4) ────────────────────────


@router.post("/stories/{story_id}/import-markdown", response_model=models.MarkdownImportPreview)
async def import_markdown_preview(
    story_id: str,
    data: models.MarkdownImportRequest,
    db: Session = Depends(get_db),
):
    """Preview how a markdown script splits into chapters/segments (spec §4.3).

    Nothing is written — the client shows the preview and POSTs the approved
    segmentation to ``/import-markdown/commit``.
    """
    story = db.query(database.Story).filter_by(id=story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")
    try:
        return stories.import_markdown_preview(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/stories/{story_id}/import-markdown/commit",
    response_model=models.StoryDetailResponse,
)
async def commit_markdown_import(
    story_id: str,
    data: models.MarkdownImportCommitRequest,
    db: Session = Depends(get_db),
):
    """Persist an approved segmentation as chapters + segments."""
    result = await stories.commit_markdown_import(story_id, data, db)
    if result is None:
        raise HTTPException(status_code=404, detail="Story not found")
    return result


@router.post("/stories/{story_id}/chapters", response_model=models.StoryChapterResponse)
async def create_story_chapter(
    story_id: str,
    data: models.StoryChapterCreate,
    db: Session = Depends(get_db),
):
    """Create a chapter."""
    chapter = await stories.create_chapter(story_id, data, db)
    if chapter is None:
        raise HTTPException(status_code=404, detail="Story not found")
    return chapter


@router.put(
    "/stories/{story_id}/chapters/{chapter_id}",
    response_model=models.StoryChapterResponse,
)
async def update_story_chapter(
    story_id: str,
    chapter_id: str,
    data: models.StoryChapterUpdate,
    db: Session = Depends(get_db),
):
    """Rename / reorder a chapter."""
    chapter = await stories.update_chapter(story_id, chapter_id, data, db)
    if chapter is None:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return chapter


@router.delete("/stories/{story_id}/chapters/{chapter_id}")
async def delete_story_chapter(
    story_id: str,
    chapter_id: str,
    db: Session = Depends(get_db),
):
    """Delete a chapter and its segments."""
    success = await stories.delete_chapter(story_id, chapter_id, db)
    if not success:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return {"message": "Chapter deleted successfully"}


@router.post("/stories/{story_id}/segments", response_model=models.StorySegmentResponse)
async def create_story_segment(
    story_id: str,
    data: models.StorySegmentCreate,
    db: Session = Depends(get_db),
):
    """Create a segment in a chapter."""
    segment = await stories.create_segment(story_id, data, db)
    if segment is None:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return segment


@router.put(
    "/stories/{story_id}/segments/{segment_id}",
    response_model=models.StorySegmentResponse,
)
async def update_story_segment(
    story_id: str,
    segment_id: str,
    data: models.StorySegmentUpdate,
    db: Session = Depends(get_db),
):
    """Edit a segment (text / speaker / engine / fades)."""
    segment = await stories.update_segment(story_id, segment_id, data, db)
    if segment is None:
        raise HTTPException(status_code=404, detail="Segment not found")
    return segment


@router.put(
    "/stories/{story_id}/segments/{segment_id}/volume",
    response_model=models.StorySegmentResponse,
)
async def set_story_segment_volume(
    story_id: str,
    segment_id: str,
    data: models.StorySegmentVolumeUpdate,
    db: Session = Depends(get_db),
):
    """Set a segment's clip volume (updates its timeline item)."""
    segment = await stories.set_segment_volume(story_id, segment_id, data.volume, db)
    if segment is None:
        raise HTTPException(status_code=404, detail="Segment not found")
    return segment


@router.put(
    "/stories/{story_id}/segments/order",
    response_model=list[models.StorySegmentResponse],
)
async def reorder_story_segments(
    story_id: str,
    data: models.StorySegmentReorder,
    db: Session = Depends(get_db),
):
    """Re-number segments in document order (drag-and-drop reorder, spec)."""
    result = await stories.reorder_segments(story_id, data.segment_ids, db)
    if result is None:
        raise HTTPException(status_code=400, detail="Invalid reorder request")
    return result


@router.put(
    "/stories/{story_id}/segments/{segment_id}/move",
    response_model=models.StorySegmentResponse,
)
async def move_story_segment_to_chapter(
    story_id: str,
    segment_id: str,
    data: models.StorySegmentMove,
    db: Session = Depends(get_db),
):
    """Move a segment to another chapter."""
    segment = await stories.move_segment(story_id, segment_id, to_chapter_id=data.chapter_id, db=db)
    if segment is None:
        raise HTTPException(status_code=404, detail="Segment or chapter not found")
    return segment


@router.delete("/stories/{story_id}/segments/{segment_id}")
async def delete_story_segment(
    story_id: str,
    segment_id: str,
    db: Session = Depends(get_db),
):
    """Delete a segment."""
    success = await stories.delete_segment(story_id, segment_id, db)
    if not success:
        raise HTTPException(status_code=404, detail="Segment not found")
    return {"message": "Segment deleted successfully"}


@router.post(
    "/stories/{story_id}/segments/{segment_id}/generate",
    response_model=models.StorySegmentResponse,
)
async def generate_story_segment(
    story_id: str,
    segment_id: str,
    data: models.StorySegmentGenerateRequest,
    db: Session = Depends(get_db),
):
    """Synthesize one segment (queued, spec §4.7 + §6)."""
    try:
        segment = await stories.generate_segment(story_id, segment_id, data, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if segment is None:
        raise HTTPException(status_code=404, detail="Segment not found")
    return segment


@router.post(
    "/stories/{story_id}/segments/generate-many",
    response_model=list[models.StorySegmentResponse],
)
async def generate_many_story_segments(
    story_id: str,
    data: models.StorySegmentsGenerateManyRequest,
    db: Session = Depends(get_db),
):
    """Synthesize several segments at once, queued in document order (§6)."""
    try:
        return await stories.generate_many_segments(story_id, data, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Characters / speakers (spec: project tab) ──────────────────────────────


@router.post("/stories/{story_id}/characters", response_model=models.StoryCharacterResponse)
async def create_story_character(
    story_id: str,
    data: models.StoryCharacterCreate,
    db: Session = Depends(get_db),
):
    """Add a named character (speaker) to a project."""
    character = await stories.create_character(story_id, data, db)
    if character is None:
        raise HTTPException(status_code=404, detail="Story not found")
    return character


@router.put(
    "/stories/{story_id}/characters/{character_id}",
    response_model=models.StoryCharacterResponse,
)
async def update_story_character(
    story_id: str,
    character_id: str,
    data: models.StoryCharacterUpdate,
    db: Session = Depends(get_db),
):
    """Update a character's name / voice / narrator flag."""
    character = await stories.update_character(story_id, character_id, data, db)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    return character


@router.delete("/stories/{story_id}/characters/{character_id}")
async def delete_story_character(
    story_id: str,
    character_id: str,
    db: Session = Depends(get_db),
):
    """Delete a character (segments fall back to the narrator)."""
    success = await stories.delete_character(story_id, character_id, db)
    if not success:
        raise HTTPException(status_code=404, detail="Character not found")
    return {"message": "Character deleted successfully"}
