# Model Reuse — Reuse the Installed Voicebox HF Cache on the Test Machine

**Status:** Planning → Implemented
**Branch:** `m04-model-reuse`
**Repo:** `W1zardXYZ/voicebox` (fork)

## 1. Problem

The off-site MacBook already has the Voicebox app installed and its model cache
is populated under `/Users/w1zard/.cache/huggingface/hub`. Re-downloading the
TTS/STT/LLM weights (~20 GB) to test the fork would be wasteful.

## 2. What's already in the cache (reusable as-is)

| Engine | HF repo (cached) | Used for |
|--------|------------------|----------|
| `qwen` (TTS) | `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16` | Dubbing TTS synthesis |
| `qwen_custom_voice` | `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` | Generated voices |
| `chatterbox` | `ResembleAI/chatterbox` | Dubbing TTS (alt) |
| `whisper` (STT) | `openai/whisper-large-v3-turbo` | Transcription/segmentation |
| `qwen_llm` | `mlx-community/Qwen3-0.6B-4bit` / `-4B-4bit` | Translation length-fit |
| (unused) | `fish-speech-1.5`, `pocket-tts` | n/a (not used by fork) |

Everything the dubbing pipeline needs downstream already lives here **except**:
- **Parakeet** `nvidia/parakeet-tdt-0.6b-v3` (~2.2 GB) — new STT engine.
- **Pyannote diarization** `pyannote/speaker-diarization-3.1` (gated, needs `HF_TOKEN`) — small.

So the win: **only ~2–3 GB of new downloads**, not 20+ GB.

## 3. Why reuse works today

Voicebox routes all model loads through Hugging Face Hub, so the cache dir is a
simple contract:

- `backend/config.py` already honors the `VOICEBOX_MODELS_DIR` env var, which it
  maps to `HF_HUB_CACHE`. Setting it to the existing cache dir makes `huggingface_hub`
  hit the on-disk files instead of re-fetching.
- `huggingface_hub` also uses `~/.cache/huggingface/hub` as its **default**, so on a
  machine where the app's cache sits at the default location, no config is needed at all.

## 4. Bug to fix

`backend/services/dubbing.py` → `_synthesize_segment` hardcodes `engine="kokoro"`.
Kokoro is **not** in the cache, so dubbing would download a fresh model and bypass reuse.

**Fix:** resolve the TTS engine from the selected **voice profile** (its
`default_engine` / preset engine / cloned-engine), falling back to `qwen`
(which *is* cached) rather than `kokoro`.

## 5. Implementation

- `_synthesize_segment`: replace hardcoded `engine="kokoro", model_size="default"` with
  a profile-resolved `(engine, model_size)` via a new `_resolve_profile_voice()` helper.
- Helper reads the profile row (from `profiles` service or ORM), picks:
  1. `preset_engine` (+ its `preset_voice_id`) if present;
  2. else `default_engine` if a non-null, valid engine;
  3. else `qwen` + model_size `1.7B` (cached MLX repo).
- Ensure `run_pipeline` whisper branch already uses `turbo` (matches cached
  `whisper-large-v3-turbo`) — no change needed; dubbing transcribe via
  Parakeet remains opt-in.
- Add a startup **model-reuse health check** + a `GET /models/cache-dir` guard note
  so the test box can confirm the cache is being hit.

## 6. Setup/doc deliverable (`docs/MODEL_REUSE_SETUP.md` + README section)

How to configure the fork dev server to reuse the installed cache:

```bash
# Point the fork at the SAME cache the installed app uses (if not the default):
export VOICEBOX_MODELS_DIR=/Users/w1zard/.cache/huggingface/hub

# Only these are newly downloaded (~2–3 GB, plus pyannote's runtime libs):
pip install -r backend/requirements.txt -r backend/requirements-studio.txt
export HF_TOKEN=<token>     # pyannote gated repo only
brew install ffmpeg         # video export only

just dev-web                # web UI + uvicorn backend on :17493
```

Verification: `GET /health` shows the resolved model cache dir; the Models tab
shows Qwen TTS / Whisper large-turbo / Qwen3 LLM as **already loaded or cached**,
so no re-download.

## 7. Acceptance
- [ ] Dubbing pipeline synthesizes using cached Qwen (profile-resolved engine), no Kokoro download.
- [ ] Whisper STT uses cached `large-v3-turbo`.
- [ ] Only Parakeet + pyannote are newly downloaded on the test box.
- [ ] `GET /models/cache-dir` returns the intended cache dir.
- [ ] Typecheck + ruff + tests green; pushed to fork; README + HOWTO committed.