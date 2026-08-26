"""
STT engine fallback tests.

Verifies that requesting the optional Parakeet engine when ``nemo`` is
unavailable resolves to the Whisper backend instead of raising, so the
dubbing/capture pipeline degrades gracefully rather than crashing with
``ModuleNotFoundError``.
"""

import backend.services.transcribe as transcribe


class _FakeBackend:
    def __init__(self, name):
        self.name = name
        self.model_size = "turbo"


def test_nemo_available_probe(monkeypatch):
    monkeypatch.setattr(transcribe, "nemo_available", lambda: False)
    assert transcribe.nemo_available() is False
    monkeypatch.setattr(transcribe, "nemo_available", lambda: True)
    assert transcribe.nemo_available() is True


def test_parakeet_falls_back_to_whisper_when_nemo_missing(monkeypatch):
    monkeypatch.setattr(transcribe, "nemo_available", lambda: False)
    whisper = _FakeBackend("whisper")
    monkeypatch.setattr(transcribe, "get_whisper_model", lambda: whisper)

    backend, resolved = transcribe.resolve_stt_backend("parakeet")
    assert resolved == "whisper"
    assert backend.name == "whisper"


def test_parakeet_stays_when_nemo_available(monkeypatch):
    monkeypatch.setattr(transcribe, "nemo_available", lambda: True)
    parakeet = _FakeBackend("parakeet")
    monkeypatch.setattr(transcribe, "get_stt_backend_for_engine", lambda engine: parakeet)

    backend, resolved = transcribe.resolve_stt_backend("parakeet")
    assert resolved == "parakeet"
    assert backend.name == "parakeet"


def test_whisper_requests_resolve_to_whisper(monkeypatch):
    whisper = _FakeBackend("whisper")
    monkeypatch.setattr(transcribe, "get_stt_backend_for_engine", lambda engine: whisper)

    backend, resolved = transcribe.resolve_stt_backend("whisper")
    assert resolved == "whisper"
    assert backend.name == "whisper"
