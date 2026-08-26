"""Speaker diarization endpoints.

``POST /diarize`` runs pyannote diarization over an uploaded audio file and
returns speaker turns. The merge into STT word timestamps is provided by
``services/diarization.merge_speakers_into_segments`` (used by the dubbing
pipeline).
"""

import asyncio
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from .. import models
from ..services import diarization
from ..services.task_queue import create_background_task
from ..utils.tasks import get_task_manager

router = APIRouter()

UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1MB
ALLOWED_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".webm", ".opus"}


@router.post("/diarize", response_model=models.DiarizationResponse)
async def diarize_audio(
    file: UploadFile = File(...),
    num_speakers: int | None = Form(None),
):
    """Run speaker diarization over an uploaded audio file."""
    uploaded_ext = Path(file.filename or "").suffix.lower()
    file_suffix = uploaded_ext if uploaded_ext in ALLOWED_AUDIO_EXTS else ".wav"

    with tempfile.NamedTemporaryFile(suffix=file_suffix, delete=False) as tmp:
        while chunk := await file.read(UPLOAD_CHUNK_SIZE):
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        from ..utils.audio import load_audio, save_audio

        # Normalize to mono 16k WAV (pyannote needs WAV; librosa decodes the
        # container, then we re-encode).
        audio, sr = await asyncio.to_thread(load_audio, tmp_path)
        wav_path = f"{tmp_path}.diar.wav"
        await asyncio.to_thread(save_audio, audio, wav_path, sr)

        backend = diarization.get_diarization_model()
        if not backend.is_loaded() and not backend._is_model_cached():
            progress_model_name = "diarization-3.1"
            task_manager = get_task_manager()

            async def download_bg():
                try:
                    await backend.load_model("3.1")
                    task_manager.complete_download(progress_model_name)
                except Exception as e:
                    task_manager.error_download(progress_model_name, str(e))

            task_manager.start_download(progress_model_name)
            create_background_task(download_bg())
            raise HTTPException(
                status_code=202,
                detail={
                    "message": "Diarization model is being downloaded. Please wait and try again.",
                    "model_name": progress_model_name,
                    "downloading": True,
                },
            )

        turns = await backend.diarize(wav_path, num_speakers=num_speakers)
        return models.DiarizationResponse(
            engine="pyannote",
            turns=[models.SpeakerTurn(**t) for t in turns],
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        Path(f"{tmp_path}.diar.wav").unlink(missing_ok=True)
