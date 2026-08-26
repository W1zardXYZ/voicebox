"""
Prosody module unit tests (real audio, no model downloads).

Verifies the prosody math on a real synthetic WAV: per-word RMS energy,
per-segment pace, pause detection, and director's-script annotation.
"""

import numpy as np

from backend.services import prosody


def _render(audio: np.ndarray, sr: int = 16000) -> "np.ndarray":
    return audio


def test_word_stats_measures_energy_and_duration():
    sr = 16000
    # One loud word in the middle, two quiet ones; duration via timestamps.
    total = int(1.5 * sr)
    audio = np.zeros(total, dtype=np.float32)

    # word at 0.0-0.4s (quiet), 0.5-1.0 (loud), 1.1-1.5 (quiet)
    def _fill(lo, hi, amp):
        audio[int(lo * sr) : int(hi * sr)] = amp

    _fill(0.0, 0.4, 0.1)
    _fill(0.5, 1.0, 0.9)
    _fill(1.1, 1.5, 0.1)

    words = [
        {"word": "soft", "start": 0.0, "end": 0.4},
        {"word": "LOUD", "start": 0.5, "end": 1.0},
        {"word": "soft2", "start": 1.1, "end": 1.5},
    ]
    stats = prosody.word_stats(audio, sr, words)
    assert len(stats) == 3
    assert stats[1]["rms"] > stats[0]["rms"] * 3
    assert stats[1]["rms"] > stats[2]["rms"] * 3
    assert abs(stats[1]["dur"] - 0.5) < 1e-6


def test_compute_pace_reflects_rate():
    # 10 words over 2s = 5 wps (fast) → pace > 1
    words = [{"start": i * 0.2, "end": i * 0.2 + 0.15} for i in range(10)]
    pace_fast = prosody.compute_pace(words, 2.0)
    assert pace_fast > 1.0
    assert pace_fast <= 1.4

    # 10 words over 10s = 1 wps (slow) → pace < 1
    words_slow = [{"start": i, "end": i + 0.8} for i in range(10)]
    pace_slow = prosody.compute_pace(words_slow, 10.0)
    assert pace_slow < 1.0
    assert pace_slow >= 0.8


def test_annotate_flags_stress_and_pauses():
    stats = [
        {"word": "a", "start": 0.0, "end": 0.2, "rms": 0.1, "dur": 0.2},
        {"word": "very", "start": 0.3, "end": 0.5, "rms": 1.0, "dur": 0.2},  # stressed
        {"word": "important", "start": 1.1, "end": 1.5, "rms": 0.1, "dur": 0.4},  # gap 0.6>threshold
        {"word": "pause", "start": 2.2, "end": 2.5, "rms": 0.1, "dur": 0.3},  # gap 0.7 from prev
    ]
    annot = prosody.annotate("a very important pause", stats)
    assert "important" in annot["instruct"] or "very" in annot["instruct"]
    assert "emphasize" in annot["instruct"]
    assert "pause" in annot["instruct"]
    # A stressed word should be uppercased in the marked text.
    assert "IMPORTANT" in annot["marked_text"] or "VERY" in annot["marked_text"]


def test_split_by_breaks_annotates_long_gaps():
    segs = [
        {"text": "one", "start": 0.0, "end": 1.0, "words": []},
        {"text": "two", "start": 2.0, "end": 3.0, "words": []},  # 1.0s gap
    ]
    out = prosody.split_by_breaks(segs)
    assert out[0].get("prosody_break") is True


def test_word_stats_empty_input():
    assert prosody.word_stats(np.zeros(100, dtype=np.float32), 16000, []) == []
    assert prosody.compute_pace([], 1.0) == 1.0


def test_split_into_pieces_breaks_on_punctuation():
    from backend.services.dubbing import _split_into_pieces

    pieces = _split_into_pieces(
        "This is the first complete sentence for the piece. And here is a second complete sentence for the piece."
    )
    assert len(pieces) >= 2, pieces
    # A single short line with no breaks stays whole.
    assert _split_into_pieces("short line") == ["short line"]
