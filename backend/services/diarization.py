"""Diarization service — delegates to the pyannote backend and merges
speaker ids into STT word/segment timestamps.
"""

from ..backends import DiarizationBackend, get_diarization_backend


def get_diarization_model() -> DiarizationBackend:
    return get_diarization_backend()


def merge_speakers_into_segments(
    segments: list[dict],
    turns: list[dict],
) -> list[dict]:
    """Assign a ``speaker_id`` to each segment based on diarization turns.

    A segment is assigned the speaker whose turn has the largest overlap with
    the segment window (using the word/start centroid as tiebreak). Falls back
    to ``None`` when there are no turns at all.

    Args:
        segments: list of ``{start, end, text, words, speaker_id}``.
        turns:    list of ``{speaker_id, start, end}`` (from /diarize).

    Returns a new list with ``speaker_id`` set on each segment.
    """

    def _overlap(seg_start: float, seg_end: float, turn: dict) -> float:
        return max(0.0, min(seg_end, turn["end"]) - max(seg_start, turn["start"]))

    if not turns:
        return [dict(s, speaker_id=None) for s in segments]

    # Index turns for O(n) lookup — assume sorted by start (diarize sorts).
    result: list[dict] = []
    for seg in segments:
        seg_copy = dict(seg)
        best_turn = None
        best_overlap = 0.0
        for turn in turns:
            ov = _overlap(seg["start"], seg["end"], turn)
            if ov > best_overlap:
                best_overlap = ov
                best_turn = turn
        seg_copy["speaker_id"] = best_turn["speaker_id"] if best_turn else None
        result.append(seg_copy)
    return result
