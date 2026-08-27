import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { Download, FileText, GripVertical, Plus, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useToast } from '@/components/ui/use-toast';
import type { StorySegment } from '@/lib/api/types';
import {
  useCreateSegment,
  useDeleteSegment,
  useExportStoryAudio,
  useGenerateSegment,
  useReorderSegments,
  useStory,
  useUpdateSegment,
} from '@/lib/hooks/useStories';
import { useStoryStore } from '@/stores/storyStore';
import { cn } from '@/lib/utils/cn';
import { ChapterList } from './ChapterList';
import { MarkdownImportDialog } from './MarkdownImportDialog';
import { SegmentSettingsPanel } from './SegmentSettingsPanel';

const AVATAR_COLORS = [
  'bg-violet-500/15 text-violet-600',
  'bg-sky-500/15 text-sky-600',
  'bg-amber-500/15 text-amber-600',
  'bg-emerald-500/15 text-emerald-600',
  'bg-rose-500/15 text-rose-600',
  'bg-cyan-500/15 text-cyan-600',
];

function avatarColor(seed: string): string {
  let h = 0;
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) | 0;
  return AVATAR_COLORS[Math.abs(h) % AVATAR_COLORS.length];
}

// Tag-marked segments (e.g. <vorlesen>) get a persistent tint.
function isTagged(segment: StorySegment): boolean {
  return !!segment.tag;
}

function SegmentDocumentRow({
  storyId,
  segment,
  selected,
  onSelect,
}: {
  storyId: string;
  segment: StorySegment;
  selected: boolean;
  onSelect: () => void;
}) {
  const { t } = useTranslation();
  const generateSegment = useGenerateSegment();
  const deleteSegment = useDeleteSegment();
  const updateSegment = useUpdateSegment();

  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: segment.id,
  });
  const [draft, setDraft] = useState(segment.text);
  useEffect(() => setDraft(segment.text), [segment.text]);

  const isBusy = segment.status === 'queued' || segment.status === 'generating';
  const tinted = isTagged(segment);

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(
        'group relative flex gap-1.5 rounded-lg px-1 py-1',
        selected && 'bg-accent/10 ring-1 ring-accent/25',
        isDragging && 'opacity-70 z-10',
      )}
    >
      {/* Drag handle — the 2:3 dot grid, shown on hover */}
      <button
        type="button"
        {...attributes}
        {...listeners}
        className={cn(
          'mt-0.5 h-6 w-4 shrink-0 grid place-items-center text-muted-foreground/0 group-hover:text-muted-foreground cursor-grab active:cursor-grabbing',
          selected && 'text-muted-foreground/60',
        )}
        aria-label={t('editor.dragSegment')}
      >
        <GripVertical className="h-4 w-4" />
      </button>

      {/* Speaker avatar */}
      <div
        className={cn(
          'mt-0.5 h-6 w-6 shrink-0 rounded-full grid place-items-center text-[10px] font-semibold border',
          avatarColor(segment.character_name || segment.character_id || 'narrator'),
        )}
        title={segment.character_name || t('segments.unassigned')}
      >
        {(segment.character_name || '?')[0]?.toUpperCase()}
      </div>

      <div className="flex-1 min-w-0">
        <textarea
          value={draft}
          rows={Math.max(1, Math.ceil(draft.length / 110))}
          onChange={(e) => setDraft(e.target.value)}
          onFocus={onSelect}
          onBlur={() => {
            const trimmed = draft.trim();
            if (trimmed && trimmed !== segment.text) {
              updateSegment.mutate({ storyId, segmentId: segment.id, data: { text: trimmed } });
            }
          }}
          className={cn(
            'w-full resize-none bg-transparent text-[15px] leading-relaxed outline-none',
            tinted && 'text-foreground',
          )}
          style={tinted ? { borderLeft: '2px solid hsl(38 92% 50%)', paddingLeft: 8 } : undefined}
        />
        {(tinted || segment.character_name) && (
          <div className="flex items-center gap-2 mt-0.5 text-[10px] text-muted-foreground">
            {tinted && (
              <span className="text-amber-500 font-medium">{t('editor.tagged')}</span>
            )}
            {segment.character_name && <span>{segment.character_name}</span>}
            <span className="tabular-nums">{t(`segments.status.${segment.status}`)}</span>
            {isBusy && <span className="text-accent">…</span>}
          </div>
        )}
      </div>

      {/* Quick actions on hover */}
      <div className="shrink-0 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          type="button"
          className="h-6 w-6 grid place-items-center text-muted-foreground hover:text-accent"
          onClick={(e) => {
            e.stopPropagation();
            generateSegment.mutate({ storyId, segmentId: segment.id });
          }}
          disabled={isBusy}
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          className="h-6 w-6 grid place-items-center text-muted-foreground hover:text-destructive"
          onClick={(e) => {
            e.stopPropagation();
            deleteSegment.mutate({ storyId, segmentId: segment.id });
          }}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

