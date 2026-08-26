"""
Dubbing pipeline service.

Orchestrates the full dubbing flow for a project:
  extract → transcribe (Parakeet/Whisper) → diarize (pyannote) → merge
  → pause-aware segmentation → translate (length-fit) → synthesize per
  speaker (Voicebox TTS engines) → assemble the dubbed track.

Everything reuses existing Voicebox seams: STT backends, diarization backend,
translation backend, the TTS generation service, and SQLAlchemy persistence.
"""

import asyncio
import logging
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from .. import config
from ..database.models import DubbingProject, DubbingSegment, DubbingSpeaker
from ..database.session import SessionLocal
from . import diarization as diarization_service, segmentation, translation as translation_service

logger = logging.getLogger(__name__)

SAMPLE_RATE = 44100


# ---------------------------------------------------------------------------
# Project / segment persistence
# ---------------------------------------------------------------------------

def _storage_dir(project_id: str) -> Path:
    path = config.get_data_dir() / "dubbing" / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_project(
    *,
    name: str,
    source_language: str,
    target_language: str,
    source_path: str,
    stt_engine: str = "parakeet",
    translation_style: str = "Natural",
    duration: float = 0.0,
) -> DubbingProject:
    db = SessionLocal()
    try:
        project = DubbingProject(
            name=name,
            source_language=source_language,
            target_language=target_language,
            source_path=source_path,
            stt_engine=stt_engine,
            translation_style=translation_style,
            duration=duration,
            status="draft",
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        return project
    finally:
        db.close()


def get_project(project_id: str) -> DubbingProject | None:
    db = SessionLocal()
    try:
        return db.query(DubbingProject).filter_by(id=project_id).first()
    finally:
        db.close()


def list_projects() -> list[dict]:
    db = SessionLocal()
    try:
        rows = db.query(DubbingProject).order_by(DubbingProject.created_at.desc()).all()
        out = []
        for p in rows:
            seg_count = (
                db.query(DubbingSegment).filter_by(project_id=p.id).count()
            )
            d = project_dict(p)
            d["segment_count"] = seg_count
            d["speakers"] = speakers_dict(db, p.id)
            out.append(d)
        return out
    finally:
        db.close()


def project_dict(p: DubbingProject) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "status": p.status,
        "stage": p.stage,
        "source_language": p.source_language,
        "target_language": p.target_language,
        "duration": p.duration,
        "translation_style": p.translation_style,
        "stt_engine": p.stt_engine,
        "error": p.error,
        "dubbed_audio_path": p.dubbed_audio_path,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def speakers_dict(db: Session, project_id: str) -> list[dict]:
    return [
        {
            "id": s.id,
            "label": s.label,
            "voice_profile_id": s.voice_profile_id,
            "preset_engine": s.preset_engine,
            "preset_voice_id": s.preset_voice_id,
        }
        for s in db.query(DubbingSpeaker).filter_by(project_id=project_id).all()
    ]


def set_project_status(db: Session, project_id: str, status: str, stage: str | None = None) -> None:
    p = db.query(DubbingProject).filter_by(id=project_id).first()
    if p is None:
        return
    p.status = status
    if stage is not None:
        p.stage = stage
    db.commit()
    logger.info("dubbing %s → %s (%s)", project_id, status, stage)


def list_segments(project_id: str) -> list[dict]:
    db = SessionLocal()
    try:
        rows = (
            db.query(DubbingSegment)
            .filter_by(project_id=project_id)
            .order_by(DubbingSegment.sequence_index.asc())
            .all()
        )
        return [_segment_dict(s) for s in rows]
    finally:
        db.close()


def _segment_dict(s: DubbingSegment) -> dict:
    return {
        "id": s.id,
        "project_id": s.project_id,
        "speaker_id": s.speaker_id,
        "sequence_index": s.sequence_index,
        "start_time": s.start_time,
        "end_time": s.end_time,
        "duration": s.duration,
        "source_text": s.source_text,
        "translated_text": s.translated_text,
        "target_char_min": s.target_char_min,
        "target_char_max": s.target_char_max,
        "pace_multiplier": s.pace_multiplier,
        "alignment": s.alignment,
        "auto_stretch": s.auto_stretch,
        "is_locked": s.is_locked,
        "synthesized_audio_path": s.synthesized_audio_path,
        "is_dirty": s.is_dirty,
    }


def update_segment(
    segment_id: str,
    *,
    translated_text: str | None = None,
    alignment: str | None = None,
    pace_multiplier: float | None = None,
    auto_stretch: bool | None = None,
    is_locked: bool | None = None,
    speaker_id: str | None = None,
) -> dict | None:
    db = SessionLocal()
    try:
        seg = db.query(DubbingSegment).filter_by(id=segment_id).first()
        if seg is None:
            return None
        if translated_text is not None:
            seg.translated_text = translated_text
            seg.is_dirty = True
        if alignment is not None:
            seg.alignment = alignment
            seg.is_dirty = True
        if pace_multiplier is not None:
            seg.pace_multiplier = pace_multiplier
            seg.is_dirty = True
        if auto_stretch is not None:
            seg.auto_stretch = auto_stretch
            seg.is_dirty = True
        if is_locked is not None:
            seg.is_locked = is_locked
        if speaker_id is not None:
            seg.speaker_id = speaker_id
        db.commit()
        db.refresh(seg)
        return _segment_dict(seg)
    finally:
        db.close()


async def resynthesize_segment(segment_id: str) -> dict | None:
    """Re-run TTS for a single segment using its current translated text."""
    db = SessionLocal()
    try:
        seg = db.query(DubbingSegment).filter_by(id=segment_id).first()
        if seg is None:
            return None
        project = db.query(DubbingProject).filter_by(id=seg.project_id).first()
        if project is None:
            return None
        storage = _storage_dir(project.id)
        seg_dir = storage / "segments"
        seg_dir.mkdir(parents=True, exist_ok=True)
        wav_path = seg_dir / f"seg_{seg.sequence_index:03d}.wav"
        await _synthesize_segment(seg, str(wav_path), storage)
        seg.synthesized_audio_path = str(wav_path.relative_to(config.get_data_dir()))
        seg.is_dirty = False
        db.commit()
        db.refresh(seg)
        return _segment_dict(seg)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

async def run_pipeline(project_id: str) -> None:
    """Run the full dubbing pipeline for a project (background task)."""
    db = SessionLocal()
    try:
        project = db.query(DubbingProject).filter_by(id=project_id).first()
        if project is None:
            logger.error("run_pipeline: unknown project %s", project_id)
            return
        storage = _storage_dir(project_id)

        set_project_status(db, project_id, "processing", "extract")

        # 1. EXTRACT — normalize source media to mono 16k WAV.
        source = project.source_path
        master_wav = storage / "master_16k.wav"
        if source and Path(source).exists():
            await _extract_audio(source, str(master_wav))
        else:
            raise RuntimeError(f"Source media missing: {source}")

        set_project_status(db, project_id, "processing", "transcribe")

        # 2. TRANSCRIBE — word-timestamped segments (Parakeet / Whisper).
        from ..services import transcribe

        if project.stt_engine == "parakeet":
            backend = transcribe.get_parakeet_model()
            await backend.load_model_async("v3-0.6b")
            raw = await backend.transcribe_segments(
                str(master_wav), language=project.source_language, model_size="v3-0.6b"
            )
        else:
            backend = transcribe.get_whisper_model()
            await backend.load_model_async("turbo")
            text = await backend.transcribe(
                str(master_wav), language=project.source_language, model_size="turbo"
            )
            raw = [{"text": text, "start": 0.0, "end": project.duration or 1.0, "words": []}]

        set_project_status(db, project_id, "processing", "diarize")

        # 3. DIARIZE + MERGE — assign speaker ids to segments.
        turns = []
        try:
            diar = diarization_service.get_diarization_model()
            await diar.load_model("3.1")
            turns = await diar.diarize(str(master_wav))
        except Exception as e:
            logger.warning("Diarization skipped for %s: %s", project_id, e)
            turns = []

        merged = diarization_service.merge_speakers_into_segments(raw, turns)

        # 4. SEGMENT — pause-aware grouping + char budgets.
        set_project_status(db, project_id, "processing", "segment")
        segments = segmentation.build_pause_aware_segments(
            merged, target_lang=project.target_language
        )

        # 5. PERSIST default speakers + segments.
        await _persist_project_artifacts(db, project_id, project, segments, turns)

        set_project_status(db, project_id, "processing", "translate")

        # 6. TRANSLATE (length-fit) + 7. SYNTHESIZE per segment.
        await _translate_and_synthesize(db, project_id, storage)

        # 8. ASSEMBLE the dubbed track.
        set_project_status(db, project_id, "processing", "assemble")
        dubbed_path = await _assemble_track(db, project_id, storage)

        project = db.query(DubbingProject).filter_by(id=project_id).first()
        project.dubbed_audio_path = str(dubbed_path.relative_to(config.get_data_dir()))
        project.status = "ready"
        project.stage = None
        project.error = None
        db.commit()
        logger.info("Dubbing pipeline complete: %s", project_id)

    except Exception as e:
        logger.exception("Dubbing pipeline failed for %s", project_id)
        set_project_status(db, project_id, "failed", "failed")
        p = db.query(DubbingProject).filter_by(id=project_id).first()
        if p is not None:
            p.error = str(e)
            db.commit()
    finally:
        db.close()


async def _extract_audio(source: str, out_wav: str) -> None:
    """Read media → mono 16k float WAV via librosa (broad container support)."""
    from ..utils.audio import load_audio, save_audio

    audio, sr = await asyncio.to_thread(load_audio, source)
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    await asyncio.to_thread(save_audio, audio, out_wav, sr)


async def _persist_project_artifacts(
    db: Session,
    project_id: str,
    project: DubbingProject,
    segments: list[dict],
    turns: list[dict],
) -> None:
    """Create speaker rows (per diarization turn) and segment rows."""
    # Clean previous run (idempotent re-runs).
    db.query(DubbingSegment).filter_by(project_id=project_id).delete()
    db.query(DubbingSpeaker).filter_by(project_id=project_id).delete()

    speaker_ids: dict[str, str] = {}
    for turn in turns:
        label = turn["speaker_id"]
        if label in speaker_ids:
            continue
        spk = DubbingSpeaker(project_id=project_id, label=label)
        db.add(spk)
        db.flush()
        speaker_ids[label] = spk.id

    for seg in segments:
        spk_label = seg.get("speaker_id")
        row = DubbingSegment(
            project_id=project_id,
            speaker_id=speaker_ids.get(spk_label),
            sequence_index=seg["sequence_index"],
            start_time=seg["start_time"],
            end_time=seg["end_time"],
            duration=seg["duration"],
            source_text=seg["source_text"],
            target_char_min=seg["target_char_min"],
            target_char_max=seg["target_char_max"],
            is_dirty=True,
        )
        db.add(row)
    db.commit()


async def _translate_and_synthesize(db: Session, project_id: str, storage: Path) -> None:
    """Translate + TTS each dirty segment, writing per-segment WAVs."""
    project = db.query(DubbingProject).filter_by(id=project_id).first()
    if project is None:
        return
    rows = (
        db.query(DubbingSegment)
        .filter_by(project_id=project_id)
        .order_by(DubbingSegment.sequence_index.asc())
        .all()
    )
    seg_dir = storage / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)

    for seg in rows:
        if seg.is_locked and seg.synthesized_audio_path:
            continue  # keep the locked version intact

        if seg.is_dirty or not seg.translated_text:
            seg.translated_text = await translation_service.translate_and_fit(
                text=seg.source_text,
                source_lang=project.source_language,
                target_lang=project.target_language,
                max_chars=seg.target_char_max,
                min_chars=seg.target_char_min,
                tone=project.translation_style or "Natural",
            )
            seg.is_dirty = True

        # Synthesize with the assigned voice profile (or the platform default).
        wav_path = seg_dir / f"seg_{seg.sequence_index:03d}.wav"
        try:
            await _synthesize_segment(seg, str(wav_path), storage)
            seg.synthesized_audio_path = str(wav_path.relative_to(config.get_data_dir()))
            seg.is_dirty = False
            db.commit()
        except Exception as e:
            logger.warning("Segment %s synthesis failed: %s", seg.id, e)
            seg.synthesized_audio_path = None
            seg.is_dirty = True
            db.commit()


