"""Transcription endpoints.

``/transcribe`` supports the platform-default Whisper engine and the optional
Parakeet V3 engine. ``/transcribe/segments`` returns word/multi-level
timestamps (with optional speaker assignment) for the dubbing/diarization
pipeline.
"""

import asyncio
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from .. import models
from ..services import transcribe
from ..services.task_queue import create_background_task
from ..utils.tasks import get_task_manager

router = APIRouter()

UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1MB

# Same set profiles.py accepts for voice samples. librosa picks its decoder from the
# file extension, so the temp file has to keep the uploaded one.
ALLOWED_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".webm", ".opus"}

_SUPPORTED_STT_ENGINES = {"whisper", "parakeet"}


async def _save_temp_audio(file: UploadFile) -> tuple[str, str]:
    """Persist an uploaded audio file to a temp path; returns (path, suffix)."""
    uploaded_ext = Path(file.filename or "").suffix.lower()
    file_suffix = uploaded_ext if uploaded_ext in ALLOWED_AUDIO_EXTS else ".wav"

    with tempfile.NamedTemporaryFile(suffix=file_suffix, delete=False) as tmp:
        while chunk := await file.read(UPLOAD_CHUNK_SIZE):
            tmp.write(chunk)
        tmp_path = tmp.name
    return tmp_path, file_suffix


async def _ensure_wav(tmp_path: str, file_suffix: str) -> str:
    """Re-encode non-WAV uploads to a temp WAV the STT backend can read.

    The STT backends (mlx_audio.stt / NeMo) only decode WAV/FLAC/MP3/Vorbis,
    so browser recordings uploaded as WebM/Opus fail. librosa decodes the file
    first (audioread/ffmpeg fallback for exotic containers), then we re-encode
    that PCM to WAV. WAV inputs pass through unchanged.
    """
    from ..utils.audio import load_audio, save_audio

    if file_suffix == ".wav":
        return tmp_path

    audio, sr = await asyncio.to_thread(load_audio, tmp_path)
    stt_path = f"{tmp_path}.stt.wav"
    await asyncio.to_thread(save_audio, audio, stt_path, sr)
    return stt_path


async def _duration_of(tmp_path: str) -> float:
    """Return the audio duration in seconds."""
    from ..utils.audio import load_audio

    audio, sr = await asyncio.to_thread(load_audio, tmp_path)
    return len(audio) / sr


def _stt_backend_for(engine: str):
    if engine == "parakeet":
        return transcribe.get_parakeet_model()
    return transcribe.get_whisper_model()


# A background download trigger shared by both engines (Whisper / Parakeet).
async def _ensure_downloaded(backend, model_size: str, model_key: str) -> None:
    """Raise an HTTPException(202) and kick off a background download if needed."""
    already_loaded = backend.is_loaded() and getattr(backend, "model_size", None) == model_size
    is_cached = getattr(backend, "_is_model_cached", lambda *_a, **_k: False)(model_size)

    if already_loaded or is_cached:
        return

    progress_model_name = f"{model_key}-{model_size}"
    task_manager = get_task_manager()

    async def _download_bg():
        try:
            load = getattr(backend, "load_model_async", None) or backend.load_model
            await load(model_size)
            task_manager.complete_download(progress_model_name)
        except Exception as e:
            task_manager.error_download(progress_model_name, str(e))

    task_manager.start_download(progress_model_name)
    create_background_task(_download_bg())
    raise HTTPException(
        status_code=202,
        detail={
            "message": f"{model_key.title()} model {model_size} is being downloaded. Please wait and try again.",
            "model_name": progress_model_name,
            "downloading": True,
        },
    )


@router.post("/transcribe", response_model=models.TranscriptionResponse)
async def transcribe_audio(
    file: UploadFile = File(...),
    language: str | None = Form(None),
    model: str | None = Form(None),
    engine: str | None = Form("whisper"),
):
    """Transcribe audio to text using the selected STT engine."""
    engine = (engine or "whisper").lower()
    if engine not in _SUPPORTED_STT_ENGINES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid engine '{engine}'. Must be one of: {', '.join(sorted(_SUPPORTED_STT_ENGINES))}",
        )

    tmp_path, file_suffix = await _save_temp_audio(file)
    stt_path = tmp_path
    try:
        from ..backends import PARAKEET_HF_REPOS

        backend = _stt_backend_for(engine)
        if engine == "parakeet":
            model_size = model if model in PARAKEET_HF_REPOS else "v3-0.6b"
        else:
            model_size = model or getattr(backend, "model_size", "base")

        await _ensure_downloaded(backend, model_size, engine)
        stt_path = await _ensure_wav(tmp_path, file_suffix)

        text = await backend.transcribe(stt_path, language, model_size)
        duration = await _duration_of(tmp_path)
        return models.TranscriptionResponse(text=text, duration=duration)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        if stt_path != tmp_path:
            Path(stt_path).unlink(missing_ok=True)


@router.post("/transcribe/segments", response_model=models.TranscriptionSegmentsResponse)
async def transcribe_segments(
    file: UploadFile = File(...),
    language: str | None = Form(None),
    model: str | None = Form(None),
    engine: str | None = Form("parakeet"),
):
    """Transcribe audio and return word-level segment timestamps.

    Defaults to Parakeet (emits word timestamps). Returns a ``speaker_id`` on
    each segment when available (left null here; the diarization route fills
    it via merge).
    """
    if engine not in _SUPPORTED_STT_ENGINES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid engine '{engine}'. Must be one of: {', '.join(sorted(_SUPPORTED_STT_ENGINES))}",
        )

    tmp_path, file_suffix = await _save_temp_audio(file)
    stt_path = tmp_path
    try:
        from ..backends import PARAKEET_HF_REPOS

        duration = await _duration_of(tmp_path)
        backend = _stt_backend_for(engine)

        if engine == "parakeet":
            model_size = model if model in PARAKEET_HF_REPOS else "v3-0.6b"
            await _ensure_downloaded(backend, model_size, engine)
            stt_path = await _ensure_wav(tmp_path, file_suffix)
            raw_segments = await backend.transcribe_segments(stt_path, language, model_size)
        else:
            model_size = model or getattr(backend, "model_size", "base")
            await _ensure_downloaded(backend, model_size, engine)
            stt_path = await _ensure_wav(tmp_path, file_suffix)
            text = await backend.transcribe(stt_path, language, model_size)
            raw_segments = [{"text": text, "start": 0.0, "end": duration, "words": []}]

        segments = [
            models.TranscriptionSegment(
                text=seg.get("text", ""),
                start=seg.get("start", 0.0),
                end=seg.get("end", 0.0),
                words=[models.WordSegment(**w) for w in seg.get("words", [])],
                speaker_id=seg.get("speaker_id"),
            )
            for seg in raw_segments
        ]
        return models.TranscriptionSegmentsResponse(
            engine=engine,
            language=language,
            duration=duration,
            segments=segments,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        if stt_path != tmp_path:
            Path(stt_path).unlink(missing_ok=True)
