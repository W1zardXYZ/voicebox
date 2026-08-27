import { Loader2, Pencil, Play, Plus, Trash2, X } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useToast } from '@/components/ui/use-toast';
import type { StoryChapter } from '@/lib/api/types';
import {
  useCreateChapter,
  useDeleteChapter,
  useGenerateManySegments,
  useUpdateChapter,
} from '@/lib/hooks/useStories';
import { cn } from '@/lib/utils/cn';

function formatMs(ms: number): string {
  const totalSec = Math.round(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

/** Rough chapter duration from segment text (~14 chars/s). */
function chapterDurationMs(chapter: StoryChapter): number {
  return chapter.segments.reduce(
    (sum, seg) => sum + Math.max(800, (seg.text.length / 14) * 1000),
    0,
  );
}

/**
 * Left rail listing a story's chapters (spec §4.6): title, segment count and
 * estimated duration, inline rename, generate-all, delete, and a "new chapter"
 * button.
 */
export function ChapterList({
  storyId,
  chapters,
  activeChapterId,
  onSelect,
}: {
  storyId: string;
  chapters: StoryChapter[];
  activeChapterId?: string | null;
  onSelect: (chapterId: string) => void;
}) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const createChapter = useCreateChapter();
  const updateChapter = useUpdateChapter();
  const deleteChapter = useDeleteChapter();
  const generateMany = useGenerateManySegments();

  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [newChapterMode, setNewChapterMode] = useState(false);
  const [newChapterTitle, setNewChapterTitle] = useState('');

  const commitRename = (chapter: StoryChapter) => {
    setRenamingId(null);
    const title = renameValue.trim();
    if (title && title !== chapter.title) {
      updateChapter.mutate({ storyId, chapterId: chapter.id, data: { title } });
    }
  };

  const generateChapter = (chapter: StoryChapter) => {
    const ids = chapter.segments.filter((s) => s.status !== 'completed').map((s) => s.id);
    if (ids.length === 0) {
      toast({ title: t('chapters.allDone') });
      return;
    }
    generateMany.mutate(
      { storyId, segmentIds: ids },
      {
        onError: (error) => {
          toast({
            title: t('chapters.generateFailed'),
            description: error instanceof Error ? error.message : String(error),
            variant: 'destructive',
          });
        },
      },
    );
  };

  return (
    <div className="w-56 shrink-0 border-r bg-muted/10 flex flex-col min-h-0">
      <div className="px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wider flex items-center justify-between">
        <span>{t('chapters.title')}</span>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 w-6 px-0 text-muted-foreground"
          onClick={() => {
            setNewChapterMode((v) => !v);
            setNewChapterTitle('');
          }}
        >
          <Plus className="h-3.5 w-3.5" />
        </Button>
      </div>

      {newChapterMode && (
        <div className="px-2 pb-2 flex gap-1">
          <Input
            autoFocus
            value={newChapterTitle}
            onChange={(e) => setNewChapterTitle(e.target.value)}
            placeholder={t('chapters.newTitle')}
            className="h-7 text-xs"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && newChapterTitle.trim()) {
                createChapter.mutate({ storyId, title: newChapterTitle.trim() });
                setNewChapterMode(false);
              }
              if (e.key === 'Escape') setNewChapterMode(false);
            }}
          />
          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 px-0"
            onClick={() => setNewChapterMode(false)}
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-y-auto space-y-1 px-2 pb-2">
        {chapters.length === 0 && (
          <p className="text-xs text-muted-foreground px-1 py-2">{t('chapters.empty')}</p>
        )}
        {chapters.map((chapter) => {
          const active = chapter.id === activeChapterId;
          const segmentCount = chapter.segments.length;
          return (
            <div
              key={chapter.id}
              className={cn(
                'group rounded-md px-2 py-1.5 cursor-pointer hover:bg-muted/60 transition-colors',
                active && 'bg-accent/15 ring-1 ring-accent/30',
              )}
            >
              {renamingId === chapter.id ? (
                <Input
                  autoFocus
                  value={renameValue}
                  onChange={(e) => setRenameValue(e.target.value)}
                  className="h-6 text-xs"
                  onClick={(e) => e.stopPropagation()}
                  onBlur={() => commitRename(chapter)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') commitRename(chapter);
                    if (e.key === 'Escape') {
                      setRenamingId(null);
                      setRenameValue(chapter.title);
                    }
                  }}
                />
              ) : (
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    className="text-xs font-medium truncate flex-1 text-left hover:underline"
                    onClick={() => onSelect(chapter.id)}
                  >
                    {chapter.title}
                  </button>
                  <span className="text-[10px] text-muted-foreground shrink-0 tabular-nums">
                    {segmentCount} · {formatMs(chapterDurationMs(chapter))}
                  </span>
                  <button
                    type="button"
                    title={t('chapters.rename')}
                    className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-foreground transition-opacity"
                    onClick={(e) => {
                      e.stopPropagation();
                      setRenamingId(chapter.id);
                      setRenameValue(chapter.title);
                    }}
                  >
                    <Pencil className="h-3 w-3" />
                  </button>
                  <button
                    type="button"
                    title={t('chapters.generateAll')}
                    className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-accent transition-opacity"
                    onClick={(e) => {
                      e.stopPropagation();
                      generateChapter(chapter);
                    }}
                  >
                    {generateMany.isPending ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Play className="h-3 w-3" />
                    )}
                  </button>
                  <button
                    type="button"
                    title={t('chapters.delete')}
                    className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-opacity"
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteChapter.mutate({ storyId, chapterId: chapter.id });
                    }}
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
