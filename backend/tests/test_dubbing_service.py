"""
Dubbing service persistence tests (real SQLite in a temp data dir).

These do NOT download models or run inference — they exercise the project /
segment CRUD against a throwaway SQLite DB.
"""

import shutil
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import models as db_models  # noqa: F401  (register tables)
from backend.database.models import Base


def _fresh_dubbing_session():
    """Build a throwaway SQLite engine + session for the dubbing module."""
    tmp = Path(tempfile.mkdtemp(prefix="dub_test_"))
    engine = create_engine(f"sqlite:///{tmp/'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    from backend.services import dubbing

    # Point the dubbing module at our session factory.
    dubbing.SessionLocal = session_factory
    return session_factory, tmp


def test_create_and_list_project():
    _session_factory, tmp = _fresh_dubbing_session()
    try:
        from backend.services import dubbing

        proj = dubbing.create_project(
            name="demo",
            source_language="en",
            target_language="de",
            source_path="/tmp/nonexistent.wav",
            stt_engine="parakeet",
        )
        assert proj.id
        projects = dubbing.list_projects()
        assert len(projects) == 1
        assert projects[0]["name"] == "demo"
        assert projects[0]["status"] == "draft"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_update_segment_roundtrip():
    session_factory, tmp = _fresh_dubbing_session()
    try:
        from backend.database.models import DubbingSegment
        from backend.services import dubbing

        proj = dubbing.create_project(
            name="seg-demo",
            source_language="en",
            target_language="en",
            source_path="",
        )
        db = session_factory()
        try:
            seg = DubbingSegment(
                project_id=proj.id,
                sequence_index=1,
                start_time=0.0,
                end_time=2.0,
                duration=2.0,
                source_text="hello",
                translated_text=None,
                is_dirty=True,
            )
            db.add(seg)
            db.commit()
            db.refresh(seg)
            seg_id = seg.id
        finally:
            db.close()

        updated = dubbing.update_segment(
            seg_id,
            translated_text="hallo",
            alignment="center",
            is_locked=True,
        )
        assert updated is not None
        assert updated["translated_text"] == "hallo"
        assert updated["alignment"] == "center"
        assert updated["is_locked"] is True
        assert updated["is_dirty"] is True  # text change marks dirty
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