async def _synthesize_segment(seg: DubbingSegment, out_path: str, storage: Path) -> None:
    """Generate the dubbed audio for one segment via the TTS engine."""
    from ..services import generation

    if not seg.translated_text:
        raise RuntimeError("No translated text for segment")

    # Resolve the voice: speaker mapping → profile → default profile id.
    voice_profile_id = None
    db = SessionLocal()
    try:
        if seg.speaker_id:
            spk = db.query(DubbingSpeaker).filter_by(id=seg.speaker_id).first()
            if spk and spk.voice_profile_id:
                voice_profile_id = spk.voice_profile_id
    finally:
        db.close()

    if not voice_profile_id:
        voice_profile_id = await _find_default_profile()

    wav_bytes = await generation.generate_audio_sync(
        profile_id=voice_profile_id,
        text=seg.translated_text,
        language="en",  # engine-language hint; engines auto-detect target lang
        engine="kokoro",  # lightweight default; override via speaker mapping later
        model_size="default",
        normalize=True,
    )

    Path(out_path).write_bytes(wav_bytes)


async def _find_default_profile() -> str:
    """Return an existing voice-profile id for synthesis (first available)."""
    from ..services import profiles

    db = SessionLocal()
    try:
        resp = await profiles.list_profiles(db)
    finally:
        db.close()
    if resp:
        return resp[0].id
    raise RuntimeError(
        "No voice profile exists. Create a voice profile first (Voices tab) "
        "or assign one per speaker in the Dubbing Studio."
    )


