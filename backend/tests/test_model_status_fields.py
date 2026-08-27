"""Spec §1 — /models/status availability ledger.

Asserts every registry model is present (Parakeet and pyannote included — the
old frontend filters dropped them) and carries the platform fields:
``engine``, ``supported``, ``support_note``, ``needs_token``.
"""

import pytest


@pytest.mark.asyncio
async def test_model_status_includes_all_registry_models():
    from backend.backends import get_all_model_configs
    from backend.routes.models import get_model_status

    response = await get_model_status()
    returned = {m.model_name: m for m in response.models}

    # Every registry config must surface in the status list.
    for cfg in get_all_model_configs():
        assert cfg.model_name in returned, f"{cfg.model_name} missing from /models/status"

    # Spec §1.2.2: the models that used to be silently dropped must render.
    assert "parakeet-tdt-0.6b-v3" in returned
    assert "pyannote-3.1" in returned


@pytest.mark.asyncio
async def test_model_status_platform_fields_present():
    from backend.routes.models import get_model_status

    response = await get_model_status()
    assert response.models, "expected at least one model"

    for m in response.models:
        assert m.engine, f"{m.model_name} missing engine field"
        assert m.supported is True, f"{m.model_name} should be supported (CPU fallback exists)"
        if m.model_name != "pyannote-3.1":
            assert m.needs_token is False, f"{m.model_name} should not require a token"


@pytest.mark.asyncio
async def test_pyannote_is_gated():
    from backend.routes.models import get_model_status

    response = await get_model_status()
    pyannote = next((m for m in response.models if m.model_name == "pyannote-3.1"), None)
    assert pyannote is not None
    assert pyannote.needs_token is True
    assert pyannote.engine == "pyannote"


@pytest.mark.asyncio
async def test_parakeet_engine_annotated():
    from backend.routes.models import get_model_status

    response = await get_model_status()
    parakeet = next(
        (m for m in response.models if m.model_name == "parakeet-tdt-0.6b-v3"), None
    )
    assert parakeet is not None
    assert parakeet.engine == "parakeet"
