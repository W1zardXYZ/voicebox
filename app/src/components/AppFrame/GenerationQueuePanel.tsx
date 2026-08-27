import { ChevronDown, ChevronUp, ListMusic, Loader2, Square } from 'lucide-react';
import { useState } from 'react';
import { Progress } from '@/components/ui/progress';
import type { GenerationQueueItem } from '@/lib/api/types';
import { useCancelAllGenerations, useCancelGeneration, useGenerationQueue } from '@/lib/hooks/useGenerationQueue';
import { useGenerationStore } from '@/stores/generationStore';

const STATE_LABEL: Record<string, string> = {
  queued: 'Queued',
  loading_model: 'Loading model…',
  generating: 'Generating',
  running: 'Running',
};

/** Live progress percent (0..100) or undefined for an indeterminate bar. */
function progressPercent(item: GenerationQueueItem): number | undefined {
  if (item.progress == null) return undefined;
  return Math.max(0, Math.min(100, Math.round(item.progress * 100)));
}

function QueueRow({ item }: { item: GenerationQueueItem }) {
  const live = useGenerationStore((s) => s.progressById.get(item.generation_id));
  const cancel = useCancelGeneration();
  const merged: GenerationQueueItem = {
    ...item,
    state: (live?.state ?? item.state) as GenerationQueueItem['state'],
    progress: live?.progress ?? item.progress,
    chunk_index: live?.chunk_index ?? item.chunk_index,
    chunk_count: live?.chunk_count ?? item.chunk_count,
    message: live?.message ?? item.message,
  };

  const pct = progressPercent(merged);
  const isLoading = merged.state === 'loading_model';
  const chunkInfo =
    merged.chunk_count != null
      ? `${merged.chunk_index ?? 0}/${merged.chunk_count} chunks`
      : null;

  return (
    <div className="space-y-1 py-1.5">
      <div className="flex items-center gap-2 min-w-0">
        {isLoading || (pct === undefined && merged.state !== 'queued') ? (
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" />
        ) : (
          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
        )}
        <span className="text-xs text-muted-foreground truncate flex-1">
          {merged.text_preview || '…'}
        </span>
        {pct != null && (
          <span className="text-[10px] tabular-nums text-muted-foreground shrink-0">{pct}%</span>
        )}
        <span className="text-[10px] text-muted-foreground shrink-0">
          {STATE_LABEL[merged.state] ?? merged.state}
          {chunkInfo ? ` · ${chunkInfo}` : ''}
        </span>
        <button
          type="button"
          onClick={() => cancel.mutate(item.generation_id)}
          disabled={cancel.isPending}
          className="shrink-0 grid h-5 w-5 place-items-center rounded text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors"
          aria-label="Stop generation"
          title="Stop"
        >
          <Square className="h-3 w-3" />
        </button>
      </div>
      <Progress value={pct} className="h-1" />
      {merged.message && (
        <p className="text-[10px] text-muted-foreground/80 truncate">{merged.message}</p>
      )}
    </div>
  );
}

/**
 * Global generation queue / progress panel (spec §6.3). Mounted in AppFrame so
 * it is visible on every route while clips are queued or generating. Collapsible
 * — a compact pill when closed, a list with per-item progress and per-item /
 * all stop buttons when open.
 */
export function GenerationQueuePanel() {
  const { data, isFetching } = useGenerationQueue();
  const hasLiveProgress = useGenerationStore((s) => s.progressById.size > 0);
  const cancelAll = useCancelAllGenerations();
  const [open, setOpen] = useState(true);

  const items = data?.items ?? [];
  const active = items.filter((i) => i.progress != null);
  const avg =
    active.length > 0
      ? Math.round(
          (active.reduce((sum, i) => sum + (i.progress ?? 0), 0) / active.length) * 100,
        )
      : null;

  const isEmpty = items.length === 0 && !hasLiveProgress;
  if (isEmpty) return null;

  const header = (
    <div className="flex items-center gap-1.5">
      <ListMusic className="h-3.5 w-3.5" />
      <span className="text-xs font-medium">
        {items.length > 0 ? `${items.length} in queue` : 'Generating'}
      </span>
      {avg != null && <span className="text-[10px] text-accent">· {avg}%</span>}
    </div>
  );

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col items-end gap-2">
      {/* Collapsed pill */}
      {!open && (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="flex items-center gap-2 rounded-full border bg-background/95 px-3 py-2 shadow-lg backdrop-blur transition-colors hover:bg-background"
        >
          {header}
          {isFetching && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
          <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" />
        </button>
      )}

      {/* Expanded card */}
      {open && (
        <div className="w-80 max-w-[calc(100vw-2rem)] rounded-xl border bg-background/95 shadow-xl backdrop-blur">
          <div className="flex items-center justify-between px-3 py-2 border-b">
            <button
              type="button"
              className="flex items-center gap-2 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
              onClick={() => setOpen(false)}
            >
              {header}
              {isFetching && <Loader2 className="h-3 w-3 animate-spin" />}
            </button>
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => cancelAll.mutate()}
                disabled={cancelAll.isPending || items.length === 0}
                className="flex items-center gap-1 rounded px-1.5 py-1 text-xs text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors disabled:opacity-50"
              >
                <Square className="h-3 w-3" />
                Stop all
              </button>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="text-muted-foreground/60 hover:text-foreground transition-colors"
                aria-label="Collapse queue panel"
              >
                <ChevronDown className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
          <div className="px-3 py-2 max-h-64 overflow-y-auto">
            {items.map((item) => (
              <QueueRow key={item.generation_id} item={item} />
            ))}
            {items.length === 0 && hasLiveProgress && (
              <p className="text-xs text-muted-foreground py-1">Finalizing…</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
