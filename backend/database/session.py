"""Engine creation, initialization, and session management."""

import logging
import uuid

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from .. import config
from .migrations import run_migrations
from .models import (
    AudioChannel,
    Base,
    EffectPreset,
    Generation,
    GenerationVersion,
    ProfileChannelMapping,
    VoiceProfile,
)
from .seed import backfill_generation_versions, seed_builtin_presets

logger = logging.getLogger(__name__)

# Initialized by init_db()
engine = None
SessionLocal = None
_db_path = None


def init_db() -> None:
    """Initialize the database engine, run migrations, create tables, and seed data."""
    global engine, SessionLocal, _db_path

    _db_path = config.get_db_path()
    _db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        f"sqlite:///{_db_path}",
        # timeout is sqlite3's busy handler: wait up to 30s on a locked
        # database instead of raising "database is locked" immediately.
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        # WAL lets readers proceed while a writer holds the lock, which is
        # the main source of lock racing between the generation worker and
        # request handlers. synchronous=NORMAL is the recommended pairing
        # (durable across app crashes, fsyncs only on checkpoint).
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    run_migrations(engine)
    Base.metadata.create_all(bind=engine)

    # Create default audio channel if it doesn't exist
    db = SessionLocal()
    try:
        default_channel = db.query(AudioChannel).filter(AudioChannel.is_default).first()
        if not default_channel:
            default_channel = AudioChannel(
                id=str(uuid.uuid4()),
                name="Default",
                is_default=True,
            )
            db.add(default_channel)

            for profile in db.query(VoiceProfile).all():
                db.add(ProfileChannelMapping(
                    profile_id=profile.id,
                    channel_id=default_channel.id,
                ))
            db.commit()
    finally:
        db.close()

    backfill_generation_versions(SessionLocal, Generation, GenerationVersion)
    seed_builtin_presets(SessionLocal, EffectPreset)


def get_db():
    """Yield a database session (FastAPI dependency)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
