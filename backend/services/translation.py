"""Translation service — delegates to a translation backend (local/cloud LLM).

Exposes `translate_and_fit` used by the translation route and the dubbing
pipeline.
"""

from ..backends import TranslationBackend, get_translation_backend


def get_translation_model(provider: str | None = None) -> TranslationBackend:
    return get_translation_backend(provider)


async def translate_and_fit(
    text: str,
    source_lang: str,
    target_lang: str,
    max_chars: int | None = None,
    min_chars: int | None = None,
    tone: str = "natural",
    context: str | None = None,
) -> str:
    """Translate text to target_lang, fitting an optional character budget."""
    backend = get_translation_backend()
    return await backend.translate_and_fit(
        text=text,
        source_lang=source_lang,
        target_lang=target_lang,
        max_chars=max_chars,
        min_chars=min_chars,
        tone=tone,
        context=context,
    )
