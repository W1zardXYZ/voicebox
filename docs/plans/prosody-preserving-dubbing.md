# Design — Prosody-Preserving Dubbing

**Status:** Draft for review (no code yet)
**DECIDED by user (2026-08-26):**
- `prosody_preserve` **default = ON** (off-switch kept for comparison/debug).
- **Synthesize per prosody piece** (per-piece synthesis + `crossfade_ms`) rather
  than one-pass-with-markers.
- Remaining feature asks (translation-model selection, auto voice profile,
  download UX) tracked in `docs/backlog.md`.

**Related:** `docs/plans/video-dubbing-sts-diarization.md`, milestone m06,
`docs/backlog.md`
**Working product insight:** a full text-replacement dubbing pipeline flattens
the source signal (`speech → bare text → translated bare text → cold TTS`),
losing F0 contour, energy/stress, durations, micro-pauses, and speaking-rate
variation. This doc designs how to recover and re-inject that "original
information."

> **Scope/gate note.** Web search was unavailable during this session, so the
> "Family B" research section is literature/model knowledge rather than fresh
> vendor lookups; a re-check of Fish Speech / SEAMLESS current status is
> flagged inline before any Family-B implementation.

---

## 1. Where "the original information" lives

Prosody is measurable from the source audio *before* any target text exists.
All of these are cheap to compute with `librosa` (already a dependency) plus
alignment timestamps (Parakeet/Whisper).

| Feature | Encodes | Sourced from |
|---|---|---|
| F0 contour | intonation: rising questions, falling statements | librosa `pyin` / parselmouth |
| Per-word RMS energy | **stress / emphasis / loudness peaks** | aligned window RMS |
| Per-word duration | drawn-out vs clipped words | word timestamps |
| Inter-word gap | **where/how long to pause** | word-timestamp deltas |
| Segment speaking rate | fast/slow delivery | words-per-second |

**Your pipeline already has the lynchpin:** Parakeet's `transcribe_segments`
returns `{word, start, end}` per word, and `segmentation._flatten_words`
already reduces that into per-word timestamps + speaker labels. Today those
timestamps feed speaker merging + splitter bounds — but are **not** used for
delivery. That is the biggest free lever.

---

## 2. How ElevenLabs Dubbing v2 does it (honest framing)

Internals are proprietary; not public. What the engineering community and
ElevenLabs' own marketing language indicate:

- **v1** ≈ your architecture: transcribe → translate text → synthesize text cold.
- **v2** publicly emphasizes emotive/natural delivery, multi-speaker handling,
  and preserving more of the source performance. The span-shared pattern is:
  *transcript-based localization PLUS source-derived prosody conditioning* —
  i.e. the target audio is conditioned on (a) the exact translated words and
  (b) prosodic features measured off the original, rather than read cold from
  translated text.

There is no public spec of the exact decoder/feature mechanism. The
non-proprietary recipe we can replicate is described below.

---

## 3. The two families + trade-off

| Family | Mechanism | Pros | Cons | Fits 8 GB? |
|---|---|---|---|---|
| **A — Prosody-guided TTS** | measure prosody → annotate translated text with pauses/stress/pace → feed markers + `instruct` to a controllable TTS; enforce timing with existing alignment/stretch | best control, reuses your text pipeline, cheap | fidelity capped by how well TTS obeys markers | **Yes (recommended)** |
| **B — Speech-to-speech / voice conversion** (SEAMLESSM4T, Fish S2S) | translate in the acoustic domain, carry timing/emotion natively | best delivery fidelity, no text-in-loop | weak wording control; heavy | 2B-class no; small S2S maybe |

User's instinct is correct: Family B "voice-changer" keeps intonation almost
for free but loses word control; Family A keeps words at the cost of delivery
fidelity.

---

## 4. Design — Tier 0: pause + rate-preserving translation

**Goal (small, high leverage):** make the translated text respect the source's
pause/sentence structure, and fix the per-segment delivery temporally rather
than defaulting all segments to 1.0.

