"""Pronunciation dictionary service.

CRUD over the ``pronunciation_dictionary`` table plus helpers to apply
dictionary phonemes to text going into TTS.
"""

import logging
import re

from ..database import session as db_session
from ..database.models import PronunciationDictionary

logger = logging.getLogger(__name__)


def _session():
    """Return a live DB session (resolved at call time so the post-init
    ``SessionLocal`` global is used — importing it at module load would
    capture ``None`` before ``init_db()`` runs)."""
    return db_session.SessionLocal()


def list_entries(language: str | None = None) -> list[dict]:
    db = _session()
    try:
        q = db.query(PronunciationDictionary)
        if language and language != "ALL":
            q = q.filter((PronunciationDictionary.language == language) | (PronunciationDictionary.language == "ALL"))
        rows = q.order_by(PronunciationDictionary.word.asc()).all()
        return [
            {
                "id": r.id,
                "word": r.word,
                "phonemes": r.phonemes,
                "language": r.language,
                "notes": r.notes,
                "updated_at": r.updated_at,
            }
            for r in rows
        ]
    finally:
        db.close()


def upsert_entry(word: str, phonemes: str, language: str = "ALL", notes: str | None = None) -> dict:
    db = _session()
    try:
        key = word.strip().lower()
        row = db.query(PronunciationDictionary).filter_by(word=key).first()
        if row:
            row.phonemes = phonemes.strip()
            row.language = language or "ALL"
            row.notes = notes
        else:
            row = PronunciationDictionary(
                word=key,
                phonemes=phonemes.strip(),
                language=language or "ALL",
                notes=notes,
            )
            db.add(row)
        db.commit()
        db.refresh(row)
        return {
            "id": row.id,
            "word": row.word,
            "phonemes": row.phonemes,
            "language": row.language,
            "notes": row.notes,
        }
    finally:
        db.close()


def delete_entry(entry_id_or_word: str) -> bool:
    db = _session()
    try:
        row = (
            db.query(PronunciationDictionary)
            .filter(
                (PronunciationDictionary.id == entry_id_or_word)
                | (PronunciationDictionary.word == entry_id_or_word.strip().lower())
            )
            .first()
        )
        if row is None:
            return False
        db.delete(row)
        db.commit()
        return True
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Application (phone TTS input rewriting)
# ---------------------------------------------------------------------------

_WORD_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z'-]*\b")


def apply_dictionary(text: str, language: str = "en") -> str:
    """Rewrite every dictionary word in ``text`` to its phoneme annotation.

    Wraps each dictionary word in the engine-friendly
    ``<phoneme alphabet="ipa">…</phoneme>`` form (honoured by engines that
    support inline phonemes; others fall back to the plain word because the
    token remains intact and safe to read).

    The ``langauge`` filter means a word pinned to ``ALL`` or to the target
    language is applied; other languages are left untouched.
    """
    entries = _entries_for_language(language)
    if not entries:
        return text

    def _sub(match: "re.Match") -> str:
        word = match.group(0).strip()
        lower = word.lower()
        phonemes = entries.get(lower)
        if phonemes is None:
            return match.group(0)  # keep original token untouched
        return f'<phoneme alphabet="ipa">{phonemes}</phoneme>'

    return _WORD_PATTERN.sub(_sub, text)


def _entries_for_language(language: str) -> dict:
    return {e["word"]: e["phonemes"] for e in list_entries(language)}
