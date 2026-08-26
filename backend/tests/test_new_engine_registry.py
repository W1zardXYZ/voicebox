"""
Registry tests for the new STT/diarization/translation engines.

These are pure metadata tests — no models are downloaded or instantiated.
"""

from backend.backends import (
    DIARIZATION_ENGINES,
    PARAKEET_HF_REPOS,
    STT_ENGINES,
    TRANSLATION_ENGINES,
    get_all_model_configs,
    get_diarization_model_configs,
    get_model_config,
    get_stt_model_configs,
)


def test_parakeet_is_registered_as_stt_engine():
    assert "parakeet" in STT_ENGINES
    assert "whisper" in STT_ENGINES


def test_parakeet_config_present_with_word_timestamps():
    configs = get_stt_model_configs()
    parakeet = [c for c in configs if c.engine == "parakeet"]
    assert parakeet, "Parakeet config missing from STT configs"
    cfg = parakeet[0]
    assert cfg.hf_repo_id == "nvidia/parakeet-tdt-0.6b-v3"
    assert cfg.model_name == "parakeet-tdt-0.6b-v3"
    assert cfg.word_timestamps is True


def test_parakeet_repo_map_matches_config():
    cfg = get_model_config("parakeet-tdt-0.6b-v3")
    assert cfg is not None
    assert PARAKEET_HF_REPOS[cfg.model_size] == cfg.hf_repo_id


def test_diarization_registry():
    assert "pyannote" in DIARIZATION_ENGINES
    configs = get_diarization_model_configs()
    assert len(configs) == 1
    assert configs[0].hf_repo_id == "pyannote/speaker-diarization-3.1"


def test_translation_registry():
    assert "llm" in TRANSLATION_ENGINES


def test_all_configs_include_new_engines():
    all_configs = get_all_model_configs()
    engines = {c.engine for c in all_configs}
    assert "parakeet" in engines
    assert "pyannote" in engines
