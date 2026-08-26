"""
m03 polish tests: alignment placement math + time-stretch (pure, no models).
"""

import numpy as np

from backend.services.dubbing import SAMPLE_RATE, _alignment_start_sample, _time_stretch


def test_alignment_start():
    # window 2s..3s, audio 0.5s
    seg_samples = int(0.5 * SAMPLE_RATE)
    start = _alignment_start_sample("start", 2.0, 3.0, seg_samples, int(10 * SAMPLE_RATE))
    assert abs(start - 2.0 * SAMPLE_RATE) < SAMPLE_RATE * 0.02


def test_alignment_end():
    seg_samples = int(0.5 * SAMPLE_RATE)
    start = _alignment_start_sample("end", 2.0, 3.0, seg_samples, int(10 * SAMPLE_RATE))
    assert abs(start - (3.0 * SAMPLE_RATE - seg_samples)) < SAMPLE_RATE * 0.02


def test_alignment_center():
    seg_samples = int(0.5 * SAMPLE_RATE)
    start = _alignment_start_sample("center", 2.0, 3.0, seg_samples, int(10 * SAMPLE_RATE))
    centered = (2.5 * SAMPLE_RATE) - seg_samples / 2
    assert abs(start - centered) < SAMPLE_RATE * 0.02


def test_alignment_clamped_to_canvas():
    # window beyond the canvas edge (audio longer than remaining canvas).
    start = _alignment_start_sample("end", 9.5, 12.0, int(2.0 * SAMPLE_RATE), int(10 * SAMPLE_RATE))
    assert 0 <= start < 10 * SAMPLE_RATE


def test_time_stretch_speeds_up():
    sr = 16000
    audio = np.zeros(sr * 2, dtype=np.float32)  # 2s
    out = _time_stretch(audio, sr, target_dur=1.0)  # halve length
    out_dur = len(out) / sr
    assert abs(out_dur - 1.0) < 0.1


def test_time_stretch_slows_down():
    sr = 16000
    audio = np.zeros(sr, dtype=np.float32)  # 1s
    out = _time_stretch(audio, sr, target_dur=2.0)  # double length
    out_dur = len(out) / sr
    assert abs(out_dur - 2.0) < 0.1


def test_time_stretch_noop_when_same_duration():
    sr = 16000
    audio = np.zeros(sr, dtype=np.float32)  # 1s
    out = _time_stretch(audio, sr, target_dur=1.0)
    assert len(out) == len(audio)  # no-op returns same array
