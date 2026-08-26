# Voicebox — Parakeet V3 STT · Speaker Diarization · Pronunciation Dictionary · Translation & Dubbing Studio

**Status:** Planning (spec-driven, awaiting build approval)
**Author:** W1zardXYZ
**Repo:** `W1zardXYZ/voicebox` (fork of `jamiepine/voicebox`)
**Scope:** This document is the build spec. No models are downloaded or run on the authoring machine (insufficient hardware). Testing happens on the off-site Apple Silicon / Linux Macbook.

---

## 1. Objective

Augment Voicebox — the open-source local AI voice studio — with four capabilities that close the loop between Voicebox's existing **input side** (Whisper STT) and DUBBERc's **dubbing/translation** workflow:

1. **Parakeet V3 STT** backend (NVIDIA `parakeet-tdt-0.6b-v3`) as a first-class, selectable STT engine alongside Whisper.
2. **Speaker Diarization** (`pyannote/speaker-diarization-3.1`) so transcriptions carry per-speaker labels/timelines.
3. **Custom Pronunciation Dictionary** (IPA / CMU Arpabet) pinned to specific words, feeding both transcription and TTS synthesis.
4. **Translation & Dubbing Studio** — a self-hosted pipeline that takes a media file, transcribes + diarizes it, segments it, translates it, re-synthesizes each segment with a chosen Voicebox voice profile, and assembles a dubbed output.

Design principle: **reuse and extend Voicebox's existing backend abstraction** (the engine-backend registry, `STTBackend` / `TTSBackend` protocols, `ModelConfig` registry, REST routes, SQLite data model, and React frontend) rather than bolting on a parallel system. Where DUBBERc already solves a problem well (segmentation, translation length-fitting, pronunciation dictionary UX, multi-speaker voice assignment), we port its proven approach into Voicebox's structure.

---

## 2. How Voicebox Currently Works (as-built today)

### Backend (Python FastAPI + PyInstaller/Tauri)
- **Abstraction layer** `backend/backends/__init__.py`:
  - Protocols: `TTSBackend`, `STTBackend`, `LLMBackend`.
  - `ModelConfig` dataclass → central metadata per model variant (`model_name`, `engine`, `hf_repo_id`, `model_size`, `size_mb`, `languages`, `needs_trim`, `supports_instruct`).
  - Registry dicts `TTS_ENGINES`, `LLM_ENGINES` and lazy `get_tts_backend_for_engine(engine)`, `get_stt_backend()`, `get_llm_backend()`, with double-checked locking.
  - `get_all_model_configs()`, `get_stt_model_configs()`, `get_model_config(name)` etc.
- **STT** today = Whisper only, two backends:
  - `MLXSTTBackend` (`mlx_audio.stt`) — default on Apple Silicon.
  - `PyTorchSTTBackend` (`transformers.WhisperForConditionalGeneration`) — everywhere else.
  - Sizes: `base/small/medium/large/turbo`; lazily loaded, cached, live download progress.
  - `routes/transcription.py` (`POST /transcribe`), `services/transcribe.py` (thin wrapper).
- **Routes**: thin HTTP handlers validating → delegating to services → engine backend.
- **Models**: `backend/database/models.py` (SQLAlchemy): `profiles`, `profile_samples`, `generations`, `generation_versions`, `audio_channels`. New DB tables via migrations.
- **TTS engines**: Qwen3-TTS, Qwen CustomVoice, LuxTTS, Chatterbox, Chatterbox Turbo, TADA, Kokoro, with device auto-selection (MLX/CUDA/ROCm/CPU).

### Frontend (`React 18 + TypeScript`, Zustand, TanStack Query, Tailwind, WaveSurfer)
- `app/src/`: `components/Profiles|Generation|Stories|ServerSettings`, `lib/api/`, `stores/`, `types/`.
- Settings section includes `ServerSettings/ModelManagement.tsx` (download/load/unload any model from registry).

### Why this is the right host
Voicebox already has the model registry + download pipeline + engine protocol seam + speech synthesis. Adding Parakeet/diarization slots cleanly into the existing registry, and dubbing can reuse Voicebox's existing TTS engines & voice profiles (cloned voices included) rather than DUBBER's HTTP-service adapters.

---

## 3. Design Overview

Three new concern layers, each following current Voicebox patterns:

