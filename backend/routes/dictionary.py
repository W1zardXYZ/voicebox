"""Pronunciation dictionary endpoints.

Ported from DUBBERc's proven API surface (list / upsert / delete) so the
Voicebox Settings UI can manage IPA/CMU pronunciation overrides.
"""

from fastapi import APIRouter, HTTPException

from .. import models
from ..services import dictionary

router = APIRouter()


@router.get("/dictionary", response_model=list[models.DictionaryEntryResponse])
async def list_dictionary(language: str | None = None):
    """List pronunciation dictionary entries, optionally filtered by language."""
    return dictionary.list_entries(language)


@router.post("/dictionary", response_model=models.DictionaryEntryResponse)
async def add_dictionary_entry(req: models.DictionaryEntryRequest):
    """Create or update a pronunciation entry (upsert by word)."""
    if not req.word.strip() or not req.phonemes.strip():
        raise HTTPException(status_code=422, detail="word and phonemes are required")
    return dictionary.upsert_entry(
        word=req.word,
        phonemes=req.phonemes,
        language=req.language,
        notes=req.notes,
    )


@router.delete("/dictionary/{entry_id_or_word}")
async def delete_dictionary_entry(entry_id_or_word: str):
    """Delete a dictionary entry by id or by word."""
    deleted = dictionary.delete_entry(entry_id_or_word)
    if not deleted:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"success": True}
