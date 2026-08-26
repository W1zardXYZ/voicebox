# Model Reuse Setup — Use the Already-Installed Voicebox HF Cache

The off-site MacBook already has the **Voicebox app** installed, which keeps its
models in an on-disk Hugging Face cache. This fork is designed to **reuse that
cache**, so testing the Parakeet/diarization/dubbing features does **not**
require re-downloading ~20 GB of TTS/STT/LLM weights.

## What's reused (already on disk, no re-download)

| Capability | Model (HF repo) | Used by |
|------------|-----------------|---------|
| TTS synthesis | `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16` | Dubbing TTS (default engine) |
| TTS voices | `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` | preset / designed voices |
| TTS (alt) | `ResembleAI/chatterbox` | Dubbing TTS (choose via profile) |
| STT | `openai/whisper-large-v3-turbo` | Transcription / word-timestamps |
| LLM (translation) | `mlx-community/Qwen3-0.6B-4bit` / `-4B-4bit` | Translation length-fit |

The dubbing pipeline's TTS now resolves the engine **from the selected voice
profile** and falls back to `qwen` (cached) — it no longer defaults to Kokoro
(which would have triggered a download).

## 2. Prereqs that are still *new* (first run only, ~2–4 GB total)

- **Parakeet V3 STT** `nvidia/parakeet-tdt-0.6b-v3` (~2.2 GB) — the new STT engine.
- **Pyannote diarization** `pyannote/speaker-diarization-3.1` (gated) — needs `HF_TOKEN`.
- ffmpeg (for video export — `brew install ffmpeg`).

Everything else is reused.

## 3. Setup (exact steps on the test MacBook)

```bash
git clone https://github.com/W1zardXYZ/voicebox.git
cd voicebox

# Point the fork at the SAME cache the installed app uses.
# Voicebox's config maps this env var → HF_HUB_CACHE.
export VOICEBOX_MODELS_DIR=/Users/w1zard/.cache/huggingface/hub

# Python deps — use Python **3.12** (Voicebox's requirements pin `kokoro>=0.9.4`,
# which supports only `>=3.10,<3.13`; a 3.13+ venv will fail here).
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt -r backend/requirements-studio.txt

# Token only needed for gated pyannote diarization repo
export HF_TOKEN=<your-huggingface-token>

# ffmpeg only needed for video export
brew install ffmpeg

# Start backend + web UI
just dev-web
```

> **No `just` installed?** `just dev-web` just starts two processes. Install `just`
> (`brew install just`), or run the two servers directly in two terminals:
> ```bash
> # terminal 1 — backend (uvicorn on :17493)
> .venv/bin/uvicorn backend.main:app --reload --port 17493
> # terminal 2 — web UI (Vite)
> cd web && bun run dev
> # then open http://localhost:5173
> ```

> **No `VOICEBOX_MODELS_DIR` needed?** `huggingface_hub` already defaults to
> `~/.cache/huggingface/hub`. If that's where the app keeps its models (it is,
> at `/Users/w1zard/.cache/huggingface/hub`), the export is redundant — but
> harmless. Setting it explicitly makes the reuse unambiguous.

## 4. Verify reuse (nothing re-downloading)

1. **Backend** → `GET http://127.0.0.1:17493/models/cache-dir`
   → should return `.../huggingface/hub` (your cache).
2. **Models tab** (`http://localhost:5173/models`) → Qwen TTS, Whisper large-v3-turbo,
   Qwen3 LLM should show as **already downloaded / loadable offline**.
3. Run a **dubbing project** (`/studio`):
   - Use **Whisper** as STT engine (cached large-v3-turbo), or Parakeet if you
     want the new engine (one-time download).
   - The pipeline synthesizes w/ the cached Qwen3-TTS automatically.
4. **Captures / dictation** (Settings → Captures → Transcription): pick **Parakeet V3**
   as the STT engine alongside the Whisper model dropdown, or keep **Whisper** (the
   faster default on Apple Silicon). Voice-profile transcription honors the same
   engine choice.

If you prefer Parakeet, its one-time download is contained; diarization needs
the `HF_TOKEN` and downloads once.

> **Fallback note:** the dubbing/capture pipeline now stays on **Whisper by
> default** and gracefully degrades from Parakeet to Whisper when `nemo-toolkit`
> isn't installed (no more `ModuleNotFoundError: No module named 'nemo'` crash).
> To simulate the full pipeline on a machine without models, run
> `backend/tests/test_dubbing_pipeline_simulation.py` — it fakes only the STT /
> diarization / translation / TTS boundaries and reaches `ready` with real
> extraction + assembly.

## 5. What gets created/changed on the test box

- `data/voicebox.db` — SQLite DB (projects, segments, dictionary, profiles).
- `data/dubbing/<project>` — extracted audio + per-segment + assembled WAV.
- First fresh models into the HF cache: Parakeet + pyannote only.
- No re-download of Qwen/Whisper/LLM/Chatterbox.

## 6. Troubleshooting

- **A model re-downloads anyway** → the process wasn't started with
  `VOICEBOX_MODELS_DIR` (or the default `~/.cache/...` isn't where the app
  stores models). Set the env to the app's actual model dir (check the
  installed app's Settings → Models → cache location).
- **`HF_TOKEN` errors on diarization** → the pyannote repo is gated; accept the
  terms on huggingface.co and export `HF_TOKEN`.
- **Segments show no audio** → the translated text came back empty (LLM not
  loaded); ensure the Qwen3 LLM download completed in the Models tab.

## 7. Relevant spec

See [`docs/plans/model-reuse.md`](plans/model-reuse.md) for the design,
acceptance checklist, and the m04 branch history.