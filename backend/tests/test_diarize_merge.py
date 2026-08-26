"""
Unit tests for the diarization→STT merge logic (pure; no models).
"""

from backend.services.diarization import merge_speakers_into_segments


def test_no_turns_leaves_speaker_none():
    segments = [{"start": 0.0, "end": 2.0, "text": "hi"}, {"start": 2.0, "end": 4.0, "text": "there"}]
    out = merge_speakers_into_segments(segments, [])
    assert all(s["speaker_id"] is None for s in out)
    # original dicts untouched
    assert "speaker_id" not in segments[0]


def test_speaker_assigned_by_overlap():
    segments = [
        {"start": 0.0, "end": 2.0, "text": "a"},
        {"start": 3.0, "end": 5.0, "text": "b"},
    ]
    turns = [
        {"speaker_id": "SPEAKER_00", "start": 0.0, "end": 1.5},
        {"speaker_id": "SPEAKER_01", "start": 2.5, "end": 6.0},
    ]
    out = merge_speakers_into_segments(segments, turns)
    assert out[0]["speaker_id"] == "SPEAKER_00"
    assert out[1]["speaker_id"] == "SPEAKER_01"


def test_overlapping_turn_wins_by_largest_overlap():
    segments = [{"start": 1.0, "end": 3.0, "text": "x"}]
    turns = [
        {"speaker_id": "A", "start": 0.0, "end": 3.0},  # 2.0s overlap
        {"speaker_id": "B", "start": 2.9, "end": 3.1},  # 0.1s overlap
    ]
    out = merge_speakers_into_segments(segments, turns)
    assert out[0]["speaker_id"] == "A"


def test_disjoint_turn_leaves_unsassigned():
    segments = [{"start": 5.0, "end": 6.0, "text": "y"}]
    turns = [{"speaker_id": "Z", "start": 0.0, "end": 1.0}]
    out = merge_speakers_into_segments(segments, turns)
    # no overlap at all — the segment is too far from every turn to be
    # confidently assigned, so it stays None (dubbing falls back to a default).
    assert out[0]["speaker_id"] is None