async def _assemble_track(db: Session, project_id: str, storage: Path) -> Path:
    """Place each segment's WAV on the master canvas (start|center|end)."""
    rows = (
        db.query(DubbingSegment)
        .filter_by(project_id=project_id)
        .order_by(DubbingSegment.sequence_index.asc())
        .all()
    )
    project = db.query(DubbingProject).filter_by(id=project_id).first()
    total_samples = max(1, int(SAMPLE_RATE * (project.duration or 0.0)))
    canvas = np.zeros(total_samples, dtype=np.float32)

    for seg in rows:
        if not seg.synthesized_audio_path:
            continue
        seg_path = config.resolve_storage_path(seg.synthesized_audio_path)
        if seg_path is None or not seg_path.exists():
            continue
        import soundfile as sf

        audio, sr = sf.read(str(seg_path), dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr != SAMPLE_RATE:
            # Basic resample to the canvas rate.
            n = int(len(audio) * SAMPLE_RATE / sr)
            audio = np.interp(
                np.linspace(0, 1, n),
                np.linspace(0, 1, len(audio)),
                audio,
            ).astype(np.float32)

        start_sample = int(seg.start_time * SAMPLE_RATE)
        seg_samples = len(audio)
        end_sample = min(total_samples, seg_samples + start_sample)
        canvas[start_sample:end_sample] += audio[: end_sample - start_sample]

    out_path = storage / "dubbed_master.wav"
    import soundfile as sf

    sf.write(str(out_path), canvas, SAMPLE_RATE)
    return out_path
