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
from ..database import session as db_session
from ..database.models import DubbingProject, DubbingSegment, DubbingSpeaker, VoiceProfile
from . import diarization as diarization_service, segmentation, translation as translation_service

logger = logging.getLogger(__name__)

SAMPLE_RATE = 44100


def _session():
    """Return a live DB session (resolved at call time so the post-init
    ``SessionLocal`` global is used — importing it at module load would
    capture ``None`` before ``init_db()`` runs)."""
    return db_session.SessionLocal()


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
    stt_engine: str = "whisper",
    translation_style: str = "Natural",
    duration: float = 0.0,
) -> DubbingProject:
    db = _session()
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
    db = _session()
    try:
        return db.query(DubbingProject).filter_by(id=project_id).first()
    finally:
        db.close()


def list_projects() -> list[dict]:
    db = _session()
    try:
        rows = db.query(DubbingProject).order_by(DubbingProject.created_at.desc()).all()
        out = []
        for p in rows:
            seg_count = db.query(DubbingSegment).filter_by(project_id=p.id).count()
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
        "dubbed_video_path": p.dubbed_video_path,
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
    db = _session()
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
    db = _session()
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
    db = _session()
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
    db = _session()
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

        # Graceful fallback: if Parakeet/nemo is unavailable, drop to Whisper.
        backend, resolved_engine = transcribe.resolve_stt_backend(project.stt_engine)
        if resolved_engine == "parakeet":
            await backend.load_model_async("v3-0.6b")
            raw = await backend.transcribe_segments(
                str(master_wav), language=project.source_language, model_size="v3-0.6b"
            )
        else:
            await backend.load_model_async("turbo")
            text = await backend.transcribe(str(master_wav), language=project.source_language, model_size="turbo")
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
        segments = segmentation.build_pause_aware_segments(merged, target_lang=project.target_language)

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
    rows = db.query(DubbingSegment).filter_by(project_id=project_id).order_by(DubbingSegment.sequence_index.asc()).all()
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
    """Generate the dubbed audio for one segment via the TTS engine.

    Reuse-friendly (m04): the engine is resolved from the selected voice
    profile (default_engine / preset engine) and falls back to ``qwen`` —
    which is the already-cached Qwen3-TTS on the machine — instead of a
    hardcoded engine that would force a fresh download.
    """
    from ..services import generation

    if not seg.translated_text:
        raise RuntimeError("No translated text for segment")

    # Resolve the voice: speaker mapping → profile → default profile id.
    voice_profile_id = None
    db = _session()
    try:
        if seg.speaker_id:
            spk = db.query(DubbingSpeaker).filter_by(id=seg.speaker_id).first()
            if spk and spk.voice_profile_id:
                voice_profile_id = spk.voice_profile_id
    finally:
        db.close()

    if not voice_profile_id:
        voice_profile_id = await _find_default_profile()

    engine, model_size = _resolve_profile_voice(voice_profile_id)

    # For preset voices the engine needs its preset_voice_id wired through;
    # generate_audio_sync derives the voice from the profile itself, so we
    # only pass engine + size (preset metadata is read off the profile row).
    wav_bytes = await generation.generate_audio_sync(
        profile_id=voice_profile_id,
        text=seg.translated_text,
        language="en",  # engine-language hint; engines auto-detect target lang
        engine=engine,
        model_size=model_size,
        normalize=True,
    )

    Path(out_path).write_bytes(wav_bytes)


def _resolve_profile_voice(profile_id: str) -> tuple[str, str]:
    """Return ``(engine, model_size)`` for a Voicebox profile.

    Priority:
      1. ``preset_engine`` + its size (Kokoro etc. — but those are NOT cached,
         so this only fires if the user explicitly picked that preset).
      2. ``default_engine`` if it's a known, loaded-able engine.
      3. ``qwen``/``1.7B`` — the cached MLX Qwen3-TTS (no download).
    """
    db = _session()
    try:
        row = db.query(VoiceProfile).filter_by(id=profile_id).first()
    finally:
        db.close()

    if row is None:
        return "qwen", "1.7B"

    # Preset voices: use the preset engine + size that matches the cached repo.
    if row.voice_type == "preset" and row.preset_engine:
        engine = row.preset_engine
        if engine == "kokoro":
            return "kokoro", "default"
        return engine, "default"

    # Cloned/designed with an explicit default engine.
    if row.default_engine and row.default_engine != "qwen_custom_voice":
        return row.default_engine, "default"

    # Fall back to the cached Qwen3-TTS 1.7B (MLX bf16 repo present on the box).
    return "qwen", "1.7B"


