"""
Pyannote speaker-diarization backend.

Uses ``pyannote/speaker-diarization-3.1`` (gated HuggingFace repo) to assign
speaker ids to audio ranges. Requires a HuggingFace token set in the
``HF_TOKEN`` environment variable to download the gated weights; pyannote is
only imported lazily when this backend is used.
"""

import asyncio
import logging
import os

from . import DIARIZATION_HF_REPOS
from .base import get_torch_device, is_model_cached, model_load_progress

logger = logging.getLogger(__name__)

HF_TOKEN_ENV = "HF_TOKEN"


class PyannoteDiarizationBackend:
    """Speaker diarization via the pyannote.audio pipeline."""

    def __init__(self, model_size: str = "3.1", hf_token: str | None = None):
        self.model = None
        self.model_size = model_size
        self.hf_token = hf_token or os.environ.get(HF_TOKEN_ENV, "")

    def is_loaded(self) -> bool:
        return self.model is not None

    def _is_model_cached(self, model_size: str | None = None) -> bool:
        size = model_size or self.model_size
        repo = DIARIZATION_HF_REPOS.get(size, "pyannote/speaker-diarization-3.1")
        try:
            return is_model_cached(repo, weight_extensions=(".safetensors", ".ckpt", ".bin"))
        except Exception:
            return False

    async def load_model(self, model_size: str = "3.1"):
        """Lazy-load the pyannote diarization pipeline."""
        if self.model is not None:
            return
        if not self.hf_token:
            raise RuntimeError(
                f"Speaker diarization needs a HuggingFace token. Set {HF_TOKEN_ENV} "
                "to download the gated pyannote/speaker-diarization-3.1 model."
            )
        await asyncio.to_thread(self._load_model_sync, model_size)

    def _load_model_sync(self, model_size: str):
        progress_model_name = f"diarization-{model_size}"
        is_cached = self._is_model_cached(model_size)
        repo = DIARIZATION_HF_REPOS.get(model_size, "pyannote/speaker-diarization-3.1")

        with model_load_progress(progress_model_name, is_cached):
            from pyannote.audio import Pipeline

            self.model = Pipeline.from_pretrained(repo, use_auth_token=self.hf_token)

            device = get_torch_device(force_cpu_on_mac=True)
            if hasattr(self.model, "to") and device != "cpu":
                try:
                    self.model.to(device)
                except Exception as e:  # pragma: no cover — platform dependent
                    logger.warning("Could not move diarization model to %s: %s", device, e)

        self.model_size = model_size
        logger.info("Diarization model %s loaded successfully", repo)

    async def diarize(
        self,
        audio_path: str,
        num_speakers: int | None = None,
    ) -> list[dict]:
        """Run diarization, returning a ``{speaker_id, start, end}`` list."""

        def _sync():
            kwargs = {}
            if num_speakers:
                kwargs["num_speakers"] = int(num_speakers)
            results = self.model(str(audio_path), **kwargs)
            segments: list[dict] = []
            for turn, _, speaker in results.itertracks(yield_label=True):
                segments.append(
                    {
                        "speaker_id": speaker,
                        "start": round(turn.start, 3),
                        "end": round(turn.end, 3),
                    }
                )
            segments.sort(key=lambda s: s["start"])
            return segments

        await self.load_model(self.model_size)
        return await asyncio.to_thread(_sync)

    def unload_model(self):
        if self.model is not None:
            del self.model
            self.model = None
            logger.info("Diarization model unloaded")
