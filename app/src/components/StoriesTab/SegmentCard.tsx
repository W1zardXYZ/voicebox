import { Loader2, Minus, Play, Plus, Trash2 } from 'lucide-react';
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
import { Slider } from '@/components/ui/slider';
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/components/ui/use-toast';
import type { StorySegment } from '@/lib/api/types';
import {
  useDeleteSegment,
  useGenerateSegment,
  useSegmentVolume,
  useUpdateSegment,
} from '@/lib/hooks/useStories';
import { useProfiles } from '@/lib/hooks/useProfiles';
import { cn } from '@/lib/utils/cn';

const STATUS_STYLE: Record<StorySegment['status'], string> = {
  draft: 'bg-muted text-muted-foreground',
  queued: 'bg-muted text-muted-foreground',
  generating: 'bg-accent/15 text-accent border-accent/30',
  completed: 'bg-emerald-500/15 text-emerald-600 border-emerald-500/30',
  error: 'bg-destructive/15 text-destructive border-destructive/30',
};

// A stable color per speaker so different voices read distinctly in the list.
const SPEAKER_COLORS = [
  'bg-violet-500/15 text-violet-600 border-violet-500/30',
  'bg-sky-500/15 text-sky-600 border-sky-500/30',
  'bg-amber-500/15 text-amber-600 border-amber-500/30',
  'bg-emerald-500/15 text-emerald-600 border-emerald-500/30',
  'bg-rose-500/15 text-rose-600 border-rose-500/30',
  'bg-cyan-500/15 text-cyan-600 border-cyan-500/30',
];

function speakerColor(profileId: string | null | undefined): string {
  if (!profileId) return 'bg-muted text-muted-foreground border-muted';
  let h = 0;
  for (const ch of profileId) h = (h * 31 + ch.charCodeAt(0)) | 0;
  return SPEAKER_COLORS[Math.abs(h) % SPEAKER_COLORS.length];
}

/**
 * A story segment card rendered like an ElevenLabs script block (spec §4.6):
 * a speaker chip + dropdown, the editable text, a status badge, and core
 * audio controls (volume / fade in-out). Generate re-synthesizes the segment.
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
  const setVolume = useSegmentVolume();

  const [draftText, setDraftText] = useState(segment.text);
  const [editing, setEditing] = useState(false);
  const [volume, setVolumeLocal] = useState(segment.volume ?? 1.0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setDraftText(segment.text);
  }, [segment.text]);

  useEffect(() => {
    setVolumeLocal(segment.volume ?? 1.0);
  }, [segment.volume]);

  useEffect(() => {
    if (editing) textareaRef.current?.focus();
  }, [editing]);

  const isBusy = segment.status === 'queued' || segment.status === 'generating';
  const hasAudio = segment.status === 'completed' && !!segment.generation_id;

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

  const commitFade = (field: 'fade_in_ms' | 'fade_out_ms', value: number) => {
    updateSegment.mutate(
      { storyId, segmentId: segment.id, data: { [field]: Math.round(value) } },
      {
        onError: (error) => {
          toast({
            title: t('segments.saveFailed'),
            description: error instanceof Error ? error.message : String(error),
            variant: 'destructive',
          });
        },
      },
    );
  };

  const onVolumeChange = (value: number[]) => {
    const v = value[0];
    setVolumeLocal(v);
    // Debounce writes so dragging the slider doesn't spam the API.
    if (volumeDebounceRef.current) clearTimeout(volumeDebounceRef.current);
    volumeDebounceRef.current = window.setTimeout(() => {
      setVolume.mutate({ storyId, segmentId: segment.id, volume: v });
    }, 250);
  };
  const volumeDebounceRef = useRef<number | null>(null);

  const nudgeVolume = (delta: number) => {
    const v = Math.max(0, Math.min(2, +(volume + delta).toFixed(2)));
    setVolumeLocal(v);
    setVolume.mutate({ storyId, segmentId: segment.id, volume: v });
  };

  return (
    <div className="rounded-xl border bg-card p-3 sm:p-4 space-y-3">
      {/* Speaker + status header */}
      <div className="flex items-center gap-2 flex-wrap">
        <span
          className={cn(
            'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium',
            speakerColor(segment.profile_id),
          )}
        >
          <span className="uppercase">{segment.profile_name?.[0] ?? '?'}</span>
          {segment.profile_name || t('segments.unassigned')}
        </span>
        <Badge className={cn('text-[10px] h-5', STATUS_STYLE[segment.status])}>
          {t(`segments.status.${segment.status}`)}
        </Badge>
        <div className="ml-auto flex items-center gap-1">
          <Button
            size="sm"
            variant={hasAudio ? 'outline' : 'default'}
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
            onClick={() => deleteSegment.mutate({ storyId, segmentId: segment.id })}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Editable script text */}
      <Textarea
        ref={textareaRef}
        value={draftText}
        rows={Math.min(8, Math.max(2, Math.ceil(draftText.length / 105)))}
        className="text-[15px] leading-relaxed resize-y"
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

      {/* Speaker picker + audio controls */}
      <div className="flex items-center gap-3 flex-wrap">
        <Select value={segment.profile_id ?? 'unassigned'} onValueChange={assignSpeaker}>
          <SelectTrigger className="h-8 w-44 text-xs">
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

        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <button
            type="button"
            className="h-6 w-6 grid place-items-center border rounded hover:bg-muted"
            onClick={() => nudgeVolume(-0.05)}
            aria-label="volume down"
          >
            <Minus className="h-2.5 w-2.5" />
          </button>
          <Slider
            value={[volume]}
            min={0}
            max={2}
            step={0.05}
            onValueChange={onVolumeChange}
            className="w-24"
            aria-label={t('segments.volume')}
          />
          <button
            type="button"
            className="h-6 w-6 grid place-items-center border rounded hover:bg-muted"
            onClick={() => nudgeVolume(0.05)}
            aria-label="volume up"
          >
            <Plus className="h-2.5 w-2.5" />
          </button>
          <span className="tabular-nums">{Math.round(volume * 100)}%</span>
        </div>

        <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground ml-auto">
          <label className="flex items-center gap-1">
            {t('segments.fadeIn')}
            <input
              type="number"
              min={0}
              max={5000}
              step={50}
              defaultValue={segment.fade_in_ms ?? 0}
              onBlur={(e) => commitFade('fade_in_ms', Number(e.target.value) || 0)}
              className="h-7 w-14 rounded border bg-background px-1 text-[11px] tabular-nums"
            />
            ms
          </label>
          <label className="flex items-center gap-1">
            {t('segments.fadeOut')}
            <input
              type="number"
              min={0}
              max={5000}
              step={50}
              defaultValue={segment.fade_out_ms ?? 0}
              onBlur={(e) => commitFade('fade_out_ms', Number(e.target.value) || 0)}
              className="h-7 w-14 rounded border bg-background px-1 text-[11px] tabular-nums"
            />
            ms
          </label>
        </div>
      </div>
    </div>
  );
}
