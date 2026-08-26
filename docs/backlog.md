# Dubbing + Prosody Backlog

> Location: `docs/backlog.md` — work requested by the user across dubbing /
> prosody / pipeline sessions. Each item below is concrete and actionable.

---

## P1. [BUG] `_assemble_track` crashes on empty synthesized WAV

**Reported:** `ValueError: array of sample points is empty` at `dubbing.py:558`
(`numpy.interp`) → pipeline `failed`.

**Root cause (confirmed):** in `_assemble_track`, if a segment's
`synthesized_audio_path` exists on disk but the WAV is **empty**
(`len(audio) == 0` — e.g. TTS returned nothing, or `trim_tts_output`/
runaway-detection zeroed the audio), then:

```python
audio, sr = sf.read(str(seg_path), dtype="float32")   # len(audio) == 0
...
n = int(len(audio) * SAMPLE_RATE / sr)                 # n == 0
audio = np.interp(
    np.linspace(0, 1, n),                              # x: empty
    np.linspace(0, 1, len(audio)),                     # xp: empty
    audio,
)
```
→ `array of sample points is empty`.

There is currently **no** `if len(audio) == 0: continue` guard between the
`sf.read` (line ~540) and the resample/stretch block.

**Fix:** add an empty/undersized guard right after `sf.read`:
```python
audio, sr = sf.read(str(seg_path), dtype="float32")
if audio.ndim > 1:
    audio = audio.mean(axis=1)
if len(audio) == 0:
    logger.warning("Skipping empty synthesized segment %s", seg.id)
    continue
```
Also guard the `audio_dur`/stretch path for a near-empty buffer.

**Test:** extend `test_dubbing_pipeline_simulation.py` with a case where one
`_synthesize_segment` writes a 0-byte/empty WAV, assert the pipeline still
reaches `ready` and the empty segment is skipped.

**Priority: High** (blocks finishing a dub; trivial fix).

---

## 2. [BACKLOG] Translation model quality — let the user pick before running

**Reported:** the dubbing translation uses the **Qwen3 0.6B LLM** by default and
produced "quite a few bad text translations" — outputting way too much or way
too little.

**Facts from code:**
- `backend/backends/translation_backend.py` → `translate_and_fit` calls
  `get_llm_backend()` (Qwen3 LLM) and passes **no `model_size`** — so it uses
  the engine default (`qwen3-0.6b`).
- `backend/backends/__init__.py` defines `qwen3-0.6b`, `qwen3-1.7b`,
  `qwen3-4b` (MLX 4-bit quantizations on Apple Silicon; upstream instruct
  weights on PyTorch). The 4B is the quality option:
  - `mlx-community/Qwen3-4B-4bit` (2.5 GB) on MLX
  - `Qwen/Qwen3-4B` (8 GB) on PyTorch

**Requested:**
1. **Allow selecting the translation model before running the pipeline** — a
   UI control (alongside the STT engine + voice selection) that sets `model_size`
   on the translation backend for that project run.
2. **Feature request — an even better translation model:** ideally a stronger
   model than Qwen3 4B (user said "ideally we can add an even better one").
   Research candidates and propose (e.g. a better Qwen3 family member that
   fits 8 GB, or a cloud translation provider opt-in). `backend/plans/
   prosody-preserving-dubbing.md` can host the recommendation.

**Implementation sketch:**
- Thread `llm_model_size` (or a general `translation_model`) through
  `create_dubbing_project` / `DubbingProject` and into
  `_translate_and_synthesize` → `translation_service.translate_and_fit(
  model_size=...)`.
- `LLMTranslationBackend.translate_and_fit(...)` already has the plumbing
  surface; add `model_size` param and pass to `backend.generate(model_size=)`.
- Frontend `DubbingTab.tsx`: add a "Translation model" dropdown (0.6B / 1.7B /
  4B / cloud-optin) next to the STT dropdown.

**Priority:** High (direct QA complaint).

---

## 3. [BACKLOG] Auto-create a dubbing voice profile from the uploaded source

**Reported:** after translation, the UI shows **"no speaker"** above segments,
and Voicebox inherently wants a **voice profile** to generate audio with users'
(appears as the default generation voice). User wants the ability to:

- **Automatically create a voice profile from the uploaded video/audio**
  (Voicebox already has a "voice creator" / clone-from-sample flow in the app —
  automate it instead of manual steps).
- **OR pick an existing/pre-generated profile** (toggle: "create from source" vs
  "use existing").
- The synthesis then respects the **generation model selected** (engine +
  model size from the selected profile / quality setting).

**Context:** dubbing synthesis already resolves the TTS engine/voice from the
profile (`_resolve_profile_voice`, `_find_default_profile`, `create_voice_prompt
_for_profile`). The gap is UX: the user must have a profile pre-created; there's
no "clone the source speaker from this video" automation and no clear speaker
mapping UI.

**Design questions to answer (defer):**
- Which sample does the auto-clone use (best/longest speaker in the source)?
- Multi-speaker: create one profile per detected speaker reused across segments
  with that speaker id?
- Where to surface "Create voice / Use existing" (DubbingTab project form vs
  segment picker)?

**Priority:** Medium-High.

---

## 4. [BACKLOG] Pipeline/UI clarity — download finished video & parts

**Reported:** "The entire way the projects work is also unclear, not sure when
I can download a finished video or parts of it."

- Document / design when a project becomes downloadable —
- after `assemble`: the `dubbed_master.wav` exists; the video export path
  (ffmpeg) is only attempted conditionally.
- Provide UI for: download full dubbed video, download per-segment WAVs,
  download transcripts — and status that says "Ready to download" once
  assembly completes.
- There is an existing video-export path (`_export_muxed_video`, uses ffmpeg)
  — surfaced as a button wired to the foreign "Ready/complete" state.

**Priority:** Medium.

---

## 5. [DECIDED] Prosody preservation — on by default, per-piece

These were the open items from `docs/plans/prosody-preserving-dubbing.md`;
user has chosen:
- **`prosody_preserve` flag default = ON** (Tier 1 behaviors active by default;
  keep an off switch for comparison/debug).
- **Synthesize per prosody piece** (per-piece with component synthesis +
  `crossfade_ms` to blend) rather than one-pass-with-markers, per the doc's
  recommendation.

Lock these into the implementation milestone (m07) once it's scheduled.
See `docs/plans/prosody-preserving-dubbing.md` for the full design.

---

## 6. [Probation — from current design] Dubbing pipeline unknown speaker
**Related to #3 above** — currently `_find_default_profile` different anchors
`voice_profile_id = await _find_default_profile()` which errors if **no voice
profile exists at all** ("No voice profile exists. Create a voice profile
first (Voices tab)..."). Auto-voice-creation (item #3) also fixes this
friction point.

---

## Index / status

| # | Item | Priority | Status |
|---|------|----------|--------|
| 1 | Empty-WAV guard in `_assemble_track` | High | Backlog (root-cause identified) |
| 2 | Translation model selection + better LLM | Medium | Backlog |
| 3 | Auto-create / choose dubbing voice profile | Med-High | Backlog (needs design Q&A) |
| 4 | Pipeline download/status clarity | Medium | Backlog (needs design Q&A) |
| 5 | Prosody on-by-default + per-piece | — | DECIDED → next milestone |
| 6 | Default-profile friction | Low | Backlog (ties into #3) |