# Voicebox — Stories, Queue/Progress, German TTS & Model-Switching Spec

> Status: **draft for review**
> Scope: a revamp of the Stories tab (markdown import, chapter/segment hierarchy,
> per-segment speaker assignment), fix of the model-switch "GPU string" bug,
> model-availability/memory improvements, an explicit generation **queue** +
> **progress** UX, an investigation of the timeline **snapping** defects, and
> faster **German** TTS engines.
> Audience: a reviewing agent, then an implementing agent. This doc is the
> contract — it describes *what* to build and *where* it lives, and marks
> decisions the reviewer must confirm.

---

## 0. The product the user wants

The user produces long-form German audiobooks from markdown scripts. Today one
"Story" is a flat list of TTS clips. They want it to feel like a real
audiobook studio (the ElevenLabs **Projects → Chapters → Script** model):

- Import a `.md` script.
- A dialog lets you pick how to **split it** into chapters/segments (by H1, by
  H2, by paragraph, or by `[read aloud]` tags).
- The result is a **chapter → segment → clip** hierarchy, not one blob.
- Each **segment** has an assignable **speaker/voice** (a Voicebox voice
  profile) and is generated independently, so a narrator and multiple
  characters can be distinct voices.
- Editor shows the headlines, the text, and per-segment speaker pickers
  (simple, text-driven), plus the multi-track timeline below.

Also: model switching must not throw a "GPU string" error; models should
unload when not needed so only the active engine occupies memory; the user
must see a **queue** and a **progress** readout; and German synthesis should be
faster than Qwen3-TTS-1.7B.

---

## 1. Models pane: availability ledger + platform compatibility

### 1.1 How it works today

- Backend: `GET /models/status` (`backend/routes/models.py:226`) reads the
  declarative registry (`backend/backends/__init__.py` `get_all_model_configs()`)
  and computes per-model `downloaded` / `downloading` / `loaded` / `size_mb`
  from the HF cache (`huggingface_hub.scan_cache_dir`) and the task manager.
- Frontend: `app/src/components/ServerSettings/ModelManagement.tsx` calls
  `apiClient.getModelStatus()` (a `react-query` `useQuery`) and groups the
  result into three sections: `voiceGeneration`, `transcription`, `languageModels`
  (`ModelManagement.tsx:409-427`).
- Per-model buttons: download, load/unload, open HF card, delete.

### 1.2 Gaps observed

1. **Platform-compatibility is invisible.** `ModelStatus` has no notion of
   "does this model even run on this machine?" The registry knows which
   backend an engine uses, and each backend has a fixed device policy (see
   §2), but the pane never tells the user e.g. *"Parakeet V3 has no Metal path
   — runs on CPU on Apple Silicon"* or *"LuxTTS is English-only"*.
2. **Some registry models never render.** The frontend `voiceModels` filter
   (`ModelManagement.tsx:409-418`) only matches `qwen-tts*`, `qwen-custom-voice*`,
   `luxtts`, `chatterbox*`, `tada*`, `kokoro`; the `parakeet-tdt-0.6b-v3` and
   `pyannote-3.1` entries are therefore absent from every section. The subtitle
   promises "all your models" but these are silently dropped.
3. **No "why" for a missing download.** When a model isn't downloaded there is
   no hint of its size/disk cost, total size after download, or whether it is
   gated (e.g. pyannote needs `HF_TOKEN`).
4. **No live in-use indicator beyond `loaded`.** "Loaded" is only set by the
   engine's singleton; there's no per-engine memory footprint or "this is the
   engine the *current* voice profile wants" hint.

### 1.3 Spec

- Extend `ModelStatus` (`backend/models.py` / `routes/models.py:356`) with:
  - `supported: bool` + `support_note: str | null` — derived from the
    engine/backend's device policy and platform. Source of truth: a new helper
    in `backend/backends/base.py`, e.g.
    `def engine_platform_note(engine: str) -> tuple[bool, str | None]`,
    used by both `/models/status` and the generate path so the note can never
    drift from reality.
  - `needs_token: bool` (true for gated repos like pyannote).
  - `engine: str`, `display_name`, `size_mb`, `size_mb_download` (already have
    size_mb; use it).
- Fix the frontend section filters so `parakeet*` and `pyannote*` render,
  either by adding `transcription` for parakeet and a new `diarization`/`utils`
  section, or by building sections from the `engine`/`kind` field rather than
  hard-coded name prefixes.
- Surface `support_note` as a muted warning line on the card, and grey out a
  model that is `downloaded` but `supported == false` (e.g. Parakeet on Apple
  Silicon) rather than presenting it as usable.
