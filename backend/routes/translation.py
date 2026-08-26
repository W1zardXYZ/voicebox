"""Translation endpoints.

``POST /translate`` translates a line with optional character budget
(length-fit). Used directly by the dubbing pipeline and by the UI.
"""

from fastapi import APIRouter, HTTPException

from .. import models
from ..services import translation

router = APIRouter()


@router.post("/translate", response_model=models.TranslationResponse)
async def translate_text(req: models.TranslationRequest):
    """Translate text to target_lang within an optional character budget."""
    if not req.text.strip():
        raise HTTPException(status_code=422, detail="text is required")
    if not req.source_lang or not req.target_lang:
        raise HTTPException(status_code=422, detail="source_lang and target_lang are required")
    try:
        text = await translation.translate_and_fit(
            text=req.text,
            source_lang=req.source_lang,
            target_lang=req.target_lang,
            max_chars=req.max_chars,
            min_chars=req.min_chars,
            tone=req.tone,
            context=req.context,
        )
        return models.TranslationResponse(text=text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
