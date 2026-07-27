# Code Quality Audit — 2026-07-26

Four parallel reviews of the codebase at `0.6-dictation-fixes` (`88e72d5`): Python backend, React frontend, Tauri/Rust shell, and CI/repo hygiene. Line references are against that tree. A follow-up section at the bottom lists what was fixed the same day.

**Scope:** first-party code only (~20k LOC Python, ~29k LOC TypeScript, ~6k LOC Rust, ~4.4k LOC backend tests).

| Area | Grade | One-liner |
|------|-------|-----------|
| Python backend | B | Well-layered local-inference server with above-average concurrency engineering; test hygiene and ~1,000 self-inflicted lint violations drag it down |
| React frontend | B | Strict typing and clean state architecture; zero tests and 1,748 lines of dead generated API client |
| Tauri/Rust shell | B− | The dictation/clipboard FFI is excellent; `main.rs` god-file and audio modules a tier below |
| CI / repo hygiene | B− | Strong release engineering and docs; PR gate was typecheck + web build only |

**Consensus:** the hard 10% — GPU lifecycles, clipboard/focus FFI, release packaging — is done unusually well. The gap to A-territory is verification: broken test hygiene, a near-empty CI gate, and second-tier modules that never got the rigor of the flagship paths.

---

## Python backend — B

`main.py` is 45 lines; the routes-refactor (commit `88536d2`) split routes into 21 domain modules under `routes/`, with real layering: routes → services → backends → database. (`PROJECT_STATUS.md` still described the pre-refactor 2,850-line god-file.)

### Strengths

