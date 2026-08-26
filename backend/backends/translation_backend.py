"""
Translation / length-fit backend.

Implements ``TranslationBackend`` on top of the existing local LLM backend
(``get_llm_backend`` → Qwen3) so no extra model download is required.
``translate_and_fit`` asks the LLM to produce a target-language rendering that
stays within an optional character budget (driven by the dubbing
length-fitting step).
"""

import logging

from . import get_llm_backend

logger = logging.getLogger(__name__)

# Character budget guidance shown to the LLM so it can length-fit naturally.
_PREAMBLE = (
    "You are a dialogue translation engine for AI voice dubbing. Translate the "
    "user's line from {src} to {tgt} as speech meant to be spoken aloud. Keep it "
    "faithful but natural, preserve proper nouns, and keep it concise. "
    "If a character budget is given, stay within it (roughly). "
    "Output only the translated text — no quotes, no explanation."
)


class LLMTranslationBackend:
    """Translation backend driven by the local LLM."""

    def __init__(self, temperature: float = 0.3):
        self.temperature = temperature

    def is_loaded(self) -> bool:
        try:
            return get_llm_backend().is_loaded()
        except Exception:
            return False

    def unload_model(self) -> None:
        from contextlib import suppress

        backend = get_llm_backend()
        with suppress(Exception):
            backend.unload_model()

    async def translate_and_fit(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        max_chars: int | None = None,
        min_chars: int | None = None,
        tone: str = "natural",
        context: str | None = None,
        model_size: str | None = None,
    ) -> str:
        """Translate ``text`` to ``target_lang`` within any char budget.

        ``model_size`` (e.g. ``"0.6B"``/``"1.7B"``/``"4B"``) picks the local
        Qwen3 LLM used; omitted uses the backend default (``0.6B``).
        """
        budget = ""
        if min_chars or max_chars:
            budget = f" between {min_chars or 0} and {max_chars or 'unlimited'} characters"

        prompt = (
            f"{_PREAMBLE}".format(src=source_lang, tgt=target_lang)
            + (f" {budget}." if budget else ".")
            + (f"\n\nContext: {context}" if context else "")
            + f"\n\n{text}"
        )
        backend = get_llm_backend()
        return (
            await backend.generate(
                prompt,
                system=("You are a professional dialogue localizer for AI dubbing. Return only the translated text."),
                max_tokens=1024,
                temperature=self.temperature,
                model_size=model_size,
            )
        ).strip()