### 4.1 Preserve sentence/pause structure across translation
Today `translate_and_fit(text=..., max_chars=..., min_chars=...)` receives a
whole segment's text and returns a fresh translation reflecting punctuation
and grouping that don't correspond to the source.

- **Change:** short-source each segment in to **sentence pieces** using the
  measured pause boundaries (from `_flatten_words` gaps), translate each
  piece, and rejoin with the *same* break "spine" (commas / periods / pause
  markers). So a source pause lands on a target punctuation boundary.
- Implementation: a thin `prosody.py` helper `split_by_pauses(words, text)`
  reused by segmentation; translate per-group and map back to segments.

### 4.2 Per-segment pace from measured rate
- In `_persist_project_artifacts` / segmentation, compute each segment's
  `source_wps = len(words)/segment_duration_s`.
- Set `DubbingSegment.pace_multiplier = clip(source_wps / nominal_wps)` instead
  of default `1.0`. `_assemble_track` already applies `pace_multiplier` (m03) so
  this instantly makes fast lines stay fast and slow lines stay slow.

### 4.3 Human-readable `instruct` (optional even at Tier 0 — cheap)
Build a short style sentence, e.g. `"Pause briefly after each comma-like boundary; emphasize parts in CAPS."` and thread it through the existing
`instruct` plumbing (below).

---

## 5. Design — Tier 1: prosody script + `instruct`

This is the core fix. It converts measured prosody into a **director's script**
and feeds it to the Qwen CustomVoice backend, which **already accepts
`instruct`** for tone/emotion/prosody.

### 5.1 New module: `backend/services/prosody.py`
- `word_stats(audio, sr, words) -> [ {word, start, end, rms, dur, f0_mean, f0_contour} ]`
  (using librosa `pyin`, `feature.rms`).