- **MLX serialization** (`services/mlx_thread.py`): single-worker executor with a docstring explaining why (Metal streams are thread-local, issue #699). Load-and-infer submitted as one job so unload can't interleave (`backends/mlx_backend.py:270-274`).
- **Serial generation queue** (`services/task_queue.py`): distinguishes cancel-while-queued vs cancel-while-running (`:105-117`), keeps background-task references against GC (`:31-36`), force-fails orphaned DB rows when the worker dies mid-write (`:69-93`), with matching route-layer recovery (`routes/generations.py:245-259`) and real behavioral tests.
- **Shared backend plumbing** (`backends/base.py`): centralized HF cache checks, device detection, CUDA compute-capability validation with actionable errors, and a `model_load_progress()` context manager all 7 engines use (`:234-295`).
- **Lifespan care**: FastAPI + FastMCP lifespans composed with an explicit LIFO-teardown comment (`app.py:134-151`); startup marks stale `generating` rows failed after a crash (`app.py:295-303`).
- **Hardening details**: RFC 5987 filenames (`app.py:112-120`), SPA path-traversal guard (`app.py:219-225`), upload limits enforced while streaming (`routes/generations.py:422-434`), documented float64→float32 patches for upstream chatterbox bugs (`backends/base.py:298-332`).
- Comments cite issues and explain decisions (no-Alembic rationale in `database/migrations.py:1-18`).

### Weaknesses

- **Broken test file committed**: `tests/test_profile_duplicate_names.py` imported the pre-refactor layout and killed collection — nobody ran the suite green since the routes refactor. *(fixed, see follow-up)*
- **No `conftest.py`**; six files did per-file `sys.path` hacks, making tests order-dependent. *(fixed)*
- **`test_cors.py` tested a hand-copied mirror** of the origin list that had already drifted from `app.py` (missing `http://tauri.localhost`). *(fixed — now uses the real `create_app()`)*
- **API routes untested**: no TestClient coverage of `/generate`, `/profiles`, `/stories`; the retry/regenerate/cancel state machine in `routes/generations.py` has zero coverage.
- **~1,000 ruff violations** against its own config. *(auto-fixed ~900; remainder baselined in `pyproject.toml` — see follow-up)*
- **Silent clone degradation**: `mlx_backend.py:252-257` catches any generate exception and retries without the voice prompt — the user gets the default voice and the generation records as successful. **Open.**
- **Inconsistent load-race protection**: Chatterbox/Hume double-check with an `asyncio.Lock`; Kokoro (`kokoro_backend.py:156-160`) and LuxTTS (`luxtts_backend.py:65`) don't. `get_stt_backend` (`backends/__init__.py:739-753`) unlocked while TTS/LLM factories are locked. **Open.**
- **SQLite has no WAL / busy_timeout** (`database/session.py:37-40`) while the code works around "SQLite lock racing" in two places. Backlog PRs #666/#667 add exactly this. **Open.**
- **Registry didn't deliver on its promise**: `backends/__init__.py` still has five per-engine if/elif chains (`:513-656`); adding an engine touches at least four places. **Open.**
- Assorted: 46 deprecated `datetime.utcnow()` calls, 14 Pydantic v1-style `class Config` blocks, pervasive defensive `getattr()` on own ORM columns, `except Exception: pass` on corrupt effects-chain JSON (`routes/generations.py:122-124`).

---

## React frontend — B

`web/` is not a duplicate: 182 LOC of platform adapters injecting a `Platform` interface via `PlatformProvider` (`app/src/platform/PlatformContext.tsx`), with the entire app shared through a Vite alias. Best structural decision in the frontend.

### Strengths

- **Typing discipline**: strict mode + `noUnusedLocals/Parameters`; exactly one `as any` in ~29k LOC (`AudioPlayer.tsx:183`).
- **State architecture**: server state in 19 react-query hooks, client state in 8 small zustand stores; persistence partialized so audio drafts never hit localStorage (`uiStore.ts:100-103`).
- **`useAudioRecording.ts`** is genuinely strong concurrency work: generation counters for stale `getUserMedia` results, coalesced in-flight acquisition, deferred release during capture, with comments explaining why.
- Every mutation has an `onError` toast; `ProfileForm` does client-side rollback with rollback-failure reporting (`:709-739`).

### Weaknesses

- **Zero tests, zero test tooling** — riskiest for the pixel-math in `StoryTrackEditor.tsx` trim/zoom (`:595-640`, `:1035-1065`), the 4-branch `onSubmit` state machine in `ProfileForm.tsx` (`:491-754`), and Web Audio scheduling in `useStoryPlayback.ts`. **Open.**
- **1,748 lines of dead generated API client** (`app/src/lib/api/{core,models,schemas,services}`) imported by nothing, with stale types (missing `engine`, `personality`, `effects_chain`) sitting beside the real hand-written client. Delete it or commit to codegen. **Open.**
- **`client.ts` DRY violations**: the same `if (!response.ok)` multipart block copy-pasted ~11 times; `useStories.ts:79-229` is 12 near-identical mutation hooks. **Open.**
- **35 `console.log` calls in production paths** (model download, story store, SSE lifecycle) despite an unused `debug.ts` gate. **Open.**
- **i18n two-thirds done**: 6 locales ship but ~24 feature components are hardcoded English, including all of `StoryTrackEditor`, `AudioPlayer`, `DictateWindow`. **Open.**
- **Effect hygiene**: `ClipWaveform` recreates WaveSurfer (re-fetching audio) on every zoom step; `getEffectiveDuration` recreated per render defeats the memos that list it; `App.tsx:218-225` failure timeout never cancelled; three dead `eslint-disable` comments in a biome repo. **Open.**
- **God components**: `ProfileForm.tsx` (1,317), `ModelManagement.tsx` (1,102 — embeds a 75-line SSE migration workflow in a JSX `onClick`, categorizes models by name-prefix string match), `HistoryTable.tsx` (915), `CapturesTab.tsx` (909). `StoryTrackEditor.tsx` (1,531) is coherent but is three components in one file. **Open.**

---

## Tauri/Rust shell — B−

Two codebases live here. The dictation/paste path is disciplined, documented, RAII-guarded FFI; the server-lifecycle half of `main.rs` and both audio modules are a tier below.

### Strengths

- **`clipboard.rs`**: full-fidelity multi-format snapshot/restore on both platforms, RAII guards throughout, correct HGLOBAL ownership semantics (`:548-563`). Conditional restore keyed on `NSPasteboard.changeCount` / `GetClipboardSequenceNumber` (`main.rs:1411-1421`) correctly yields to clipboard managers writing mid-paste.
- **`keyboard_layout.rs`**: Dvorak/AZERTY Cmd+V via `UCKeyTranslate` + input-source-change observer; hot path reads one `AtomicU16`.
- **`input_monitoring.rs:42-58`**: declares `IOHIDCheckAccess` as `c_uint` not `bool` with a comment explaining the UB risk — exemplary FFI care.
- **`focus_capture.rs`**: macOS 14 cooperative-activation handled with a cached `respondsToSelector:` probe; refused activation aborts before clobbering the clipboard (`:325-331`).
- **Hotkey lifecycle**: single dispatcher thread serializes Start/Stop/Restart; shutdown is flag + join (`hotkey_monitor.rs:102-136`); focus snapshotted before any window mutation.

### Weaknesses

- **`main.rs` god-file** (1,828 lines): NSPanel surgery + ~660 lines of sidecar process management + paste pipeline + app builder; `start_server` is 560 lines with the dev-mode fallback copy-pasted three times. `lib.rs:1` declares a vestigial duplicate `audio_capture` module. **Open.**
- **Blocking calls in async commands**: `reqwest::blocking::Client` inside async `stop_server` (`main.rs:993-1000`); blocking health checks and `thread::sleep` inside async `start_server`. **Open.**
- **`println!` logging with per-packet spam**: `audio_output.rs:217` logs every decoded packet; no `log`/`tracing` facade anywhere. **Open.**
- **`audio_output.rs` bugs**: stop-flag set-then-reset race a 10 ms poll can miss (`:105-108` vs `:413-419`); "multi-device" playback is actually serial (`:111-117`); `resample` is sample-and-hold while the comment claims linear interpolation (`:268`). **Open.**
- **`audio_capture/` copy-paste divergence**: `samples_to_wav` triplicated verbatim; all three `stop_capture`s do `let _ = tx.send(())` on a *tokio* mpsc sender — the future is dropped and the signal never sent (works only because dropping the sender closes the channel); Windows stop is a fixed 500 ms sleep that can truncate the tail; `linux.rs:113` calls `env::set_var` from a spawned thread (the setenv data race that is `unsafe` in Rust 2024) and never unsets it; Windows/macOS assume Float32 sample format unchecked. **Open.**
- **Plausible deadlock**: sync `enable_hotkey`/`disable_hotkey` run on the main thread and join the dispatcher while holding the state lock (`hotkey_monitor.rs:108-111`); the dispatcher's effect path does main-thread round-trips (`:252-260`). Marking the commands async closes it. **Open.**
- **`start_server` TOCTOU on itself**: `child.is_some()` guard and store separated by multiple awaits — two concurrent invocations double-spawn. **Open.**

---

## CI / repo hygiene — B−

### Strengths

- **Release pipeline** (`release.yml`, 404 lines): 3-platform matrix, changelog extraction, Tauri updater JSON, DMG notarization + staple with `spctl` verification, SHA-pinned third-party action with written rationale, checksummed CUDA/ROCm sidecar archives with torch-compat metadata.
- **Developer docs**: `docs/content/docs/developer/tts-engines.mdx` (703 lines) with a mandatory dependency-research phase built from real scar tissue. 4,022 lines of MDX across 14 files.
- **justfile**: fully cross-platform including native PowerShell, GPU auto-detection for CUDA/ROCm torch indexes, venv guards.
- **Security claims check out**: server binds `127.0.0.1` by default, CORS is a real allowlist with a test, Docker binds host port to `127.0.0.1`.
- Tracked-file state clean: 671 files, no venvs/worktrees/data tracked.

### Weaknesses

- **PR gate was ~15 effective lines**: typecheck + web build. No biome, no ruff, no pytest, no cargo check — the entire 27-file backend suite ungated. This is how 100+ unverifiable PRs pile up. *(fixed, see follow-up)*
- **`.gitignore` tail was UTF-16LE** — the `.claude/settings.local.json` pattern was garbage bytes git can't parse; the whole file was CRLF. *(fixed)*
- **Unpinned git dependencies**: `linacodec` and `Zipvoice` (`backend/requirements.txt:21-22`, third-party personal account) and `Qwen3-TTS` (justfile, Dockerfile) have no commit pins — a force-push upstream silently changes what every release ships. The single biggest supply-chain exposure. **Open.**
- **Stale contributor docs**: `CONTRIBUTING.md` references a nonexistent autoupdater doc, Black instead of ruff, Python 3.11+, `com.voicebox.app`, and the pre-refactor layout. `SECURITY.md` says 0.3.x is the supported version. **Open.**
- **Vestigial root `requirements.txt`**: 9 unpinned lines including unused `torchvision`; nothing references it; it exists to mislead. **Open.**
- **`backend/pyproject.toml` version stuck at 0.2.3** — missing from `.bumpversion.cfg`. **Open.**
- `build-windows.yml` uses floating `tauri-action@v0` and a hardcoded stale release body. Release `bun install` isn't `--frozen-lockfile` while CI is. Two venvs (`backend/venv` + `backend/.venv`) on dev machines. **Open.**

---

## Priorities

1. ~~CI: biome + ruff + pytest + cargo check on every PR~~ *(done 2026-07-26)*
2. ~~Pin the three git deps to commit SHAs~~ *(done 2026-07-26)*
3. ~~Fix the silent voice-prompt fallback in `mlx_backend.py`~~ *(done 2026-07-26)*
4. ~~Delete the dead generated API client (1,748 LOC)~~ *(done 2026-07-26)*
5. `audio_capture`/`audio_output` rigor pass (dropped futures, stop races, `set_var`)
6. ~~SQLite WAL + busy_timeout~~ *(done 2026-07-26)*
7. ~~Refresh `CONTRIBUTING.md` / `SECURITY.md`; delete root `requirements.txt`~~ *(done 2026-07-26)*
8. Frontend test tooling + first unit tests for the pure pixel-math functions *(in progress)*
9. Burn down the ruff/biome baselines (tracked in `backend/pyproject.toml` and `biome.jsonc`)

---

## Follow-up — fixed 2026-07-26

Same-day fixes landed on `0.6-dictation-fixes`:

- **CI** (`.github/workflows/ci.yml`): added biome lint to the frontend job, a `backend-quality` job (macOS arm64: `just setup-python`, `ruff check`, `pytest`), a `rust-quality` job (`cargo check` with stub sidecars), and concurrency cancellation.
- **Tests green**: fixed `test_profile_duplicate_names.py` imports, added `tests/conftest.py` (kills the order-dependence), rewrote `test_cors.py` against the real `create_app()` factory (now covers `http://tauri.localhost`), fixed the stale 1,000-byte simulation in `test_progress.py` (tracker's 1 MB reporting threshold). Suite: 134 passed, 2 skipped.
- **Ruff green**: ~900 violations auto-fixed; remaining 151 baselined in `pyproject.toml` with per-rule counts and per-file carve-outs for deliberate env-before-import patterns.
- **Biome green**: `biome.json` → `biome.jsonc` with the failing rules baselined at `warn` (annotated against issue #421); scanner ignores `.worktrees/` so local worktrees no longer break `bun run lint`.
- **Real bug fixed**: `pyi_rth_numpy_compat.py` referenced `_t` before binding, so the `NameError` was swallowed by `except Exception: pass` and the torch `from_numpy` patch silently never applied in frozen builds.
- **`.gitignore`**: rewritten as UTF-8/LF; added `.worktrees/`, `.hermes/`, `mlx-test/`.
- **Git deps pinned to commits**: `linacodec@c0ae7c7` and `Zipvoice@381b160` (the commits resolved in the working venv) in `backend/requirements.txt`; `Qwen3-TTS@022e286` (upstream HEAD, verified as the installed 0.1.1) in the justfile and Dockerfile.
- **Dead generated API client deleted** (~1,750 LOC): `app/src/lib/api/{core,models,schemas,services,index.ts}`, plus its generator (`scripts/generate-api.sh`, the `generate:api` script, the `just generate-api` recipe) and the doc sections describing the codegen workflow. The client is hand-written in `client.ts`/`types.ts`; docs now say so.
- **Voice-prompt fallback removed** (`mlx_backend.py`): a cloning failure now fails the generation with the real error instead of silently retrying with the model's default voice; the empty-audio-as-success path and the silent no-`ref_audio`-parameter fallback raise too.
- **Load races closed**: Kokoro and LuxTTS `load_model` now double-check under an `asyncio.Lock` (same pattern as Chatterbox); `get_stt_backend` got the lock the TTS/LLM factories already had.
- **SQLite hardened** (`database/session.py`): WAL journal mode + `synchronous=NORMAL` via connect listener, 30 s busy timeout via `connect_args` — mitigates the lock racing the orphan-recovery machinery works around.
- **Hotkey deadlock closed**: `enable_hotkey` / `disable_hotkey` / `update_chord_bindings` are now async commands, so joining the dispatcher no longer happens on the main thread the dispatcher may be waiting on.
- **Docs refreshed**: `CONTRIBUTING.md` (ruff not Black, Python 3.12, `sh.voicebox.app`, real backend layout, real testing story, fixed autoupdater link), `SECURITY.md` (0.5.x supported; describes actual CI enforcement), root `requirements.txt` deleted (two stale references repointed at `backend/requirements.txt`), `backend/pyproject.toml` version synced to 0.5.0 and added to `.bumpversion.cfg`.