async def _find_default_profile() -> str:
    """Return an existing voice-profile id for synthesis (first available)."""
    from ..services import profiles

    db = _session()
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
    """Place each segment's WAV on the master canvas (start|center|end).

    Alignment + time-stretch polish (m03):
      - ``alignment`` decides where the synthesized audio sits inside the
        original segment window: ``start`` / ``center`` / ``end``.
      - ``pace_multiplier`` scales the *target* duration (faster/slower read).
      - ``auto_stretch`` phase-vocoders the audio (pitch-preserving) to hit
        the target window exactly; without it the audio keeps its natural
        length and only placement shifts.
    """
    rows = db.query(DubbingSegment).filter_by(project_id=project_id).order_by(DubbingSegment.sequence_index.asc()).all()
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

        # A synthesized WAV can come back empty (TTS returned nothing, or
        # trim/runaway-detection zeroed it). Placing zero samples later makes
        # the resample/stretch step call np.interp with empty sample points and
        # crash the whole assemble. Skip it so the rest of the track survives.
        if len(audio) == 0:
            logger.warning("Skipping empty synthesized segment %s", seg.id)
            continue

        window_start_s = seg.start_time
        window_end_s = seg.end_time
        window_dur = max(0.1, window_end_s - window_start_s)

        # Apply pace multiplier → effective target duration.
        target_dur = window_dur * (seg.pace_multiplier or 1.0)

        # Auto-stretch (pitch-preserving) when requested and needed.
        audio_dur = len(audio) / sr
        if seg.auto_stretch and target_dur > 0.05 and abs(audio_dur - target_dur) / target_dur > 0.03:
            audio = _time_stretch(audio, sr, target_dur)

        if sr != SAMPLE_RATE:
            n = int(len(audio) * SAMPLE_RATE / sr)
            audio = np.interp(
                np.linspace(0, 1, n),
                np.linspace(0, 1, len(audio)),
                audio,
            ).astype(np.float32)

        seg_samples = len(audio)

        # Alignment: where inside the window the audio starts.
        start_sample = _alignment_start_sample(seg.alignment, window_start_s, window_end_s, seg_samples, total_samples)
        end_sample = min(total_samples, seg_samples + start_sample)
        if end_sample > start_sample:
            canvas[start_sample:end_sample] += audio[: end_sample - start_sample]

    out_path = storage / "dubbed_master.wav"
    import soundfile as sf

    sf.write(str(out_path), canvas, SAMPLE_RATE)
    return out_path


def _alignment_start_sample(
    alignment: str,
    window_start_s: float,
    window_end_s: float,
    seg_samples: int,
    total_samples: int,
) -> int:
    """Start sample for ``start`` / ``center`` / ``end`` placement, clamped to canvas."""
    sr = SAMPLE_RATE
    if alignment == "end":
        start = int((window_end_s * sr) - seg_samples)
    elif alignment == "center":
        start = int(((window_start_s + window_end_s) / 2) * sr - seg_samples / 2)
    else:  # start
        start = int(window_start_s * sr)
    return max(0, min(start, max(0, total_samples - 1)))


def _time_stretch(audio: np.ndarray, sr: int, target_dur: float) -> np.ndarray:
    """Pitch-preserving time stretch via librosa phase vocoder.

    ``rate = original_duration / target_duration``; >1 speeds up, <1 slows
    down. Falls back to linear resample if librosa is unavailable.
    """
    import numpy as _np

    if target_dur <= 0.05:
        return audio
    orig_dur = len(audio) / sr
    rate = orig_dur / target_dur
    if abs(rate - 1.0) < 0.01:
        return audio
    try:
        from librosa.effects import time_stretch as _librosa_stretch

        stretched = _librosa_stretch(audio, rate=float(rate))
        return _np.asarray(stretched, dtype=_np.float32)
    except Exception:
        # Linear fallback — resamples, changes pitch slightly, better than nothing.
        n = max(1, int(len(audio) / max(rate, 0.05)))
        return _np.interp(
            _np.linspace(0, 1, n),
            _np.linspace(0, 1, len(audio)),
            audio,
        ).astype(_np.float32)


async def export_video(project_id: str) -> Path | None:
    """Mux the dubbed master audio back onto the original video (ffmpeg).

    Returns the path to the exported MP4, or None if the project isn't ready
    or has no dubbed audio.
    """
    import shutil as _shutil
    import subprocess as _subprocess

    db = _session()
    try:
        project = db.query(DubbingProject).filter_by(id=project_id).first()
        if project is None:
            return None
        if not project.dubbed_audio_path:
            return None
        dubbed_path = config.resolve_storage_path(project.dubbed_audio_path)
        if dubbed_path is None or not dubbed_path.exists():
            return None

        # Original media (video preferred; fall back to source audio).
        source = Path(project.source_path) if project.source_path else None
        if source is None or not source.exists():
            raise RuntimeError("No original media file available for export")

        if _shutil.which("ffmpeg") is None:
            raise RuntimeError(
                "ffmpeg is required for video export and was not found. "
                "Install it (e.g. `brew install ffmpeg`) and try again."
            )

        storage = _storage_dir(project_id)
        out_mp4 = storage / "dubbed_video.mp4"
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-i",
            str(dubbed_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(out_mp4),
        ]
        result = _subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg export failed: {result.stderr[-500:]}")

        project.dubbed_video_path = str(out_mp4.relative_to(config.get_data_dir()))
        db.commit()
        return out_mp4
    finally:
        db.close()
