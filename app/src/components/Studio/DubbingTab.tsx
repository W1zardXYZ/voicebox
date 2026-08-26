import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import {
  apiClient,
  type DubbingProject,
  type DubbingSegment,
  type DictionaryEntry,
} from '@/lib/api/client';

/** Dubbing Studio — create a project from a media upload, run the pipeline,
 *  inspect/edit segments, manage pronunciations, and play the dubbed track. */
export function DubbingTab() {
  return (
    <div className="flex h-full min-h-0 flex-col gap-4 overflow-y-auto p-6">
      <div>
        <h1 className="text-xl font-bold">Dubbing Studio</h1>
        <p className="text-sm text-muted-foreground">
          Transcribe → diarize → translate → synthesize a media file in a target language.
        </p>
      </div>

      <StudioSection />
      <DictionaryPanel />
    </div>
  );
}

function StudioSection() {
  const queryClient = useQueryClient();

  const projectsQuery = useQuery({
    queryKey: ['dubbing-projects'],
    queryFn: () => apiClient.listDubbingProjects(),
  });

  const [selectedId, setSelectedId] = useState<string | null>(null);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['dubbing-projects'] });
    if (selectedId) void queryClient.invalidateQueries({ queryKey: ['dubbing-project', selectedId] });
    if (selectedId) void queryClient.invalidateQueries({ queryKey: ['dubbing-segments', selectedId] });
  };

  return (
    <>
      <CreateProjectForm onCreate={invalidate} />

      {selectedId ? (
        <ProjectPanel
          projectId={selectedId}
          onBack={() => setSelectedId(null)}
          onChanged={invalidate}
        />
      ) : (
        <ProjectList
          projects={projectsQuery.data ?? []}
          loading={projectsQuery.isLoading}
          onSelect={setSelectedId}
        />
      )}
    </>
  );
}

