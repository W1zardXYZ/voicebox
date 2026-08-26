"""
STT (Speech-to-Text) module - delegates to backend abstraction layer.

Supports the platform default Whisper backend plus the optional Parakeet V3
engine. Both implement the ``STTBackend`` protocol.
"""

from ..backends import STTBackend, get_stt_backend, get_stt_backend_for_engine


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


def unload_whisper_model():
    """Unload Whisper model to free memory."""
    backend = get_stt_backend()
    backend.unload_model()


def unload_parakeet_model():
    """Unload Parakeet model to free memory."""
    backend = get_parakeet_model()
    backend.unload_model()
