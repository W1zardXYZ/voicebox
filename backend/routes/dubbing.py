"""Dubbing Studio endpoints.

Create dubbing projects from a media upload, run the full pipeline in the
background, inspect/edit segments, re-synthesize individual segments, and
fetch the assembled dubbed audio.
"""

import asyncio
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .. import config, models
from ..database import session as db_session
from ..database.models import DubbingProject
from ..services import dubbing
from ..services.task_queue import create_background_task

router = APIRouter()

UPLOAD_CHUNK_SIZE = 4 * 1024 * 1024  # 4MB

ALLOWED_MEDIA_EXTS = {
    ".wav",
    ".mp3",
    ".m4a",
    ".ogg",
    ".flac",
    ".aac",
    ".webm",
    ".opus",
    ".mp4",
    ".mov",
    ".mkv",
}


@router.post("/dubbing/projects", response_model=models.DubbingProjectResponse)
async def create_dubbing_project(
    file: UploadFile = File(...),
    name: str | None = Form(None),
    source_language: str = Form("en"),
    target_language: str = Form("en"),
    stt_engine: str = Form("parakeet"),
    translation_style: str = Form("Natural"),
):
    """Upload a media file and create a dubbing project."""
    if stt_engine not in ("whisper", "parakeet"):
        raise HTTPException(status_code=400, detail="stt_engine must be 'whisper' or 'parakeet'")

    uploaded_ext = Path(file.filename or "").suffix.lower()
    if uploaded_ext not in ALLOWED_MEDIA_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {uploaded_ext}")

    project = dubbing.create_project(
        name=name or file.filename or "Untitled dubbing project",
        source_language=source_language,
        target_language=target_language,
        source_path="",
        stt_engine=stt_engine,
        translation_style=translation_style,
    )

    # Persist the upload into the project dir, get its duration.
    storage = config.get_data_dir() / "dubbing" / project.id
    storage.mkdir(parents=True, exist_ok=True)
    dest = storage / f"source{uploaded_ext}"
    with open(dest, "wb") as out:
        while chunk := await file.read(UPLOAD_CHUNK_SIZE):
            out.write(chunk)

    duration = 0.0
    try:
        from ..utils.audio import load_audio

        audio, sr = await asyncio.to_thread(load_audio, str(dest))
        duration = len(audio) / sr
    except Exception:
        duration = 0.0

    db = db_session.SessionLocal()
    try:
        p = db.query(DubbingProject).filter_by(id=project.id).first()
        p.source_path = str(dest)
        p.duration = duration
        db.commit()
        db.refresh(p)
        resp = dubbing.project_dict(p)
    finally:
        db.close()

    resp["segment_count"] = 0
    resp["speakers"] = []
    return resp


@router.get("/dubbing/projects", response_model=list[models.DubbingProjectResponse])
async def list_dubbing_projects():
    """List dubbing projects with speaker/segment counts."""
    return dubbing.list_projects()


@router.get("/dubbing/projects/{project_id}", response_model=models.DubbingProjectResponse)
async def get_dubbing_project(project_id: str):
    """Get a single dubbing project."""
    project = dubbing.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    db = db_session.SessionLocal()
    try:
        seg_count = db.query(dubbing.DubbingSegment).filter_by(project_id=project_id).count()
        resp = dubbing.project_dict(project)
        resp["segment_count"] = seg_count
        resp["speakers"] = dubbing.speakers_dict(db, project_id)
    finally:
        db.close()
    return resp


@router.post("/dubbing/projects/{project_id}/run")
async def run_dubbing_pipeline(project_id: str):
    """Start the dubbing pipeline (transcribe → diarize → segment → translate → synth → assemble)."""
    project = dubbing.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    create_background_task(dubbing.run_pipeline(project_id))
    return {"success": True, "message": "Dubbing pipeline started"}


@router.get("/dubbing/projects/{project_id}/segments", response_model=list[models.DubbingSegmentResponse])
async def list_dubbing_segments(project_id: str):
    """List all segments of a project (ordered by sequence)."""
    project = dubbing.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return dubbing.list_segments(project_id)


@router.patch("/dubbing/segments/{segment_id}", response_model=models.DubbingSegmentResponse)
async def update_dubbing_segment(segment_id: str, req: models.DubbingSegmentUpdate):
    """Edit a segment (translated text, alignment, lock, pace, speaker)."""
    seg = dubbing.update_segment(
        segment_id,
        translated_text=req.translated_text,
        alignment=req.alignment,
        pace_multiplier=req.pace_multiplier,
        auto_stretch=req.auto_stretch,
        is_locked=req.is_locked,
        speaker_id=req.speaker_id,
    )
    if seg is None:
        raise HTTPException(status_code=404, detail="Segment not found")
    return seg


@router.post("/dubbing/segments/{segment_id}/resynthesize", response_model=models.DubbingSegmentResponse)
async def resynthesize_dubbing_segment(segment_id: str):
    """Re-run TTS for one segment with its current translated text."""
    seg = await dubbing.resynthesize_segment(segment_id)
    if seg is None:
        raise HTTPException(status_code=404, detail="Segment not found")
    return seg


@router.get("/dubbing/audio/{project_id}")
async def get_dubbed_audio(project_id: str):
    """Serve the assembled dubbed track."""
    project = dubbing.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    path = config.resolve_storage_path(project.dubbed_audio_path)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Dubbed audio not ready")
    return FileResponse(str(path), media_type="audio/wav")


@router.post("/dubbing/projects/{project_id}/export")
async def export_dubbed_video(project_id: str):
    """Mux dubbed audio back onto the original video and return the path."""
    project = dubbing.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status != "ready":
        raise HTTPException(status_code=400, detail="Project must be ready before export")
    try:
        out = await dubbing.export_video(project_id)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    if out is None:
        raise HTTPException(status_code=400, detail="Dubbed audio not available")
    return {"success": True, "video_path": str(out.relative_to(config.get_data_dir()))}


@router.get("/dubbing/video/{project_id}")
async def get_dubbed_video(project_id: str):
    """Serve the exported dubbed video (MP4)."""
    project = dubbing.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    path = config.resolve_storage_path(project.dubbed_video_path)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Dubbed video not ready")
    return FileResponse(str(path), media_type="video/mp4")
