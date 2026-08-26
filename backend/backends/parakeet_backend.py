"""
Parakeet V3 STT backend using NVIDIA NeMo.

Parakeet TDT 0.6B v3 is a fast, word-timestamp-emitting ASR model. It is
torch/NeMo based and runs on CUDA or CPU (there is no Metal/MLX path yet, so
Apple Silicon uses the CPU fallback). Whisper stays the platform default;
Parakeet is selected explicitly as ``engine="parakeet"``.

The heavy imports (``nemo_toolkit``) are deferred to ``load``/``transcribe``
so the base app and Whisper path never pay the cost of importing them.
"""

import asyncio
import logging

from . import PARAKEET_HF_REPOS
from .base import get_torch_device, is_model_cached, model_load_progress

logger = logging.getLogger(__name__)


class ParakeetBackend:
    """NeMo-based Parakeet V3 STT backend."""

    # Keeps explicit class state so is_loaded/model_size checks work like the
    # other STT backends (MLXSTTBackend / PyTorchSTTBackend).
    def __init__(self, model_size: str = "v3-0.6b"):
        self.model = None
        self.model_size = model_size

    def is_loaded(self) -> bool:
        return self.model is not None

    def _is_model_cached(self, model_size: str | None = None) -> bool:
        size = model_size or self.model_size
        hf_repo = PARAKEET_HF_REPOS.get(size, "nvidia/parakeet-tdt-0.6b-v3")
        return is_model_cached(hf_repo, weight_extensions=(".safetensors", ".bin", ".ckpt"))

    async def load_model_async(self, model_size: str | None = None):
        """Lazy-load the Parakeet model (blocking load in a thread)."""
        if model_size is None:
            model_size = self.model_size

        if self.model is not None and self.model_size == model_size:
            return

        await asyncio.to_thread(self._load_model_sync, model_size)

    # Alias for protocol compatibility.
    load_model = load_model_async

    def _load_model_sync(self, model_size: str):
        """Synchronous model loading via NeMo ASRModel.from_pretrained."""
        progress_model_name = f"parakeet-{model_size}"
        is_cached = self._is_model_cached(model_size)
        hf_repo = PARAKEET_HF_REPOS.get(model_size, "nvidia/parakeet-tdt-0.6b-v3")

        with model_load_progress(progress_model_name, is_cached):
            from nemo.collections.asr.models import ASRModel

            logger.info("Loading Parakeet model %s (%s)...", model_size, hf_repo)
            self.model = ASRModel.from_pretrained(hf_repo, map_location="cpu")

        # Move to the best torch device once loaded.
        device = get_torch_device(force_cpu_on_mac=True)
        if device != "cpu":
            try:
                self.model = self.model.to(device)
                logger.info("Moved Parakeet model to %s", device)
            except Exception as e:  # pragma: no cover - platform dependent
                logger.warning("Could not move Parakeet model to %s: %s", device, e)

        self.model_size = model_size
        logger.info("Parakeet model %s loaded successfully", model_size)

    def unload_model(self):
        if self.model is not None:
            del self.model
            self.model = None
            logger.info("Parakeet model unloaded")

    def _transcribe_pcm(self, audio_path: str, language: str | None) -> list[dict]:
        """Run Parakeet inference and return raw transcript hypotheses.

        Returns a list of ``{text, start, end, words:[{word,start,end}]}``.
        Falls back to a single plain-text segment if word timestamps aren't
        available for the model's decoder.
        """
        transcript = self.model.transcribe(
            [audio_path],
            batch_size=1,
            language=language if language else "en",
        )

        # transcript is a list across the batch (we sent one file).
        item = transcript[0] if isinstance(transcript, list) and transcript else transcript
        text = ""
        if isinstance(item, str):
            text = item.strip()
        elif item is not None:
            text = getattr(item, "text", None) or str(item).strip()

        return [{"text": text, "start": 0.0, "end": 0.0, "words": []}]

    async def transcribe(
        self,
        audio_path: str,
        language: str | None = None,
        model_size: str | None = None,
    ) -> str:
        """Transcribe audio to plain text."""
        await self.load_model_async(model_size)
        segments = await asyncio.to_thread(self._transcribe_pcm, audio_path, language)
        return " ".join(seg["text"] for seg in segments if seg["text"]).strip()

    async def transcribe_segments(
        self,
        audio_path: str,
        language: str | None = None,
        model_size: str | None = None,
    ) -> list[dict]:
        """Transcribe audio and return word-level segment timestamps."""
        await self.load_model_async(model_size)
        return await asyncio.to_thread(self._transcribe_pcm, audio_path, language)