/** Pronunciation dictionary (IPA / phonemes) — ported from DUBBERc's Settings UI. */
function DictionaryPanel() {
  const queryClient = useQueryClient();
  const dictQuery = useQuery({
    queryKey: ['dictionary'],
    queryFn: () => apiClient.listDictionary(),
  });
  const [word, setWord] = useState('');
  const [phonemes, setPhonemes] = useState('');
  const [lang, setLang] = useState('ALL');
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const entries = dictQuery.data ?? [];
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['dictionary'] });

  const add = async () => {
    if (!word.trim() || !phonemes.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      await apiClient.upsertDictionaryEntry({ word, phonemes, language: lang, notes });
      setWord('');
      setPhonemes('');
      setNotes('');
      refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (idOrWord: string) => {
    await apiClient.deleteDictionaryEntry(idOrWord);
    refresh();
  };

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <h3 className="text-sm font-semibold">
        Pronunciation Dictionary{' '}
        <span className="text-xs font-normal text-muted-foreground">(IPA / phonemes)</span>
      </h3>
      <p className="mb-2 text-xs text-muted-foreground">
        Pin exact pronunciations for technical terms, proper nouns and acronyms before synthesis.
      </p>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <input
          className="rounded-md border border-border bg-background px-3 py-2 text-sm"
          placeholder="word (e.g. stichwort)"
          value={word}
          onChange={(e) => setWord(e.target.value)}
        />
        <input
          className="rounded-md border border-border bg-background px-3 py-2 text-sm"
          placeholder="phonemes (IPA)"
          value={phonemes}
          onChange={(e) => setPhonemes(e.target.value)}
        />
        <input
          className="rounded-md border border-border bg-background px-3 py-2 text-sm"
          placeholder="language (ALL / en / de…)"
          value={lang}
          onChange={(e) => setLang(e.target.value)}
        />
        <input
          className="rounded-md border border-border bg-background px-3 py-2 text-sm"
          placeholder="notes (optional)"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </div>
      <div className="mt-2 flex items-center gap-3">
        <button
          onClick={add}
          disabled={busy}
          className="rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-accent-foreground disabled:opacity-40"
        >
          {busy ? 'Adding…' : 'Add'}
        </button>
        {err && <span className="text-xs text-destructive">{err}</span>}
        <span className="text-xs text-muted-foreground">{entries.length} rule(s)</span>
      </div>

      <div className="mt-3 space-y-1">
        {entries.map((e: DictionaryEntry) => (
          <div
            key={e.id}
            className="flex items-center justify-between rounded-md bg-muted/30 px-3 py-1.5 text-sm"
          >
            <span>
              <span className="font-medium">{e.word}</span>{' '}
              <span className="text-muted-foreground">→ {e.phonemes}</span>{' '}
              <span className="text-xs text-muted-foreground">[{e.language}]</span>
            </span>
            <button className="text-xs text-destructive hover:underline" onClick={() => void remove(e.id)}>
              delete
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function CreateProjectForm({ onCreate }: { onCreate: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState('');
  const [source, setSource] = useState('en');
  const [target, setTarget] = useState('de');
  const [stt, setStt] = useState('parakeet');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      await apiClient.createDubbingProject(file, {
        name: name || file.name,
        source_language: source,
        target_language: target,
        stt_engine: stt,
      });
      setFile(null);
      setName('');
      onCreate();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <label className="col-span-2 text-sm font-medium">
          Media file (video or audio)
          <input
            type="file"
            accept=".wav,.mp3,.m4a,.ogg,.flac,.webm,.mp4,.mov,.opus,.aac,.mkv"
            className="mt-1 block w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <label className="text-sm font-medium">
          Name (optional)
          <input
            className="mt-1 block w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={file?.name ?? 'Untitled'}
          />
        </label>
        <div className="grid grid-cols-3 gap-2">
          <Select label="From" value={source} onChange={setSource} options={LANG_OPTIONS} />
          <Select label="To" value={target} onChange={setTarget} options={LANG_OPTIONS} />
          <label className="text-sm font-medium">
            STT
            <select
              className="mt-1 block w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
              value={stt}
              onChange={(e) => setStt(e.target.value)}
            >
              <option value="parakeet">Parakeet</option>
              <option value="whisper">Whisper</option>
            </select>
          </label>
        </div>
      </div>

      <div className="mt-3 flex items-center gap-3">
        <button
          disabled={!file || busy}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-foreground disabled:opacity-40"
          onClick={submit}
        >
          {busy ? 'Creating…' : 'Create project'}
        </button>
        {error && <span className="text-sm text-destructive">{error}</span>}
        {file && <span className="text-xs text-muted-foreground">{file.name}</span>}
      </div>
    </div>
  );
}

const LANG_OPTIONS = ['en', 'de', 'es', 'fr', 'it', 'pt', 'nl', 'zh', 'ja', 'ko'];

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <label className="text-sm font-medium">
      {label}
      <select
        className="mt-1 block w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

function ProjectList({
  projects,
  loading,
  onSelect,
}: {
  projects: DubbingProject[];
  loading: boolean;
  onSelect: (id: string) => void;
}) {
  if (loading) return <p className="text-sm text-muted-foreground">Loading projects…</p>;
  if (projects.length === 0)
    return <p className="text-sm text-muted-foreground">No projects yet. Create one above.</p>;

  return (
    <div className="space-y-2">
      {projects.map((p) => (
        <button
          key={p.id}
          onClick={() => onSelect(p.id)}
          className="flex w-full items-center justify-between rounded-xl border border-border bg-card px-4 py-3 text-left hover:bg-muted/50"
        >
          <div>
            <div className="font-medium">{p.name}</div>
            <div className="text-xs text-muted-foreground">
              {p.source_language} → {p.target_language} · {p.segment_count} segments
            </div>
          </div>
          <span
            className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
              p.status === 'ready' ? 'bg-emerald-500/15 text-emerald-400' : p.status === 'failed' ? 'bg-destructive/15 text-destructive' : 'bg-accent/15 text-accent'
            }`}
          >
            {p.stage ?? p.status}
          </span>
        </button>
      ))}
    </div>
  );
}

function ProjectPanel({
  projectId,
  onBack,
  onChanged,
}: {
  projectId: string;
  onBack: () => void;
  onChanged: () => void;
}) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [exporting, setExporting] = useState(false);

  const projectQuery = useQuery({
    queryKey: ['dubbing-project', projectId],
    queryFn: () => apiClient.getDubbingProject(projectId),
    refetchInterval: (q) => (q.state.data && q.state.data.status === 'processing' ? 3000 : false),
  });
  const segmentsQuery = useQuery({
    queryKey: ['dubbing-segments', projectId],
    queryFn: () => apiClient.listDubbingSegments(projectId),
    refetchInterval: (q) =>
      q.state.data && q.state.data.some((s: DubbingSegment) => s.is_dirty) ? 3000 : false,
  });

  const project = projectQuery.data;
  const segments = segmentsQuery.data ?? [];

  const run = async () => {
    setRunning(true);
    setError(null);
    try {
      await apiClient.runDubbingPipeline(projectId);
      await queryClient.invalidateQueries({ queryKey: ['dubbing-project', projectId] });
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  const exportVideo = async () => {
    setExporting(true);
    setError(null);
    try {
      await apiClient.exportDubbedVideo(projectId);
      await queryClient.invalidateQueries({ queryKey: ['dubbing-project', projectId] });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setExporting(false);
    }
  };

  if (projectQuery.isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <button onClick={onBack} className="text-sm text-muted-foreground hover:text-foreground">
            ← Projects
          </button>
          <h2 className="text-lg font-bold">{project?.name}</h2>
          <p className="text-xs text-muted-foreground">
            {project?.source_language} → {project?.target_language} · engine {project?.stt_engine} ·
            stage {project?.stage ?? project?.status}
          </p>
        </div>
        <button
          onClick={run}
          disabled={running || project?.status === 'processing'}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-foreground disabled:opacity-40"
        >
          {running || project?.status === 'processing' ? 'Processing…' : 'Run pipeline'}
        </button>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {project?.error && <p className="text-sm text-destructive">{project.error}</p>}

      {project?.status === 'ready' && project.dubbed_audio_path && (
        /* biome-ignore lint/a11y/useMediaCaption: assembled dubbing master, no captions payload */
        <audio controls src={apiClient.dubbedAudioUrl(projectId)} className="w-full" />
      )}

      {project?.status === 'ready' && (
        <div className="flex items-center gap-3">
          <button
            onClick={exportVideo}
            disabled={exporting}
            className="rounded-lg border border-border px-4 py-2 text-sm font-semibold hover:bg-muted/50 disabled:opacity-40"
          >
            {exporting ? 'Exporting…' : 'Export video'}
          </button>
          {project.dubbed_video_path && (
            /* biome-ignore lint/a11y/useMediaCaption: exported dub video, no captions payload */
            <video controls src={apiClient.dubbedVideoUrl(projectId)} className="h-40 rounded-lg" />
          )}
        </div>
      )}

      {segments.length > 0 ? (
        <SegmentList segments={segments} onChanged={onChanged} />
      ) : (
        <p className="text-sm text-muted-foreground">
          No segments yet. Run the pipeline to transcribe and segment the media.
        </p>
      )}
    </div>
  );
}

function SegmentList({
  segments,
  onChanged,
}: {
  segments: DubbingSegment[];
  onChanged: () => void;
}) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [busyId, setBusyId] = useState<string | null>(null);

  const saveText = async (seg: DubbingSegment, text: string) => {
    await apiClient.updateDubbingSegment(seg.id, { translated_text: text });
    onChanged();
  };

  const toggleLock = async (seg: DubbingSegment) => {
    await apiClient.updateDubbingSegment(seg.id, { is_locked: !seg.is_locked });
    onChanged();
  };

  const setAlignment = async (seg: DubbingSegment, alignment: string) => {
    await apiClient.updateDubbingSegment(seg.id, {
      alignment: alignment as 'start' | 'center' | 'end',
    });
    onChanged();
  };

  const resynthesize = async (seg: DubbingSegment) => {
    setBusyId(seg.id);
    try {
      await apiClient.resynthesizeDubbingSegment(seg.id);
      onChanged();
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-2">
      {segments.map((seg) => {
        const open = !collapsed[seg.id];
        return (
          <div key={seg.id} className="rounded-xl border border-border bg-card p-3">
            <button
              className="flex w-full items-center justify-between text-left"
              onClick={() => setCollapsed((c) => ({ ...c, [seg.id]: !c[seg.id] }))}
            >
              <span className="text-sm font-medium">
                              {seg.sequence_index}. {seg.start_time.toFixed(2)}s – {seg.end_time.toFixed(2)}s
                              <span className="ml-2 text-xs text-muted-foreground">
                                {seg.speaker_id ?? 'no-speaker'} · [{seg.target_char_min}..{seg.target_char_max}] chars
                              </span>
                            </span>
              <span className="flex items-center gap-2">
                {seg.is_locked && <span className="rounded bg-accent/15 px-1.5 text-xs text-accent">locked</span>}
                <span className="text-xs text-muted-foreground">{seg.duration.toFixed(2)}s</span>
              </span>
            </button>

            {open && (
              <div className="mt-2 space-y-2">
                <div className="rounded bg-muted/30 p-2 text-xs text-muted-foreground">{seg.source_text}</div>
                <textarea
                  defaultValue={seg.translated_text ?? ''}
                  onBlur={(e) => {
                    if (e.target.value !== (seg.translated_text ?? '')) void saveText(seg, e.target.value);
                  }}
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                  rows={2}
                  placeholder="Translated text…"
                />
                <div className="flex flex-wrap items-center gap-3 text-xs">
                  <label>
                    Alignment
                    <select
                      value={seg.alignment}
                      onChange={(e) => void setAlignment(seg, e.target.value)}
                      className="ml-2 rounded border border-border bg-background px-2 py-1"
                    >
                      <option value="start">Start</option>
                      <option value="center">Center</option>
                      <option value="end">End</option>
                    </select>
                  </label>
                  <button className="text-muted-foreground hover:text-foreground" onClick={() => void toggleLock(seg)}>
                    {seg.is_locked ? 'Unlock' : 'Lock'}
                  </button>
                  <button
                    className="text-accent hover:underline"
                    disabled={busyId === seg.id}
                    onClick={() => void resynthesize(seg)}
                  >
                    {busyId === seg.id ? 'Synthesizing…' : 'Re-synthesize'}
                  </button>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}