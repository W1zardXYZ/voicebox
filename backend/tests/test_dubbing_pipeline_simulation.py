"""
Full-dubbing-pipeline simulation (no model downloads).

Runs the REAL ``run_pipeline`` orchestration (extract → transcribe →
diarize → segment → translate → synthesize → assemble) against a real
SQLite DB and real synthetic audio on this machine. Only the model-boundary
calls (STT, diarization, translation, TTS synthesis) are faked to return
realistic output — so we can troubleshoot every code path in the pipeline
without downloading Parakeet/nemo, Whisper, pyannote, or any TTS weights.

This is the machine's substitute for running the heavy ML stack.
"""

import io
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import models as db_models  # noqa: F401  (register tables)
from backend.database.models import Base

SR = 16000


class _FakeSttBackend:
    """Stands in for the Whisper/Parakeet backend, producing word timestamps."""

    def __init__(self):
        self.model_size = "turbo"

    async def load_model_async(self, model_size=None):
        pass

    async def load_model(self, model_size=None):
        pass

    async def transcribe(self, audio_path, language=None, model_size=None):
        return "Hello this is a simulated transcript."

    async def transcribe_segments(self, audio_path, language=None, model_size=None):
        # Faithful word-timestamped seg; transcript over ~1.5s.
        return [
            {
                "text": "Hello simulated transcript",
                "start": 0.0,
                "end": 1.5,
                "words": [
                    {"word": "Hello", "start": 0.0, "end": 0.4},
                    {"word": "simulated", "start": 0.5, "end": 1.0},
                    {"word": "transcript", "start": 1.1, "end": 1.5},
                ],
            }
        ]


class _FakeDiarization:
    """No-op speaker-diarization backend that returns zero turns."""

    async def load_model(self, *_args, **_kwargs):
        pass

    async def diarize(self, path):
        return []


async def _fake_translate(**kwargs):
    return "Hi! This is an example translation."


@pytest.fixture
def sim(monkeypatch):
    """Point DB + data dir at a temp location and fake the model boundaries."""
    tmp = Path(tempfile.mkdtemp(prefix="dub_pipeline_sim_"))
    data_dir = tmp / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    engine = create_engine(f"sqlite:///{tmp / 'sim.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)  # noqa: N806

    import backend.config as config
    from backend.database import session as db_session

    config.set_data_dir(data_dir)
    # _session() in dubbing resolves SessionLocal at call time -> patch the global.
    db_session.SessionLocal = Session

    stt = _FakeSttBackend()
    monkeypatch.setattr("backend.services.transcribe.nemo_available", lambda: False)
    monkeypatch.setattr(
        "backend.services.transcribe.resolve_stt_backend",
        lambda engine: (stt, "whisper"),
    )
    monkeypatch.setattr("backend.services.diarization.get_diarization_model", lambda: _FakeDiarization())
    monkeypatch.setattr("backend.services.translation.translate_and_fit", _fake_translate)
    monkeypatch.setattr("backend.services.dubbing._find_default_profile", lambda: "sim-profile-id")

    # Patch the whole synthesis step at the dubbing module level so we never
    # import the torch-dependent generation/profile modules on this machine.
    async def _fake_synth_segment(seg, out_path, storage):
        buf = io.BytesIO()
        sf.write(buf, np.zeros(8000, dtype=np.float32), 4000, format="WAV")
        buf.seek(0)
        Path(out_path).write_bytes(buf.read())

    monkeypatch.setattr("backend.services.dubbing._synthesize_segment", _fake_synth_segment)

    yield {"tmp": tmp, "Session": Session, "stt": stt}
    shutil.rmtree(tmp, ignore_errors=True)


def _make_source_audio(data_dir: Path) -> Path:
    """Write a short mono WAV source file for the pipeline to extract."""
    src = data_dir / "sample.wav"
    t = np.linspace(0, 2.0, int(SR * 2.0), endpoint=False)
    tone = 0.5 * np.sin(2 * np.pi * 220.0 * t).astype(np.float32)
    sf.write(str(src), tone, SR, format="WAV")
    return src


@pytest.mark.asyncio
async def test_full_pipeline_sim_produces_ready_dub(sim):
    from backend.services import dubbing

    data_dir = sim["tmp"] / "data"
    src = _make_source_audio(data_dir)

    proj = dubbing.create_project(
        name="sim",
        source_language="en",
        target_language="de",
        source_path=str(src),
        stt_engine="parakeet",  # request parakeet -> must gracefully land on whisper
    )
    assert proj is not None
    assert proj.id

    await dubbing.run_pipeline(proj.id)

    from backend.database.models import DubbingProject

    db = sim["Session"]()
    try:
        p = db.query(DubbingProject).filter_by(id=proj.id).first()
    finally:
        db.close()

    assert p is not None, "project should exist after pipeline"
    assert p.status == "ready", f"pipeline should complete; got status={p.status}"
    assert p.dubbed_audio_path, "dubbed track should be produced"


@pytest.mark.asyncio
async def test_pipeline_extract_creates_master_wav(sim):
    from backend.services import dubbing

    data_dir = sim["tmp"] / "data"
    src = _make_source_audio(data_dir)

    proj = dubbing.create_project(
        name="sim2",
        source_language="en",
        target_language="de",
        source_path=str(src),
        stt_engine="whisper",
    )
    await dubbing.run_pipeline(proj.id)
    master = dubbing._storage_dir(proj.id) / "master_16k.wav"
    assert master.exists(), "extract step should produce master_16k.wav"