- `annotate(text, stats) -> dict{ marked_text, instruct }`:
  - `<pause Nms>` / `…` for gaps > threshold (sourced from inter-word deltas);
  - stress/emphasis on words whose RMS or duration deviates strongly
    (uppercase them in `instruct`, or wrap via the TTS's notation);
  - per-segment rate hints (`"slightly slower"` / `"quicker"`).
- `compute_pace(...)` and `split_by_breaks(...)` helpers (shared with Tier 0).

### 5.2 Wire into the pipeline
The `instruct` plumbing is **already built end-to-end**:
`_synthesize_segment` → `generate_audio_sync(instruct=)` → `generate_chunked`
→ `tts_model.generate(instruct=)` → `qwen_custom_voice_backend.generate(instruct=)`.

Today `_synthesize_segment` (dubbing.py:~440) passes **no `instruct`**. Change:
1. Compute per-segment prosody in `_persist_project_artifacts` (or lazily in
   `_synthesize_segment`), store on `DubbingSegment` (add columns: `prosody_
   _annotation`, `pace_multiplier` already exists).
2. In `_synthesize_segment`:
   ```python
   annot = segment.prosody_annotation  # director's script
   wav = await generation.generate_audio_sync(..., text=seg.translated_text,
                                              instruct=annot.instruct, ...)
   ```

### 5.3 Timing enforcement
Even if the Qwen CustomVoice backend only approximates the markers, the
`_assemble_track` **`_time_stretch` + `align` + `auto_stretch`** (already
implemented m03) will squeeze/stretch to the voiced segment window. So delivery
arrives from two cooperating layers:
1. `instruct` steers stress/pause/emotion intra-segment;
2. stretch enforces the global window timing.

### 5.4 Model fitness check
Qwen CustomVoice takes free-form `instruct`; it is NOT a strong marker-leader
like an SSML engine, so we should **measure how faithfully it honors pause and
emphasis markers** in the simulation (Tier below) before committing to its
marker syntax. If `/pause`/`**` notation is ineffective, rotate to:
- an SSML-aware TTS that honors `<break>`/`<prosody>`, or
- augment via **chunking the segment** into prosody-bounded pieces and
  synthesizing them separately with per-piece pace (`crossfade_ms` is already
  supported) — deterministic timing from the transcription won't depend on the
  model's marker comprehension.

---

## 6. Design — Simulation harness on 8 GB (no models)

Same philosophy as `test_dubbing_pipeline_simulation.py`: keep all **prosody
extraction + annotation logic real**; mock only the TTS/STT boundaries.

- Input: a short synthesized source WAV (e.g. a stretched tone, or a short
  recorded clip if we add one to the repo).
- Run: force-align word timestamps with a **mock** that returns a realistic
  `{word, start, end}` list (constant gap), then run `prosody._stats` on the
  real audio with librosa.
- Assert: the produced `annotate()` `instruct` contains pause/emphasis markup
  where the ground truth expects it; pace multiplier != 1; pipeline reaches
  `status=="ready"`.
- This validates the *annotation logic* with real audio math and fake TTS — no
  model downloads, works on 8 GB M3 Max VM.

**Deliverable gate for Tier 1:** the mocked test demonstrates the directive
markup is sensible; real Qwen responsiveness to markers is then a short
offline test on a machine with the model before claiming a win.

---

## 7. Family B (research notes — re-verify before implementation)

Rationale for *not* defaulting to Family B on this project:
- **Meta SEAMLESSM4T (2B)** — true speech-to-speech translation, prosody
  carries natively. But 2B params is benchmarked target CUDA ≥ 16 GB and is not
  comfortable on an 8 GB VM, no Metal STT/ASR path on Apple Silicon.
- **Fish Speech S2S / voice conversion** — strong intonation carry, but it is
  primarily a voice-conversion / style-transfer stack, not a guaranteed-literal
  target-text dubbing system; wording fidelity is a real risk, which matters
  for a dubbing UI that shows translated subtitles matched to audio.
- Conclusion: Family A delivers the control-and-cost profile that matches this
  codebase (profiles, alignment, stretch, `instruct`) on the 8 GB target. Revisit
  Family B only if the user wants a dedicated GPU/cloud box.

---

## 8. Backwards-compat + phasing
- Tier 1 features behind a **project flag**: `dubbing_projects.prosody_preserve`
  bool — **default ON per user decision**, with an off-switch in the UI for
  comparison/debug. Existing projects/runs are untouched because the flag
  defaults to its value at insert.
- Migration: `_add_column` via `backend/database/migrations.py` (m05 pattern).
- New model columns: `DubbingSegment.prosody_annotation` (Text),
  `DubbingSegment.source_wps` / `target_pace` (Float), and the project-wide
  `prosody_preserve` flag.

---

## 9. Concrete change-list (for the implementation milestone)

1. **New** `backend/services/prosody.py`: `word_stats()`, `annotate()`,
   `split_by_breaks()`, `compute_pace()`, `instruct_from_annot()`.
2. `backend/services/segmentation.py`: keep pause bounds; expose inter-word
   gap list for prosody.
3. `backend/services/dubbing.py`:
   - `_translate_and_synthesize`: per-segment `pace_multiplier` from source rate
     (Tier 0), and pass `prosody_annotation` → `instruct` (Tier 1).
   - `_synthesize_segment`: attach `instruct=` from the annotation decorator.
4. `backend/database/migrations.py` + `models.py`: add prosody/preservation
   columns + project flag.
5. `app/src/components/Studio/DubbingTab.tsx`: expose a "Preserve delivery"
   checkbox (maps to `prosody_preserve`).
6. Tests:
   - `test_prosody.py` — feature extraction + annotation unit tests (real
     audio, fake alignment).
   - `test_dubbing_pipeline_prosody_sim.py` — end-to-end sim with mocked TTS
     verifying `pace_multiplier!=1` and `instruct` populated; still `ready`.
7. Docs in `docs/history/` + `docs/plans/prosody-preserving-dubbing.md`.

---

## 10. Open questions
- **RESOLVED:** synthesize **per-prosody-piece** with crossfade (user decision).
- **RESOLVED:** `prosody_preserve` default = **ON** (off-switch kept).
- Preferred marker notation for the Qwen `instruct` (test empirically — still open).
- Re-verify Fish/SEAMLESS numbers (web search was offline this session).