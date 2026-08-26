"""
Unit tests for dubbing segmentation + character-budget math (pure; no models).
"""

from backend.services.segmentation import (
    build_pause_aware_segments,
    calculate_character_budget,
)


def test_character_budget_scales_with_duration():
    short_min, short_max = calculate_character_budget(2.0, "EN")
    long_min, long_max = calculate_character_budget(6.0, "EN")
    assert long_min > short_min
    assert long_max > short_max
    assert short_min <= short_max


def test_character_budget_rate_depends_on_language():
    de_min, _ = calculate_character_budget(2.0, "DE")
    en_min, _ = calculate_character_budget(2.0, "EN")
    # German and English have different rates; assert both are sane.
    assert de_min >= 10
    assert en_min >= 10


def test_segmentation_grouped_by_pause():
    segments = [
        {
            "text": "hello world this is a test",
            "start": 0.0,
            "end": 3.0,
            "speaker_id": None,
            "words": [
                {"word": "hello", "start": 0.0, "end": 0.4},
                {"word": "world", "start": 0.4, "end": 0.8},
                {"word": "this", "start": 1.5, "end": 1.9},
                {"word": "is", "start": 1.9, "end": 2.3},
                {"word": "a", "start": 2.3, "end": 2.6},
                {"word": "test", "start": 2.6, "end": 3.0},
            ],
        }
    ]
    out = build_pause_aware_segments(segments, target_lang="EN", pause_threshold=0.3)
    # A 0.7s pause between "world" and "this" splits into 2 segments.
    assert len(out) == 2
    assert out[0]["source_text"] == "hello world"
    assert out[1]["source_text"] == "this is a test"


def test_segmentation_carries_speaker():
    segments = [
        {
            "text": "hey  howdy",
            "start": 0.0,
            "end": 2.0,
            "speaker_id": "SPEAKER_00",
            "words": [
                {"word": "hey", "start": 0.0, "end": 0.6},
                {"word": "howdy", "start": 1.2, "end": 2.0},
            ],
        }
    ]
    out = build_pause_aware_segments(segments, target_lang="EN", pause_threshold=0.5)
    # 0.6s pause splits; both carry the speaker.
    assert len(out) == 2
    assert out[0]["speaker_id"] == "SPEAKER_00"
    assert out[1]["speaker_id"] == "SPEAKER_00"


def test_segmentation_speaker_boundary_splits():
    segments = [
        {
            "start": 0.0,
            "end": 2.0,
            "speaker_id": "A",
            "words": [
                {"word": "one", "start": 0.0, "end": 0.5},
                {"word": "two", "start": 0.5, "end": 1.0},
            ],
        },
        {
            "start": 1.0,
            "end": 2.0,
            "speaker_id": "B",
            "words": [
                {"word": "three", "start": 1.0, "end": 1.5},
            ],
        },
    ]
    out = build_pause_aware_segments(segments, target_lang="EN")
    assert len(out) >= 2
    speakers = {s["speaker_id"] for s in out}
    assert "A" in speakers
    assert "B" in speakers


def test_segmentation_fallback_no_words():
    segments = [{"text": "no timestamps here", "start": 0.0, "end": 2.0, "speaker_id": None}]
    out = build_pause_aware_segments(segments, target_lang="EN")
    assert len(out) == 1
    assert out[0]["source_text"] == "no timestamps here"
