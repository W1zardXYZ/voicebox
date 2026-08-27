import { Loader2, Play, Trash2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/components/ui/use-toast';
import type { StorySegment } from '@/lib/api/types';
import { useDeleteSegment, useGenerateSegment, useUpdateSegment } from '@/lib/hooks/useStories';
import { useProfiles } from '@/lib/hooks/useProfiles';
import { cn } from '@/lib/utils/cn';

const STATUS_STYLE: Record<StorySegment['status'], string> = {
  draft: 'bg-muted text-muted-foreground',
  queued: 'bg-muted text-muted-foreground',
  generating: 'bg-accent/15 text-accent border-accent/30',
  completed: 'bg-emerald-500/15 text-emerald-600 border-emerald-500/30',
  error: 'bg-destructive/15 text-destructive border-destructive/30',
};

/**
 * A single story segment card (spec §4.6): editable text, a speaker dropdown,
 * a status badge, and Generate / Delete affordances. Editing text marks the
 * segment draft again (a new Generation is synthesized on the next Generate).
 */
export function SegmentCard({
  storyId,
  segment,
}: {
  storyId: string;
  segment: StorySegment;
}) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { data: profiles } = useProfiles();
  const updateSegment = useUpdateSegment();
  const deleteSegment = useDeleteSegment();
  const generateSegment = useGenerateSegment();

  const [draftText, setDraftText] = useState(segment.text);
  const [editing, setEditing] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Keep local text in sync when the server copy changes (status updates etc).
  useEffect(() => {
    setDraftText(segment.text);
  }, [segment.text]);

  useEffect(() => {
    if (editing) textareaRef.current?.focus();
  }, [editing]);

  const isBusy = segment.status === 'queued' || segment.status === 'generating';

  const saveText = () => {
    if (!editing) return;
    setEditing(false);
    const trimmed = draftText.trim();
    if (trimmed && trimmed !== segment.text) {
      updateSegment.mutate(
        { storyId, segmentId: segment.id, data: { text: trimmed } },
        {
          onError: (error) => {
            toast({
              title: t('segments.saveFailed'),
              description: error instanceof Error ? error.message : String(error),
              variant: 'destructive',
            });
            setDraftText(segment.text);
          },
        },
      );
    } else {
      setDraftText(segment.text);
    }
  };

  const assignSpeaker = (profileId: string) => {
    updateSegment.mutate(
      { storyId, segmentId: segment.id, data: { profile_id: profileId } },
      {
        onError: (error) => {
          toast({
            title: t('segments.speakerFailed'),
            description: error instanceof Error ? error.message : String(error),
            variant: 'destructive',
          });
        },
      },
    );
  };

  return (
    <div className="rounded-lg border bg-card p-3 space-y-2">
      <div className="flex items-center gap-2">
        <Badge className={cn('text-[10px] h-5', STATUS_STYLE[segment.status])}>
          {t(`segments.status.${segment.status}`)}
        </Badge>
        {segment.profile_name && (
          <span className="text-xs text-muted-foreground truncate">
            {t('segments.speakerLabel')}: {segment.profile_name}
          </span>
        )}
        <div className="ml-auto flex items-center gap-1">
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-xs"
            onClick={() => generateSegment.mutate({ storyId, segmentId: segment.id })}
            disabled={isBusy || generateSegment.isPending}
          >
            {isBusy ? (
              <Loader2 className="h-3 w-3 animate-spin mr-1" />
            ) : (
              <Play className="h-3 w-3 mr-1" />
            )}
            {t('segments.generate')}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-7 w-7 px-0 text-muted-foreground hover:text-destructive"
            onClick={() =>
              deleteSegment.mutate({ storyId, segmentId: segment.id })
            }
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      <Textarea
        ref={textareaRef}
        value={draftText}
        rows={Math.min(6, Math.max(2, Math.ceil(draftText.length / 90)))}
        className="text-sm resize-y"
        onFocus={() => setEditing(true)}
        onBlur={saveText}
        onChange={(e) => setDraftText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            setDraftText(segment.text);
            (e.target as HTMLTextAreaElement).blur();
          }
        }}
        placeholder={t('segments.textPlaceholder')}
      />

      <Select value={segment.profile_id ?? 'unassigned'} onValueChange={assignSpeaker}>
        <SelectTrigger className="h-8 w-56 text-xs">
          <SelectValue placeholder={t('segments.assignSpeaker')} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="unassigned">{t('segments.unassigned')}</SelectItem>
          {(profiles ?? []).map((p) => (
            <SelectItem key={p.id} value={p.id}>
              {p.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