```
┌─────────────────────────────── FRONTEND (React) ───────────────────────────────┐
│  Settings/ModelManagement  ·  Studio:DubbingView  ·  Settings:DictionaryView  │
│  (React Query + Zustand, WaveSurfer for segment timeline)                      │
└───────────────────────────────────┬────────────────────────────────────────────┘
                                    │  HTTP 127.0.0.1:17493
┌───────────────────────────────────┴────────────────────────────────────────────┐
│                            BACKEND (FastAPI, SQLite)                            │
│  routes:  /models (register new), /transcribe, /diarize, /dictionary,          │
│           /dubbing (media, segments, translate, synth, assemble)               │
│  services: transcribe, diarization, dictionary, translation, dubbing           │
│  backends: parakeet_backend  diarization_backend  translation_backend          │
│            (TTSEngineBackend, LLMBackend reused from today)                    │
│  data:    pronunciation_dictionary (new table)                                  │
└───────────────────────────────────┬────────────────────────────────────────────┘
                                    │ I/O
┌───────────────────────────────────┴────────────────────────────────────────────┐
│  INFERENCE:  Parakeet (NeMo) · Pyannote diarization · Ollama/OpenRouter LLM ·  │
│              existing TTS engines (Qwen/React/Chatterbox/Kokoro)              │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Model Registry additions (`backend/backends/__init__.py`)

Add `ParakeetBackend`, `PyannoteBackend`, and a `TRANSLATION_ENGINES` registry mirroring `LLM_ENGINES`.

| engine key      | model_name               | hf_repo_id                                  | size | notes                                        |
|-----------------|--------------------------|---------------------------------------------|------|----------------------------------------------|
| `parakeet`      | `parakeet-tdt-0.6b-v3`   | `nvidia/parakeet-tdt-0.6b-v3`               | ~2.2GB | Fast STT, word timestamps, 1000s of languages | 
| `diarization`   | `pyannote-3.1`           | `pyannote/speaker-diarization-3.1`          | ~pyannote | Gated (HF token), standard diarization       |
| —              | —                        | —                                          | —      | Translation uses LLM (local Ollama or existing Qwen3 LLM config / OpenRouter cloud BYOK) |

Registry wiring:
- Add Parakeet to `get_stt_model_configs()`, `get_all_model_configs()`, and the `CRU` in `routes/models.py` unload/loaded path won't be Whisper-specific — the route already calls by engine... but `unload_model_by_config`/`check_model_loaded`/`get_model_load_func` currently special-case `whisper/qwen/qwen_llm/qwen_custom_voice`. These helper dispatch functions will gain `parakeet` and `pyannote` branches (kept string-based to match existing style).
- Parakeet reuse: `STTBackend` protocol; `ModelConfig` gets a `word_timestamps: bool = False` field (Parakeet supports word-level, Whisper does too via `return_timestamps`, but keep feature orthogonal).

---

## 5. Feature 1 — Parakeet V3 STT backend

**New file `backend/backends/parakeet_backend.py`** implementing `STTBackend`:

- **Load**: NeMo `parakeet.tdt` via `nemo_toolkit` / `pesa` — `from_pretrained("nvidia/parakeet-tdt-0.6b-v3")`, device from `platform_detect.get_backend_type()` (CUDA/CPU; MPS/MLX NOT used — Parakeet is torch-based, runs on CPU/GPU; Apple Silicon uses CPU).
- **ModelConfig**: size labels `v3-0.6b`, default loaded model; `size_mb` ~2300; `languages` broad (Whisper-like set extended); `py_timestamps = True`.
- **Transcribe** semantics matching `STTBackend.transcribe(...) -> str`, plus optional **word/segment timestamps** returned via a new optional method / struct `SegmentTimestamps` (list of `{text,start,end,words:[{word,start,end,prob}]}`). This powers Feature 2 (diarization merge) and Feature 4 (pre-harmonization).
- Lazy load, `_is_model_cached`, download progress (`model_load_progress`), `unload_model`, `is_loaded` — identical contract to `MLXSTTBackend`.
- **Route**: `POST /transcribe` already exists and current; extend the `model`/`engine` selection to accept `engine=parakeet` (needs a default-compatible wire). Add a second route `POST /transcribe/segments` returning word/segment timestamps.

> Note on Apple Silicon: Parakeet (NeMo) does not run on Metal. This fork is validated on the user's Linux/Apple-Silicon Macbook via CPU/CUDA path; Whisper/MLX remains the Apple-Silicon default. The diarization + translation + dubbing features work anywhere.

---

## 6. Feature 2 — Speaker Diarization

**New file `backend/backends/dinger_backend.py`** implementing a new `DiarizationBackend` protocol (add to `backends/__init__.py`):
- `load_model()`, `diarize(audio_path: str, num_speakers: int | None = None) -> list[SpeakerSegment{spk_id,start,end}]`, `unload_model()`, `is_loaded()`.
- Uses `pyannote/speaker-diarization-3.1` (pipeline). Needs `HF_TOKEN` (gated repo) — read from env `HF_TOKEN`, surfaced in Settings. Falls back gracefully with a human message if token absent.
- **New route `POST /diarize`**, **service `services/diarization.py`**.
- **Merge logic** in a new `services/diarize_merge.py`: takes word/segment timestamps (from Parakeet) + diarization turns → assigns a `speaker_id` to each word/segment (overlap-priority: word-centroid inside a speaker turn), emitting `Utterance` objects (DUBBER-style) that downstream consumption uses.

---

## 7. Feature 3 — Custom Pronunciation Dictionary

**DB**: new SQLAlchemy table `pronunciation_dictionary`
```
id        TEXT PK
word      TEXT NOT NULL UNIQUE
phonemes  TEXT NOT NULL   -- IPA or CMU Arpabet
language  TEXT DEFAULT 'ALL'
notes     TEXT
updated_at TIMESTAMP
```

**Route** (`routes/dictionary.py`) — port DUBBER's proven API surface:
- `GET    /dictionary`            list all, ordered by word
- `POST   /dictionary`            upsert (create on conflict update) — DUBBER-style ON CONFLICT
- `DELETE /dictionary/{id}`       delete by id or word

**service `services/dictionary.py`** with a `apply_dictionary(text, language) -> str` that, for any dictionary word present in a TTS string, replaces/injects phonemes in the form the target TTS engine understands:
- engines honoring IPA/lexicon (e.g. use an inline wrapper: the dictionary term encloses in the engine's phoneme syntax), plus a generic `TTS dic` normalization hook that callable before `generate()`.

**Frontend**: a **Pronunciation Dictionary** section — reuse DUB's SettingsView layout (table + add-form with Word / Phonemes / Language / Notes; delete per row). Placed under Settings.

---

## 8. Feature 4 — Translation & Dubbing Studio

### 8.1 Translation
- New `TranslationBackend` protocol + adapter:
  - **Local**: existing `LLMBackend` (Qwen3) — no new download.
  - **Cloud (BYOK)**: OpenRouter via `OPENROUTER_API_KEY` (DUB's proven prompt shape: source→target, literal + characters, length-fit).
- **Route `POST /translate`** body `{text, source_lang, target_lang, max_chars?, min_chars?, tone?}` — with length-fitting (reuse DUB's `calculate_character_budget` logic: ~15-20 chars/sec × segment duration ±10%).

### 8.2 Pipeline (Dubbing)
New `services/dubbing.py` + `routes/dubbing.py` orchestrating a multi-stage job run in background (task queue `services/task_queue.py` reused), streaming progress via SSE/events (reuse existing `routes/events.py`):

Stage order (DUB-proven):
1. `extract` — media → 16k mono WAV (+ proxy video for preview).
2. `separate` *(optional)* — background/vocals — **skip** if source is clean/stemmed; reuse existing split hooks or DUB's Demucs adapter. Marked **P2 (optional)**.
3. `transcribe` — Parakeet (or Whisper) → segments **with word timestamps**.
4. `diarize` — Pyannote → merge → each segment gets a `speaker_id`.
5. `segment` — pause-aware / punctuation-bounded grouping (port DUB `build_pause_aware_segments` & `calculate_character_budget`).
6. `translate` — per segment via TranslationBackend with char-fit.
7. `synth` — for each segment, synthesize via a chosen **Voicebox voice profile** (existing `generate_service` / `TTSBackend`) — voice scheduling per speaker (default: speaker→profile mapping; UI selectable).
8. `assemble` — place segments on a canvas with `start / center / end` alignment and optional time-stretch (user-driven), `pace_multiplier`, `auto_stretch`. Per-segment `is_locked` (won't overwrite on re-runs). **This mirrors DUB's Figma-style segment placement.**
9. `save` — write output WAV + metadata record to `generations`.

### 8.3 Data model additions (`database/models.py`)
- `dubbing_projects` (id, name, source_path, source_lang, target_lang, status, profile/persona mapping)
- `dubbing_segments` (id, project_id, seq, start_time, end_time, source_text, translated_text, speaker_id, pace_multiplier, alignment, auto_stretch, is_locked, source_audio_path, synthesized_audio_path, is_dirty)
- `dubbing_speakers` (id, project_id, label, voice_profile_id | preset)

### 8.4 Frontend: Dubbing Studio view
New `app/src/components/Studio/`:
- **Overview/Create** modal (DUB's CreateDubModal pattern): pick media file, source + target language, optional voice-mapping.
- **Timeline editor** (WaveSurfer): segments with source/translated text, expected/actual duration, alignment + stretch; speaker badges; lock toggle; per-segment "re-synthesize".
- **Stage status** progress via events; final "Play / Export" button.
- Accessibility: runs purely over the **web UI** (`just dev-web`), no Tauri packaging required for testing.

---

## 9. Frontend Build Plan (summary)
- Add `PronunciationDictionaryView` + `DubbingStudioView` to `app/src/app` router navigation.
- Extend `ModelManagement.tsx` model list to show Parakeet + Diarization model entries with download/load/unload states (already reads registry).
- New `/lib/api` clients + types for dictionary, diarize, translate, dubbing endpoints.
- Tailwind + CMY-flavor accents kept consistent with DUB styling where sensible.

---

## 10. Dependencies added
| Dependency | Use | Notes |
|-----------|-----|-------|
| `nemo-toolkit` (or `nemo_toolkit[asr]`) | Parakeet inference | CPU/CUDA; not on Apple Silicon; large |
| `torch` (already present) | Parakeet/Diarization | existing dep |
| `pyannote.audio` + `speechbrain` | diarization | gated HF repo; needs `HF_TOKEN` |
| `httpx` (present) / `openai` (present) | OpenRouter BYOK | reuse |

Names/commandlists live in `backend/requirements.txt` guarded by `requires-advanced-stt` extra so base install stays lean; `just dev-web` brings them on the test machine.

---

## 11. Milestone plan (mirrors DUB's mNN-branch discipline)

| Phase | Branch | Deliverable | Gate |
|------|--------|-------------|------|
| **P1** | `m01-backends` | Parakeet backend + registry + `/transcribe/segments`; diarization backend + protocol + `/diarize` + merge; model configs wired; DB table for dictionary; dictionary routes/UI; translation route; **channel route + dubbing skeleton routes** | Code + typecheck green; unit tests on Parakeet registry / dict CRUD / char-fit |
| **P2** | `m02-studio` | Dubbing Studio backend: project/segment data model, pipeline runner (extract→transcribe→diarize→segment→translate→synth→assemble), progress SSE, frontend Dubbing view (create, editor timeline, stage status) | typecheck + tests; web UI runnable |
| **P3** | `m03-polish` | Demo recipe, README/docs (this page → docs), pronun UI polish, aligned stretch edge cases, lock/auto_stretch | full green; final PR to fork main + upstream PR offer |

Each phase: merge green into `main` on the fork, open fresh branch (per working agreement), leave `docs/SESSION-<date>.md`.

---

## 12. Out of scope / decisions
- **No model downloads / no inference here** — author machine lacks GPU/VRAM. Everything validated on the off-site MacBook.
- **No packaged Tauri app** — webUI + `uvicorn` / `just dev-web` only.
- **Demucs vocal-separation is P2/optional**; the core dubbing path works from any speech audio (including pre-separated).
- **Licensed content**: no D&D/official content in this repo; dictionary entries are user/example-provided.

---

## 13. Acceptance checklist
- [ ] `just dev-web` serves the webUI with backend on 127.0.0.1:17493.
- [ ] Parakeet appears in Model Management; downloads/loads; `/transcribe` returns word timestamps.
- [ ] Diarization loads (HF token); `/diarize` returns speakers; timeline merge assigns speakers correctly.
- [ ] Dictionary CRUD works; a custom phoneme forces a term's pronunciation in TTS.
- [ ] Create media project → runs full dubbing pipeline → segments edited → synth → playable exported audio.
- [ ] All new tests + `bun typecheck` + `ruff` green before merge.