export function StoryContent() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const selectedStoryId = useStoryStore((state) => state.selectedStoryId);
  const { data: story, isLoading } = useStory(selectedStoryId);
  const exportAudio = useExportStoryAudio();
  const createSegment = useCreateSegment();
  const reorderSegments = useReorderSegments();

  const [importOpen, setImportOpen] = useState(false);
  const [activeChapterId, setActiveChapterId] = useState<string | null>(null);
  const [selectedSegmentId, setSelectedSegmentId] = useState<string | null>(null);
  const [newSegmentText, setNewSegmentText] = useState('');

  const activeChapter =
    story?.chapters.find((c) => c.id === activeChapterId) ?? story?.chapters[0] ?? null;

  const sortedSegments = useMemo(() => {
    if (!activeChapter) return [];
    return [...activeChapter.segments].sort((a, b) => a.order_index - b.order_index);
  }, [activeChapter]);

  const selectedSegment =
    sortedSegments.find((s) => s.id === selectedSegmentId) ?? sortedSegments[0] ?? null;

  useEffect(() => {
    if (!selectedSegmentId && sortedSegments[0]) setSelectedSegmentId(sortedSegments[0].id);
  }, [selectedSegmentId, sortedSegments]);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id || !activeChapter) return;
    const oldIndex = sortedSegments.findIndex((s) => s.id === active.id);
    const newIndex = sortedSegments.findIndex((s) => s.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;
    const ordered = arrayMove(sortedSegments, oldIndex, newIndex);
    reorderSegments.mutate(
      { storyId: story!.id, segmentIds: ordered.map((s) => s.id) },
      { onError: (e) => toast({ title: t('editor.reorderFailed'), description: String(e), variant: 'destructive' }) },
    );
  };

  const addSegment = () => {
    if (!story || !activeChapter) return;
    const text = newSegmentText.trim();
    if (!text) return;
    createSegment.mutate(
      { storyId: story.id, data: { chapter_id: activeChapter.id, text } },
      { onSuccess: () => setNewSegmentText('') },
    );
  };

  if (!selectedStoryId) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        <div className="text-center">{t('storyContent.selectStory.title')}</div>
      </div>
    );
  }
  if (isLoading) return <div className="flex items-center justify-center h-full text-muted-foreground">{t('storyContent.loading')}</div>;
  if (!story) return <div className="text-muted-foreground">{t('storyContent.notFound.title')}</div>;

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden px-8">
      {/* Header */}
      <div className="shrink-0 flex items-center justify-between py-3 border-b">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold truncate">{story.name}</h2>
          {story.description && (
            <p className="text-xs text-muted-foreground truncate">{story.description}</p>
          )}
        </div>
        <div className="flex gap-2 items-center shrink-0">
          <Button variant="outline" size="sm" onClick={() => setImportOpen(true)}>
            <FileText className="mr-2 h-4 w-4" />
            {t('storyContent.importScript')}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => exportAudio.mutate({ storyId: story.id, storyName: story.name })}
            disabled={exportAudio.isPending}
          >
            <Download className="mr-2 h-4 w-4" />
            {t('storyContent.exportAudio')}
          </Button>
        </div>
      </div>
      <MarkdownImportDialog storyId={story.id} open={importOpen} onOpenChange={setImportOpen} />

      {/* Three-column editor */}
      <div className="flex-1 min-h-0 flex">
        <ChapterList
          storyId={story.id}
          chapters={story.chapters}
          activeChapterId={activeChapter?.id}
          onSelect={setActiveChapterId}
        />

        {/* Document center — text-first */}
        <div className="flex-1 min-w-0 flex flex-col min-h-0">
          <div className="flex-1 min-h-0 overflow-y-auto py-6 px-4">
            {activeChapter ? (
              <>
                <h3 className="text-xl font-semibold mb-4">{activeChapter.title}</h3>
                {sortedSegments.length === 0 ? (
                  <p className="text-sm text-muted-foreground border-2 border-dashed border-muted rounded-md p-4">
                    {t('storyContent.chapters.noSegments')}
                  </p>
                ) : (
                  <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
                    <SortableContext
                      items={sortedSegments.map((s) => s.id)}
                      strategy={verticalListSortingStrategy}
                    >
                      <div className="space-y-2">
                        {sortedSegments.map((segment) => (
                          <SegmentDocumentRow
                            key={segment.id}
                            storyId={story.id}
                            segment={segment}
                            selected={selectedSegment?.id === segment.id}
                            onSelect={() => setSelectedSegmentId(segment.id)}
                          />
                        ))}
                      </div>
                    </SortableContext>
                  </DndContext>
                )}
                <div className="flex gap-2 mt-4">
                  <Input
                    value={newSegmentText}
                    onChange={(e) => setNewSegmentText(e.target.value)}
                    placeholder={t('storyContent.chapters.newSegment')}
                    className="h-9 text-sm"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') addSegment();
                    }}
                  />
                  <Button
                    size="sm"
                    className="h-9"
                    onClick={addSegment}
                    disabled={!newSegmentText.trim() || createSegment.isPending}
                  >
                    <Plus className="mr-1.5 h-4 w-4" />
                    {t('storyContent.chapters.addSegment')}
                  </Button>
                </div>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">{t('storyContent.chapters.emptyHint')}</p>
            )}
          </div>
        </div>

        {/* Right settings panel */}
        <SegmentSettingsPanel story={story} selectedSegment={selectedSegment} />
      </div>
    </div>
  );
}
