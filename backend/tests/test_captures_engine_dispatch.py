"""
Capture STT-engine dispatch tests.

Verifies that ``create_capture`` routes to the Parakeet backend when
``stt_engine="parakeet"`` and to Whisper otherwise, and that the resolved
engine / model is persisted on the row. No real models, inference, or
downloads: the STT backends, audio decode, and config paths are all mocked.
"""

import shutil
import tempfile
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base


class _FakeStt:
    """Minimal stand-in for an STTBackend."""

    def __init__(self, text, model_size):
        self.model_size = model_size
        self._text = text
        self.transcribe_calls: list[tuple[str, str | None, str | None]] = []

    async def transcribe(self, audio_path, language=None, model_size=None):
        self.transcribe_calls.append((audio_path, language, model_size))
        return self._text


class _Env:
    def __init__(self, session, tmp: Path, whisper, parakeet):
        self.session = session
        self.tmp = tmp
        self.whisper = whisper
        self.parakeet = parakeet


@pytest.fixture
def env(monkeypatch):
    tmp = Path(tempfile.mkdtemp(prefix="capture_dispatch_"))
    engine = create_engine(f"sqlite:///{tmp / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)  # noqa: N806

    def _captures_dir():
        d = tmp / "captures"
        d.mkdir(parents=True, exist_ok=True)
        return d

    monkeypatch.setattr("backend.config.get_captures_dir", _captures_dir)
    monkeypatch.setattr("backend.config.to_storage_path", lambda p: f"captures/{Path(p).name}")
    # Avoid real audio decode.
    monkeypatch.setattr(
        "backend.services.captures.load_audio",
        lambda path: (np.zeros(16000, dtype=np.float32), 16000),
    )

    whisper = _FakeStt("whisper said", "turbo")
    parakeet = _FakeStt("parakeet said", "v3-0.6b")
    monkeypatch.setattr("backend.services.captures.get_whisper_model", lambda: whisper)
    monkeypatch.setattr("backend.services.captures.get_parakeet_model", lambda: parakeet)

    e = _Env(Session(), tmp, whisper, parakeet)
    try:
        yield e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def _create(e: _Env, stt_engine: str | None = "whisper"):
    from backend.services import captures

    return await captures.create_capture(
        audio_bytes=b"\x00\xff" * 100,
        filename="clip.wav",
        source="dictation",
        language="en",
        stt_model=None,
        stt_engine=stt_engine,
        db=e.session,
    )


@pytest.mark.asyncio
async def test_parakeet_engine_dispatches_to_parakeet(env):
    resp = await _create(env, "parakeet")
    assert resp.stt_engine == "parakeet"
    assert resp.stt_model == "v3-0.6b"
    assert env.parakeet.transcribe_calls
    assert not env.whisper.transcribe_calls


@pytest.mark.asyncio
async def test_default_engine_is_whisper(env):
    resp = await _create(env, None)
    assert resp.stt_engine == "whisper"
    assert resp.stt_model == "turbo"
    assert env.whisper.transcribe_calls
    assert not env.parakeet.transcribe_calls


@pytest.mark.asyncio
async def test_invalid_engine_falls_back_to_whisper(env):
    resp = await _create(env, "bogus")
    assert resp.stt_engine == "whisper"
    assert env.whisper.transcribe_calls
