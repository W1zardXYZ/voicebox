"""
Prosody analysis + preservation for dubbing.

Recovers the *delivery* of the source speech that a plain translate-and-
resynthesize pipeline flattens away. Given word-level alignment (Parakeet /
Whisper timestamps) and the source audio, we measure:

- per-word energy (stress/emphasis via RMS),
- per-word duration (drawn-out vs clipped words),
- inter-word gaps (where / how long to pause),
- per-segment speaking rate (fast vs slow).

Those measurements are turned into a **director's script** (an ``instruct``
string plus per-segment timing hints) that we feed to TTS that supports
instruction-based prosody (e.g. the Qwen CustomVoice backend), and into a
``pace_multiplier`` that the assembler already honours. All the math is real
and runs offline with just ``librosa`` + ``numpy`` (no model downloads), so it
is testable on any machine.

Design: docs/plans/prosody-preserving-dubbing.md
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

# Nominal speech rate (words/second) used as the pace anchor. Segments faster
# than this get a `pace_multiplier > 1` (read back a bit faster); slower ones
# get < 1. Bucketing keeps the multiplier subtle rather than overcorrecting
# every tiny variation.
NOMINAL_WPS = 2.5

# Gap (seconds) beyond which we treat an inter-word silence as a deliberate
# pause worth preserving in the director's script.
PAUSE_THRESHOLD_S = 0.45

# A word whose RMS is this many times the segment's median is flagged as
# stressed/emphasized.
STRESS_RMS_RATIO = 1.6

# A word whose duration is this many times the median is flagged as drawn-out.
STRESS_DUR_RATIO = 1.6


def word_stats(
    audio: np.ndarray,
    sr: int,
    words: list[dict],
) -> list[dict]:
    """Measure prosodic features per aligned word.

    Args:
        audio: mono float audio.
        sr: sample rate.
        words: ``[{word, start, end, speaker_id}, ...]`` (aligned timestamps).

    Returns:
        A list (parallel to ``words``) of ``{word, start, end, rms, dur}``.
        ``rms`` is the word-window RMS energy; ``dur`` is its length in sec.
    """
    if not words:
        return []

    sr = int(sr) or 1
    per_word = []
    for w in words:
        start_s = float(w.get("start", 0.0))
        end_s = float(w.get("end", start_s))
        start = int(start_s * sr)
        end = max(start, int(end_s * sr))
        window = audio[start:end]
        if window.size == 0:
            rms = 0.0
        else:
            rms = float(np.sqrt(np.mean(np.square(window))))
        per_word.append(
            {
                "word": w.get("word", ""),
                "start": start_s,
                "end": end_s,
                "rms": rms,
                "dur": max(1e-6, end_s - start_s),
            }
        )
    return per_word


def compute_pace(
    words: list[dict],
    duration_s: float,
    nominal_wps: float = NOMINAL_WPS,
) -> float:
    """Map a segment's measured speaking rate to a ``pace_multiplier``.

    Returns a value clipped to a modest range so fast/slow delivery is
    preserved without distorting intelligibility.
    """
    n_words = len(words)
    if duration_s <= 0 or n_words == 0:
        return 1.0
    wps = n_words / duration_s
    if wps <= 0:
        return 1.0
    ratio = wps / nominal_wps
    return float(np.clip(ratio, 0.8, 1.4))


def rate_hint(pace: float) -> str:
    if pace >= 1.15:
        return "speak a little quicker than normal"
    if pace <= 0.87:
        return "speak a little slower than normal"
    return ""


def annotate(
    text: str,
    stats: list[dict],
) -> dict:
    """Build a director's script from measured prosody.

    Args:
        text: the (translated) text for the segment.
        stats: output of :func:`word_stats`.

    Returns:
        ``{"instruct": str, "marked_text": str}`` where ``instruct`` is a
        natural-language style directive for a TTS ``instruct`` parameter and
        ``marked_text`` is the text with capitalization-style emphasis.
    """
    if not stats:
        return {"instruct": "Speak naturally and clearly.", "marked_text": text}

    median_rms = float(np.median([s["rms"] for s in stats])) if stats else 0.0
    median_dur = float(np.median([s["dur"] for s in stats])) if stats else 0.0
    median_rms = max(median_rms, 1e-9)
    median_dur = max(median_dur, 1e-9)

    pause_count = 0
    stressed_words: list[str] = []
    for i, s in enumerate(stats):
        if i == 0:
            continue
        gap = s["start"] - stats[i - 1]["end"]
        if gap > PAUSE_THRESHOLD_S:
            pause_count += 1
        if (
            s["dur"] > 0
            and s["rms"] > 0
            and (s["rms"] / median_rms > STRESS_RMS_RATIO or s["dur"] / median_dur > STRESS_DUR_RATIO)
        ):
            word = (s.get("word") or "").strip(".,!?;:")
            if word:
                stressed_words.append(word)

    directives: list[str] = []
    if pause_count >= 2:
        directives.append("add a brief pause where the source has natural breaks between phrases")
    if stressed_words:
        directives.append("emphasize the following words: " + ", ".join(stressed_words[:6]))

    marked = text
    for word in stressed_words[:6]:
        if word in marked:
            marked = marked.replace(word, word.upper(), 1)

    if not directives:
        directives.append("speak naturally and clearly")
    instruct = "; ".join(directives) + "."
    return {"instruct": instruct, "marked_text": marked}


def split_by_breaks(
    segments: list[dict],
) -> list[dict]:
    """Split transcribed segments at strong pause boundaries (Tier 0).

    Returns the same list with ``prosody_break`` set to True on the last
    segment before a strong inter-segment pause, so translation can carry the
    source's phrasing across.
    """
    result: list[dict] = [dict(seg) for seg in segments]
    # Strong pauses between consecutive segments are already reflected in the
    # segmentation split; here we only annotate the inter-segment gap so the
    # translator/synthesizer can preserve the pause. Gapped when gaps > threshold.
    if len(result) >= 2:
        for i in range(len(result) - 1):
            cur = result[i]
            nxt = result[i + 1]
            cur_end = cur.get("end", 0.0)
            nxt_start = nxt.get("start", cur_end)
            if (nxt_start - cur_end) > PAUSE_THRESHOLD_S:
                cur["prosody_break"] = True
    return result
