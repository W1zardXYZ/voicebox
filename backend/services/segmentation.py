"""
Pause-aware segmentation and character-budget length fitting.

Ported from DUBBERc's proven pipeline math (segmentation.py): given word-level
timestamps (Parakeet/Whisper) plus a speaker label per word, group words into
speech segments that a translator can length-fit and a TTS engine can
re-synthesize into the original duration budget.
"""


# Target average speech rates (characters per second) across European languages.
SPEECH_CHARS_PER_SECOND = {
    "EN": 15.0,
    "DE": 18.5,
    "ES": 19.0,
    "FR": 17.5,
    "NL": 17.0,
    "IT": 16.0,
    "PT": 16.5,
}


def calculate_character_budget(duration: float, target_lang: str = "DE") -> tuple[int, int]:
    """
    Compute ``[min_chars, max_chars]`` permitted for a segment duration so
    re-synthesis fits naturally without extreme speedups/slowdowns.
    """
    rate = SPEECH_CHARS_PER_SECOND.get(target_lang.upper(), 18.0)
    ideal_chars = max(0.0, duration) * rate

    min_chars = max(10, int(ideal_chars * 0.88))
    max_chars = max(min_chars + 15, int(ideal_chars * 1.12))
    return min_chars, max_chars


def _flatten_words(segments: list[dict]) -> list[dict]:
    """Yield every word across segments: {word, start, end, speaker_id}."""
    words: list[dict] = []
    for seg in segments:
        if seg.get("words"):
            for w in seg["words"]:
                words.append(
                    {
                        "word": w.get("word", ""),
                        "start": float(w.get("start", seg.get("start", 0.0))),
                        "end": float(w.get("end", seg.get("end", 0.0))),
                        "speaker_id": seg.get("speaker_id"),
                    }
                )
        else:
            # No word-level data — synthesize evenly-spaced words.
            text = seg.get("text", "").strip()
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", start))
            parts = text.split()
            n = max(1, len(parts))
            dur = (end - start) / n
            for i, w in enumerate(parts):
                words.append(
                    {
                        "word": w,
                        "start": start + i * dur,
                        "end": start + (i + 1) * dur,
                        "speaker_id": seg.get("speaker_id"),
                    }
                )
    return words


def build_pause_aware_segments(
    segments: list[dict],
    target_lang: str = "EN",
    pause_threshold: float = 0.35,
    min_segment_dur: float = 1.2,
    max_segment_dur: float = 10.0,
) -> list[dict]:
    """
    Group words into pause-aware, punctuation-bounded speech segments.

    Args:
        segments: STT output with word timestamps + speaker labels.
        target_lang: language code for the character budget ("EN"/"DE"/...).

    Returns:
        List of ``{sequence_index, start_time, end_time, duration,
        source_text, speaker_id, target_char_min, target_char_max}``.
    """
    all_words = _flatten_words(segments)
    if not all_words:
        return _fallback_segments(segments, target_lang)

    result: list[dict] = []
    current: list[dict] = []

    for i, w in enumerate(all_words):
        current.append(w)
        is_last = i == len(all_words) - 1

        if is_last:
            result.append(_finalize(current, len(result) + 1, target_lang))
            break

        next_w = all_words[i + 1]
        pause = next_w["start"] - w["end"]
        current_dur = next_w["end"] - current[0]["start"]

        # Boundary if pause exceeds threshold AND segment isn't too short,
        # or if the segment is getting too long.
        boundary_pause = pause > pause_threshold and current_dur >= min_segment_dur
        boundary_len = current_dur >= max_segment_dur
        boundary_speaker = (
            next_w.get("speaker_id") and current and current[-1].get("speaker_id")
            and next_w["speaker_id"] != current[-1]["speaker_id"]
            and current_dur >= 0.5
        )

        if boundary_pause or boundary_len or boundary_speaker:
            result.append(_finalize(current, len(result) + 1, target_lang))
            current = []

    if not result:
        return _fallback_segments(segments, target_lang)
    return result


def _finalize(words: list[dict], idx: int, target_lang: str) -> dict:
    text = " ".join(w["word"] for w in words if w["word"]).strip()
    s_time = words[0]["start"]
    e_time = words[-1]["end"]
    dur = max(0.1, e_time - s_time)
    c_min, c_max = calculate_character_budget(dur, target_lang)
    return {
        "sequence_index": idx,
        "start_time": round(s_time, 2),
        "end_time": round(e_time, 2),
        "duration": round(dur, 2),
        "source_text": text,
        "speaker_id": words[0].get("speaker_id"),
        "target_char_min": c_min,
        "target_char_max": c_max,
    }


def _fallback_segments(segments: list[dict], target_lang: str) -> list[dict]:
    """No words at all — one segment per transcript block."""
    out: list[dict] = []
    for i, seg in enumerate(segments):
        text = seg.get("text", "").strip()
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start + 1.0))
        duration = max(0.1, end - start)
        c_min, c_max = calculate_character_budget(duration, target_lang)
        out.append(
            {
                "sequence_index": i + 1,
                "start_time": start,
                "end_time": end,
                "duration": duration,
                "source_text": text,
                "speaker_id": seg.get("speaker_id"),
                "target_char_min": c_min,
                "target_char_max": c_max,
            }
        )
    return out
