"""
STT (Speech-to-Text) module - delegates to backend abstraction layer.

Supports the platform default Whisper backend plus the optional Parakeet V3
engine. Both implement the ``STTBackend`` protocol.

Because ``nemo-toolkit`` (Parakeet's dependency) is optional and can be
missing or fail to import, all engine selection should go through
:func:`resolve_stt_backend`, which falls back to Whisper when Parakeet is
unavailable — so the pipeline never hard-crashes just because nemo is not
installed.
"""

import importlib.util
import logging

from ..backends import STTBackend, get_stt_backend, get_stt_backend_for_engine

logger = logging.getLogger(__name__)


def nemo_available() -> bool:
    """Whether the optional ''nemo'' (NeMo ASR) package can be imported."""
    return importlib.util.find_spec("nemo") is not None


def get_whisper_model() -> STTBackend:
    """
    Get the default STT backend (Whisper; MLX or PyTorch based on platform).

    Returns:
        STT backend instance
    """
    return get_stt_backend()


def get_parakeet_model() -> STTBackend:
    """
    Get the Parakeet V3 STT backend (NeMo, CUDA/CPU).

    Returns:
        ParakeetBackend instance
    """
    return get_stt_backend_for_engine("parakeet")


def resolve_stt_backend(engine: str) -> tuple[STTBackend, str]:
    """
    Resolve an ``STTBackend`` for the requested engine, degrading gracefully.

    If ``engine == "parakeet"`` but the optional ``nemo`` package is not
    installed/importable, logs a warning and returns the Whisper backend instead
    (so the dubbing/capture pipeline keeps running rather than crashing).

    Args:
        engine: ``"whisper"`` (default) or ``"parakeet"``.

    Returns:
        A ``(backend, resolved_engine)`` tuple where ``resolved_engine`` is the
        engine actually used (``"parakeet"`` only when nemo is importable).
    """
    if engine == "parakeet" and not nemo_available():
        logger.warning(
            "Parakeet STT requested but the optional 'nemo' package is not "
            "installed (pip install -r backend/requirements-studio.txt). "
            "Falling back to Whisper."
        )
        return get_whisper_model(), "whisper"
    return get_stt_backend_for_engine(engine), engine


def unload_whisper_model():
    """Unload Whisper model to free memory."""
    backend = get_stt_backend()
    backend.unload_model()


def unload_parakeet_model():
    """Unload Parakeet model to free memory."""
    backend = get_parakeet_model()
    backend.unload_model()