- Add a top-level "active engines" strip (or a per-engine badge) showing which
  backend is currently loaded and its device, linking straight to the GPU page.

---

## 2. Model-switching "GPU string" bug

### 2.1 What the user sees

Switching the engine/model dropdown (the "Model" selector — `EngineModelSelector.tsx`)
from one engine to another and generating throws an error along the lines of
*"didn't find a GPU string"*.

### 2.2 Where the value comes from

- The frontend selector only sets `engine` + `modelSize` form fields
  (`EngineModelSelector.tsx:60-108`). It does **not** cause the error directly.
- The backend resolves `engine → get_tts_backend_for_engine(engine)` and calls
  `load_engine_model` (`backend/backends/__init__.py:667`), then
  `backend.load_model(...)`.
- The risky path is in the **Qwen engines**:
  - `PyTorchTTSBackend._load_model_sync` (`backend/backends/pytorch_backend.py:90`)
    → `Qwen3TTSModel.from_pretrained(model_path, cache_dir=..., device_map=self.device, torch_dtype=bf16)` (`:116`).
  - `QwenCustomVoiceBackend` (`backend/backends/qwen_custom_voice_backend.py:116`)
    uses the same `device_map=self.device` pattern.
- `Qwen3TTSModel.from_pretrained` forwards its kwargs **verbatim** to
  `AutoModel.from_pretrained` (`qwen_tts/inference/qwen3_tts_model.py:112`) —
  the docstring even shows `device_map="cuda:0"` as the intended usage. **Leading
  hypothesis:** passing a bare device string (`"cuda"`, `"mps"`, or a DirectML
  `torch.device` object) where the library/accelerate expects a valid
  `device_map` (or `device=`) is what trips the "GPU string" resolution. A
  related/known issue is [QwenLM/Qwen-Audio#85](https://github.com/QwenLM/Qwen-Audio/issues/85)
  — "qwen-tts runs on CPU even when GPU is specified" — i.e. device handling in
  `qwen-tts` is fragile either way. **The implementer should treat this as a
  hypothesis and confirm the exact error by reproducing the switch on a CUDA
  machine before and after the fix (§2.5).**

### 2.3 Why it only bites on some machines

`get_torch_device()` (`backend/backends/base.py:80`) is called with **different
flags per backend**, so the same machine yields different accelerators per
engine:

| backend | flags | on Apple Silicon | on CUDA box |
|---|---|---|---|
| qwen / qwen_custom_voice | `allow_xpu, allow_directml` (no `allow_mps`) | `cpu` | `cuda` |
| luxtts | `allow_mps, allow_xpu` | `mps` | `cuda` |
| chatterbox(_turbo)/tada | `force_cpu_on_mac, allow_xpu` | `cpu` | `cuda` |
| kokoro | `allow_mps=False` | `cpu` | `cuda` |

So a CUDA box passes `device_map="cuda"` into a path that wants a real
`device_map` (or `device=`). On the user's **MacBook** the Qwen engines land on
`cpu` (never MPS), which is *also* a silent bug: **Qwen never uses the Apple
GPU**, explaining why it's slow there. Switching to a GPU-expecting engine
exercises the broken `device_map` branch.

### 2.4 Spec

1. **Stop passing `device_map` as a bare device string.** In
   `pytorch_backend.py:116` and `qwen_custom_voice_backend.py:116`, replace
   `device_map=self.device` with the correct call for the library:
   - If `qwen_tts` accepts `device=` (preferred and simplest), pass
     `device=self.device` and drop `device_map`.
   - For multi-GPU / sharding we do **not** need `device_map`; a single-device
     `device=` is sufficient and avoids the accelerate GPU-string path.
2. **Centralize the fix.** Add a helper in `backend/backends/base.py` such as
   `build_model_kwargs(device, dtype) -> dict` that maps device → the correct
   `from_pretrained` kwargs per engine, and use it in every backend. This stops
   each backend from hand-rolling device handling.
3. **Let MPS actually be used where beneficial.** Decide per engine whether MPS
   is supported (it is for Qwen; confirmed usable) and relax
   `PyTorchTTSBackend._get_device` / `QwenCustomVoiceBackend._get_device` to
   `allow_mps=True`. Guard with a runtime probe so an MPS-incompatible op still
   falls back to CPU instead of crashing. (This is the "make it fast on a
   MacBook" lever for Qwen.)
4. **Surface the failure per engine.** When `from_pretrained` raises, the
   existing `model_load_progress` marks the task error (`base.py:284-288`) and
   `run_generation` writes `status="failed"` with `error=str(e)`; make sure the
   frontend's `useGenerationProgress` toast shows the engine name + the real
   reason (see §6), so "GPU string" becomes actionable ("Parakeet has no Metal
   path", etc.).
5. **Add a regression test** that constructs the kwargs for each engine's
   device and asserts a valid `from_pretrained` signature (no `device_map` when
   the library wants `device=`), and a test that switching engine A→B→C across
   the registry never passes a bare device string to `device_map`.

### 2.5 Verification required before implementing

The "GPU string" error is genuinely hard to reproduce without the exact
hardware. The implementer must:

1. Reproduce on the user's machine (or a CUDA box): load Qwen 1.7B via the
   normal generate path, then switch to a different engine/model and generate
   again; capture the full traceback (stderr logs via `GET /settings/logs` or the
   terminal).
2. Confirm whether the error is from `device_map`/`device=` in `from_pretrained`
   or from something else (e.g. the `qwen_tts` internal device probe, a DirectML
   object, or an MPS-only op).
3. Apply the minimal correct calling convention for the installed `qwen-tts`
   version (grep its installed source in the frozen/venv site-packages, not the
   upstream `main` branch — the pip version may differ).
4. Re-test the full A→B→C→A engine-switch cycle.

---

## 3. Unload-on-switch memory management

The user explicitly allows freely unloading models when not needed so only the
active engine occupies VRAM/RAM.

- Today `get_tts_backend_for_engine` caches a **singleton per engine**
  (`_tts_backends` dict, `backends/__init__.py:836`); each holds a loaded model
  forever. `load_engine_model` only unloads **the same engine's** model when
  changing size (`pytorch_backend.py:81`), so switching Qwen→Chatterbox leaves
  Qwen resident.
- **Spec:** introduce a single **"active engine"** policy at the service layer
  (`services/generation.py:run_generation` and the `load_engine_model` helper):
  before loading engine B, call `unload_model()` on the previously active TTS
  backend (track a global `_active_tts_engine`). Keep at most **one** loaded TTS
  engine at a time by default (configurable later).
- Add an "Unload" affordance already present per-model (`/models/{name}/unload`)
  and a global "Unload all" in the models pane; the pane should *show* which
  engine is currently loaded (from §1.3) so the user can act on it.
- Ensure `unload_model_by_config` (`backends/__init__.py:704`) is invoked on
  engine switch so `empty_device_cache` runs and VRAM is actually returned.

---

## 4. Stories tab overhaul

### 4.1 Current state (the "one big thing")

- Data model: `Story` → `StoryItem` → `Generation`
  (`backend/database/models.py:88-114`). `StoryItem` is a flat list with
  `start_time_ms` + `track`; there is **no chapter or segment grouping**.
- Backend: `backend/routes/stories.py` (CRUD + move/reorder/trim/split/duplicate
  /export) backed by `backend/services/stories.py`. `export_story_audio`
  mixes all items at their timecodes.
- Frontend: `StoriesTab` → `StoryContent.tsx` renders a **flat** sortable list
  of `SortableStoryChatItem` (+ `StoryTrackEditor` at the bottom).
- There is **no markdown import** today: the only import is audio
  (`/generate/import`, `routes/generations.py:417`).

This is why "one story is one big thing".

### 4.2 Target model (ElevenLabs-style hierarchy)

Add two optional levels above the clip, reusing the existing
`StoryItem`/`Generation`/`VoiceProfile` plumbing for the actual audio:

```
Story (exists)
 └── Chapter(s)                 [NEW StoryChapter]
      └── Segment(s)            [NEW StorySegment - a "chunk" of text + speaker]
           ├── text
           ├── speaker → VoiceProfile  (voice assignment)
           ├── engine/model (per segment, inherits default from profile)
           └── Generation/StoryItem    (the synthesized clip on the timeline)
```

Recommended DB additions (`backend/database/models.py`):

- `StoryChapter`: `id`, `story_id (FK)`, `title`, `source` (markdown slice),
  `order_index`, `created_at/updated_at`.
- `StorySegment`: `id`, `chapter_id (FK)`, `order_index`, `text`,
  `profile_id (FK, nullable → fallback to story default voice)`,
  `engine`, `model_size`, `language`, `status`
  (`draft|queued|generating|completed|error`), `generation_id (FK, nullable)`,
  `created_at/updated_at`.

The existing `StoryItem` continues to place the clip on the timeline; add
`story_segment_id` (nullable) to `StoryItem` so the timeline clip traces back to
its segment. This keeps all playback/mix/export logic working while giving the
new hierarchy. Backwards-compat: chapters/segments are **optional**; a story can
still be a flat list of items (imported/legacy).

### 4.3 Markdown import + segmentation dialog

New endpoint `POST /stories/{id}/import-markdown` (`routes/stories.py`),
service `services/stories.py`:

1. Accept the `.md` text (from `multipart/form-data` upload).
2. **Parse** into a heading tree (use an existing markdown parser; the repo
   already ships `markdown-it-py` transitively — verify, otherwise add
   `markdown-it-py`/`mistune`).
3. Return a **preview segmentation** to the client as a structured list so the
   user can confirm before anything is written:
   `{ chapters: [{ title, level, segments: [{ text, source_span, tags }] }] }`.
4. The **segmentation dialog** (frontend) offers modes:
   - **By H1** → one chapter per `#`, split children into segments.
   - **By H2** → one chapter per `##` (parents auto-promoted), split into segments.
   - **By paragraph** → each non-empty paragraph = a segment (flat, single chapter).
   - **Read-aloud tags** (see §4.4) — every region wrapped in a "read aloud"
     marker becomes a segment (used in combination with a heading mode).
   - A **"combine" threshold** (e.g. merge paragraphs under N chars) so we don't
     produce thousands of micro-segments.
5. On **confirm**, write `StoryChapter` + `StorySegment` rows, defaulting every
   segment's speaker to the story's default voice profile (or unassigned),
   and return the story detail.

### 4.4 Read-aloud tag → segment detection

The user's existing English Kokoro system auto-segmented on these markers.
Support a configurable set of `read-aloud` delimiters, e.g.:

- `[read aloud]` … `[/read aloud]` (block)
- `<readaloud>` … `</readaloud>`
- `[[read]]`/`[[/read]]`
- `<!-- read aloud -->` … `<!-- /read aloud -->`
- Single-line `[read aloud]: ...` / `> read aloud` tokens

Behavior:
- Text **inside** a read-aloud region becomes a **segment**.
- Optionally, a preceding **label** (e.g. the heading or the closest non-read
  line) becomes that segment's **name/title**, and a **speaker hint** parsed from
  the region's metadata (e.g. `[read aloud: narrator]`) pre-assigns a voice.
- Content **outside** any read-aloud region is kept as chapter context, not
  spoken (or, in "speak everything" mode, still segmented but flagged).
- Provide a checkbox: **"Treat untagged text as read-aloud too"** (default on for
  simple scripts, off for scripts that mark only some passages).

Make the tag set a settings value (`GenerationSettings` or a new `StorySettings`
singleton) so it can be tuned without a redeploy.

### 4.5 Per-segment speaker assignment

- Each `StorySegment.profile_id` picks the voice. The segment's `Generation`
  is created with `profile_id = segment.profile_id` and the engine/`model_size`
  from the profile (existing `routes/generations.py` `_resolve_generation_engine`
  + `create_voice_prompt_for_profile` already route on profile). So assigning a
  speaker is a **data** change, not a code change.
- UI: a **speaker dropdown per segment** in the editor (§4.6), listing voice
  profiles (with a small "…" to create/clone a voice from the source, mirroring
  the dubbing "create voice from source" idea).
- **Bulk assignment:** select multiple segments → assign one voice. Also a
  **"detect roles"** heuristic (optional, on by default for dialogue-style
  scripts): when a line matches `CharacterName: "..."` or `**Name:** ...`,
  auto-assign `CharacterName` to a voice profile (creating placeholder profiles
  if absent, or mapping via the existing `DubbingSpeaker`-style preset lookup).

### 4.6 Editor UX (the "much nicer visual editor")

Left rail (like ElevenLabs):
- **Chapter list** (reorderable, collapsible), each showing title + segment count
  + total duration.

Center pane (text-driven):
- Renders the chapter with its segments in document order.
- Each segment is a **card**: headline/speaker chip + a speaker dropdown + the
  editable text + a regenerate/replace affordance + a per-segment **"Generate"**
  and status badge (`draft/queued/generating/completed/error`). Editing text
  creates a new `Generation` (re-synth) rather than mutating history.
- Clicking a segment seeks the playhead to it and opens it in the timeline.

Bottom:
- Existing `StoryTrackEditor` (multi-track timeline) stays, now grouped by
  chapter (chapter headers on the ruler or in the track list).

Components to add/replace under `app/src/components/StoriesTab/`:
- `ChapterList.tsx` (left rail), `SegmentCard.tsx`, `SegmentSpeakerPicker.tsx`,
  `MarkdownImportDialog.tsx` (preview + split-mode picker),
  and a refactor of `StoryContent.tsx` to orchestrate chapters+segments →
  playback/export. Keep `StoryChatItem` for the legacy flat list.

### 4.7 API surface (additions)

```
GET    /stories/{id}                          # now includes chapters[] and segments[]
POST   /stories/{id}/import-markdown          # {markdown} → preview segmentation
POST   /stories/{id}/import-markdown/commit   # {chapters:[...]} → persist
POST   /stories/{id}/chapters                 # create chapter
PUT    /stories/{id}/chapters/{ch}            # rename / reorder
DELETE /stories/{id}/chapters/{ch}            # delete chapter + its segments
POST   /stories/{id}/segments                 # create segment
PUT    /stories/{id}/segments/{seg}           # edit text / speaker / engine
POST   /stories/{id}/segments/{seg}/generate  # synthesize this one segment
POST   /stories/{id}/segments/generate-many   # synthesize a range/whole chapter (queued, §6)
DELETE /stories/{id}/segments/{seg}
```

All respond with the updated story detail so the client can invalidate
`['stories', storyId]` once.

### 4.8 Backend files

- `backend/database/models.py` — add `StoryChapter`, `StorySegment`;
  add `story_segment_id` to `StoryItem`.
- `backend/database/migrations.py` / alembic — add the migration (the codebase
  uses a hand-rolled `migrations.py`; follow its conventions).
- `backend/models.py` — add the Pydantic response/request schemas.
- `backend/services/stories.py` — markdown parse/segment service (reuse the
  heading/`read-aloud` logic), chapter/segment CRUD, "generate segment(s)".
- `backend/routes/stories.py` — the new endpoints.
- `backend/services/generation.py` — a `generate_segment(segment)` wrapper that
  calls `run_generation` with the segment's profile/engine/text and links the
  resulting `Generation` back to the `StoryItem`/`StorySegment`.

### 4.9 Frontend files

- `app/src/lib/api/types.ts` — `StoryChapter`, `StorySegment` types;
  extend `StoryDetailResponse`.
- `app/src/lib/api/models/` — request/response model files + client methods.
- `app/src/components/StoriesTab/*` — the editor components listed above.
- `app/src/lib/hooks/useStories.ts` — new hooks for the import/segment endpoints.

---

## 5. Timeline snapping defects (investigation)

Reviewed `app/src/components/StoriesTab/StoryTrackEditor.tsx`.

### 5.1 Findings

1. **There is no snapping at all in clip drag/drop.** `handleDragEnd`
   (`:891-935`) computes
   `newTimeMs = Math.max(0, Math.round(pixelsToMs(dragPosition.x)))`
   (`:904`) — a raw pixel→ms conversion with no grid snap, no snapped
   increments, and no snapping to adjacent clip edges. A dropped clip lands
   exactly where the pointer is (subject to the label-offset arithmetic), which
   reads as "snapping to weird positions."
2. **The drop coordinate math is fragile.** It subtracts `LABEL_COL_WIDTH` (64),
   `TIME_RULER_HEIGHT` (24), and a pointer-anchored `dragOffset` from
   container-relative positions (`:862-868`, `:877-884`) and clamps x to ≥ 0
   during move (`:886`). If the container's scroll/label geometry changes (or a
   clip is near the label edge), the final `dragPosition.x` maps to an
   unexpected time. There is no validation against the *actual* rendered clip
   left position after the drop.
3. **No overlap / collision handling.** `moveItem.mutate` (`:913`) sends
   `start_time_ms` + `track` straight to the backend
   (`backend/services/stories.py:move_story_item`), which does **zero**
   collision detection — so two clips can fully overlap on one track, and the
   timeline renders them stacked. Combined with (1), the "snapping" feels broken.
4. **Trim uses raw `pixelsToMs` too** (`:599-640`) with no snap; `split` uses
   `mean` playhead time (`:696`). These are less common but share the no-snap
   design.
5. **Backend time math is int ms; frontend uses floats** — e.g. `split` rounds
   (`:696`) but `handleDragEnd`/timecodes are float ms that the DB holds as
   `Integer`. Rounding at the boundary is inconsistent (some paths round, some
   don't).

### 5.2 Spec (targeted fixes; not a rewrite)

- Add a **snap constant** (e.g. `SNAP_MS = 100`, and a "snap to clip edges" when
  within N px of another item's start/end on the target track), and a helper
  `snapTime(ms, snapSet)` used by drop (`handleDragEnd`), trim, and split.
- **Fix the drop mapping** by computing the target time from the clip's own
  rendered geometry (the dragged element's `clientX` relative to the tracks
  container), not from accumulated `dragPosition + LABEL_COL_WIDTH` offsets, so
  what the user sees is what lands.
- Add **collision resolution**: in `move_story_item`
  (`backend/services/stories.py:334`), when moving to a `track`+`start_time`,
  reject or nudge the placement if it overlaps an existing item's
  `[start, start+duration)` range, returning a clear error (or auto-shift by
  one gap).
- Normalize all FE↔BE time math to **integer ms** at the API boundary (already
  `int` in the schema for `start_time_ms`/`trim_*`); add a consistent
  `Math.round` at the last FE step so FE preview matches BE storage.
- If the timeline continues to feel buggy after the targeted fixes, the reviewer
  should consider a rebuild on a proven dnd+zoom lib (e.g. `react-timeline` /
  dnd-kit), but **do not rewrite for this task** — the user deprioritized the
  timeline.

---

## 6. Generation queue visibility + progress

### 6.1 Root cause

- Backend serializes all TTS in a single queue
  (`backend/services/task_queue.py:_generation_worker`), one job at a time, with
  `_queued_generation_ids` + `_running_generation_tasks` kept **in memory only**.
- The only per-generation feed to the client is
  `GET /generate/{id}/status` (`backend/routes/generations.py:275`), which polls
  the DB each second and emits **only** `{ id, status, duration, error, source }`.
  There is **no `queued` vs `running` field, no progress %, no chunk count, and
  no sampling %**.
- The frontend subscribes per pending id via `useGenerationProgress`
  (`app/src/lib/hooks/useGenerationProgress.ts`) and only cares about
  `completed`/`failed`. There is **no queue list UI** and **no progress bar**;
  the only affordance is the `pendingCount` pill linking to `/`
  (`StoryContent.tsx:374-395`) and per-row spinners in the history table.
- The "sampling percentage" the user sees in the terminal comes from the
  engine's own tqdm/progress output (e.g. `transformers`/`qwen_tts` sampling
  loop), which is **never** captured or forwarded.

### 6.2 Spec

1. **Expose the queue.** Add `GET /generate/queue` returning an ordered list:
   `[{ generation_id, profile_id, text_preview, state: queued|running, progress,
   enqueued_at }]`. Source it from `task_queue.py` (add a lock-protected snapshot
   over `_queued_generation_ids` + `_running_generation_tasks` + the
   `TaskManager._active_generations`), and optionally a running index.
   Poll it (or subscribe via a shared SSE channel) from the frontend.
2. **Add real progress to the status payload.** Extend `GET /generate/{id}/status`
   to also send `state` (`queued|loading_model|generating`), `progress` (0..1),
   `chunk_index`, `chunk_count`, and `message` (e.g. "Synthesizing chunk 3/12").
   Feed it from a new progress channel in the backend:
   - Add `update_generation_progress(generation_id, percent, chunk, message)` to
     `TaskManager` or a new `GenerationProgress` registry, called from
     `services/generation.py:run_generation` **around** `generate_chunked`, and
     ideally from within `generate_one` (`chunked_tts.py:253`) so each chunk
     advances the bar.
   - If we can capture the engine's own sampling callback, forward that too;
     otherwise emit a **chunk-level** progress (per chunk start/finish) which is
     the honest, achievable signal for all engines.
3. **UI — a global queue/progress panel.** A dismissible bottom sheet or an
   indicator row (reachable from the `pendingCount` pill) that lists, in order:
   each queued/running clip with its text preview, a per-item progress bar
   (`loading_model` → indefinite; `generating` → `%`), and a **total
   aggregate** (e.g. "3/12 segments — 38%"). Place it in `AppFrame`
   (`app/src/components/AppFrame/`) so it is available on every route.
4. **Wire the toast/status.** In `useGenerationProgress`, surface `progress`
   updates so the pill/panel update live; keep the existing completion/autoplay
   behavior.
5. **Tests:** assert `GET /generate/queue` reflects queued vs running and that
   status includes `state`+`progress`; assert progress advances per chunk for a
   multi-chunk generation.

---

## 7. Faster German TTS models

### 7.1 Truth about the options (corrected)

Recent research (with citations in §7.5) corrects the working assumption that
"Kartoffelbox is German Kokoro". It is **not**:

- **Kartoffelbox is a German fine-tune of ResembleAI `chatterbox`** (base 500M+)
  and **`Kartoffelbox_Turbo` is a fine-tune of `chatterbox-turbo` (350M)**. It is
  **not** Kokoro-based. Both PyTorch repos are **gated** (HF auth required);
  un-gated `cstr/kartoffelbox-turbo-GGUF` mirrors confirm the architecture.
- **Kokoro official (`hexgrad/Kokoro-82M`) has NO German.** Its `VOICES.md`
  lists no `de`. German requires **community re-trains**:
  `dida-80b/kokoro-german-hui-multispeaker-base` (German re-train of Kokoro-82M)
  + `kikiri-tts/kikiri-german-victoria` / `...-martin` voicepacks (voice ids
  `df_victoria`, `dm_martin`). The **official English model collapses to silence
  on long German utterances** — the German base is mandatory.
- **Qwen3-TTS-0.6B** (`Qwen/Qwen3-TTS-12Hz-0.6B-Base`) fully supports German (10
  langs incl. `de`) and shares the **exact same API** as 1.7B
  (`Qwen3TTSModel.from_pretrained(...).generate_voice_clone(...)`).

Relative cost (measured RTF, GPU, [Qwen3-TTS report](https://ar5iv.labs.arxiv.org/html/2601.15621)):

| engine | GPU RTF (conc 1) | Apple Silicon | memory | fits Voicebox `.generate(text, voice_prompt, language)`? |
|---|---|---|---|---|
| Qwen3-TTS **0.6B** | **0.288** | ~0.28 (Metal M4) / ~0.52 (CPU M1, int4) | ~3 GB | ✅ yes |
| Qwen3-TTS **1.7B** | 0.313 | ~0.44 GPU / CPU-only today | ~8 GB | ✅ yes |
| Kokoro-82M (German base) | sub-realtime, CPU realtime | CPU realtime | 82M (~150 MB) | ❌ no (`KPipeline` + `voice=`) |
| Kartoffelbox Turbo | low-latency (350M) | n/a (no published RTF) | ~1 GB | ❌ no (patch-load + `audio_prompt_path=`) |
| Piper (de) | well under realtime | CPU realtime | per-voice ONNX | ❌ no (CLI/ONNX) |

Key insight: **Qwen 0.6B is only ~8–10% faster than 1.7B at RTF**, but on a
MacBook the current 1.7B runs on **CPU** (§2.3) — so the real-world win comes
**much less from dropping to 0.6B than from letting Qwen use the Apple GPU**
(the §2.4 MPS fix). Combined, 0.6B + MPS is the biggest reliable speedup.

### 7.2 Recommended additions (prioritized)

**(a) PRIMARY — Qwen3-TTS-0.6B (+ the §2.4 MPS fix).**
Lowest risk, biggest real win. It is already a registered config
(`backends/__init__.py:346`), fully supports German, and is the same API so the
integration is a default-voice/engine change, not a new backend. On Apple
Silicon make it use MPS (per §2.4) so German synthesis leaves CPU. This is the
drop-in "fast German default" the user should get first.

**(b) SECONDARY — dedicated German Kokoro turbo engine.**
Fastest quality/speed (82M, CPU-realtime, Apache-2.0), but German is
community-only and Kokoro's API (`KPipeline(lang_code)` + `voice=`, no
`voice_prompt`/`language`) does **not** match Voicebox's `TTSBackend.generate`
contract. Add it as a new backend using `kokoro-german-hui-multispeaker-base` +
the `kikiri-tts` voicepacks (`df_victoria` default, `dm_martin`), and expose the
German voices as **preset profiles** (`voice_type="preset"`,
`preset_engine="kokoro"`, `preset_voice_id="df_victoria"` etc.). Do **not**
reuse the English `hexgrad` model for German.

**(c) TERTIARY / EXPERIMENTAL — Kartoffelbox Turbo.**
Most "German-native" fast option (350M), but: the PyTorch repos are **gated**,
training diverged (experimental, paralinguistic tags likely broken), and it needs
a **patch-load** (load the base chatterbox-turbo, then apply the downloaded
`t3_cfg.safetensors` state dict) instead of plain `from_pretrained`. Its
`.generate` uses `audio_prompt_path=` (not `voice_prompt`). Do **not** treat this
as a drop-in. Only pursue if the user wants to accept a gated, experimental
model to ride the existing `chatterbox_turbo_backend.py`.

### 7.3 Integration process

Adding a new **engine** (German Kokoro or Kartoffelbox) must follow the
project's `add-tts-engine` skill and `docs/content/docs/developer/tts-engines.mdx`
— **Phase 0 dependency audit is mandatory** (the v0.2.3 release regressed by
skipping it). Files touched:

- `backend/backends/<engine>_backend.py` (+ register in `backends/__init__.py`:
  `ModelConfig`, `TTS_ENGINES`, factory).
- `backend/requirements.txt`, `justfile` setup targets, `.github/workflows/release.yml`,
  `Dockerfile`, and PyInstaller bundling in `backend/build_binary.py` +
  `backend/server.py`.
- Frontend: `lib/api/types.ts` (engine union), `constants/languages.ts`,
  `Generation/EngineModelSelector.tsx`, `hooks/useGenerationForm.ts`,
  `ServerSettings/ModelManagement.tsx`.

For the gated Kartoffelbox repos, add a `needs_token` flag (§1.3) and surface a
"log in with HF token" hint; for the community Kokoro base, add an entry to the
voice roster.

**Recommendation:** implement **(a) Qwen 0.6B + MPS** first (immediate, low risk,
meaningful speedup on the MacBook), then **(b) German Kokoro** as the dedicated
"turbo German" engine if quality is acceptable, and treat **(c) Kartoffelbox
Turbo** as an experimental option pending the user's appetite for a gated model.
Verify realtime factors on the actual target machine before committing — RTF is
hardware-specific.

### 7.4 Open questions for the reviewer

- Confirm Qwen 0.6B German quality vs 1.7B on a short ABX before making it the
  default.
- Confirm the `kikiri-tts` voicepack licenses and which voices to ship; verify the
  q8 GGUF floor (q4 reportedly breaks German).
- Whether to make Qwen 0.6B the global default German engine, or keep 1.7B and
  only add Kokoro/Kartoffelbox as an explicit choice.
- Gate handling: does the user have an HF token wired for the gated Kartoffelbox
  and pyannote repos?

### 7.5 Sources

- Kartoffelbox: [SebastianBodza/Kartoffelbox-v0.1](https://huggingface.co/SebastianBodza/Kartoffelbox-v0.1)
  (gated, `library_name: chatterbox`), [Kartoffelbox_Turbo](https://huggingface.co/SebastianBodza/Kartoffelbox_Turbo)
  (350M chatterbox-turbo fine-tune), [cstr/kartoffelbox-turbo-GGUF](https://huggingface.co/cstr/kartoffelbox-turbo-GGUF)
  (architecture mirror).
- Chatterbox: [ResembleAI/chatterbox](https://github.com/resemble-ai/chatterbox),
  [Chatterbox Turbo 350M](https://github.com/resemble-ai/chatterbox/commit/bc58894bb85e50df6439abe5b81af2e2527e9274),
  [chatterbox-finetuning-multilingual](https://github.com/Ahmed-Ezzat20/chatterbox-finetuning-multilingual).
- Kokoro German: [hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)
  (VOICES.md — no German), [dida-80b/kokoro-german-hui-multispeaker-base](https://huggingface.co/dida-80b/kokoro-german-hui-multispeaker-base),
  [cstr/kokoro-de-hui-base-GGUF](https://huggingface.co/cstr/kokoro-de-hui-base-GGUF),
  [cstr/kokoro-voices-GGUF](https://huggingface.co/cstr/kokoro-voices-GGUF),
  [semidark/kokoro-deutsch](https://github.com/semidark/kokoro-deutsch).
- Qwen3-TTS: [Qwen/Qwen3-TTS-12Hz-0.6B-Base](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base),
  [Qwen3-TTS Technical Report (RTF table)](https://ar5iv.labs.arxiv.org/html/2601.15621),
  [gabriele-mastrapasqua/qwen3-tts (Apple Silicon RTF)](https://github.com/gabriele-mastrapasqua/qwen3-tts),
  [HaujetZhao/Qwen3-TTS-GGUF](https://github.com/HaujetZhao/Qwen3-TTS-GGUF).

---

## 8. Cross-cutting risks / notes

- **Backwards compatibility** of the story model is critical: existing stories
  have no chapters/segments. Keep `StoryChapter`/`StorySegment` optional and
  render the legacy flat list when absent.
- **Queue/progress** must not slow the hot path: never block TTS inference on a
  lock; the progress registry should be enqueue-only and read by a separate
  endpoint.
- **Device handling** (§2) touches every backend; the centralized helper + tests
  are what prevent regressions.
- Every FE↔BE `ms` value should be `int` at the boundary to avoid drift (§5.1.5).
- Adding an engine requires the full `add-tts-engine` checklist. The German
  recommendation is deliberately scoped so the first step (**Qwen 0.6B + MPS**)
  is a config/device change with **no** new backend; any genuinely new engine
  (German Kokoro / Kartoffelbox) must implement Voicebox's `TTSBackend.generate`
  contract — neither matches it today, so each needs a dedicated backend (and
  Kartoffelbox additionally a gated patch-load).
- **`TTSBackend.generate` contract recap** (for the implementer):
  `generate(text, voice_prompt: dict, language, seed, instruct) -> (np.ndarray, sr)`.
  Engines that instead take a voice id (`Kokoro KPipeline`) or an audio path
  (`Kartoffelbox`) must be adapted inside their backend (map a preset
  `voice_prompt` to a `voice=` / `audio_prompt_path=`), not by changing the
  protocol.
