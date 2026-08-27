import { FileText, Loader2, Upload } from 'lucide-react';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useToast } from '@/components/ui/use-toast';
import type {
  MarkdownImportPreview,
  MarkdownImportRequest,
} from '@/lib/api/types';
import { useCommitMarkdownImport, useMarkdownImportPreview } from '@/lib/hooks/useStories';
import { useProfiles } from '@/lib/hooks/useProfiles';
import { cn } from '@/lib/utils/cn';

const SPLIT_MODES: { value: MarkdownImportRequest['mode']; label: string }[] = [
  { value: 'h1', label: 'splitModes.h1' },
  { value: 'h2', label: 'splitModes.h2' },
  { value: 'paragraph', label: 'splitModes.paragraph' },
  { value: 'read_aloud', label: 'splitModes.readAloud' },
];

/**
 * Markdown script import dialog (spec §4.3/§4.4): pick a .md file, choose the
 * split mode, see the chapter/segment preview, then commit.
 */
export function MarkdownImportDialog({
  storyId,
  open,
  onOpenChange,
}: {
  storyId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { data: profiles } = useProfiles();
  const previewMutation = useMarkdownImportPreview();
  const commitMutation = useCommitMarkdownImport();

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [markdown, setMarkdown] = useState('');
  const [mode, setMode] = useState<MarkdownImportRequest['mode']>('h1');
  const [speakUntagged, setSpeakUntagged] = useState(true);
  const [combineMaxChars, setCombineMaxChars] = useState(0);
  // Custom XML/HTML separator pair (e.g. <vorlesen>/</vorlesen>) — splits
  // segments within chapters, never creates new ones.
  const [customOpenTag, setCustomOpenTag] = useState('<vorlesen>');
  const [customCloseTag, setCustomCloseTag] = useState('</vorlesen>');
  // Narrator set before creation — every segment defaults to this voice.
  const [narratorProfileId, setNarratorProfileId] = useState<string>('none');
  const [preview, setPreview] = useState<MarkdownImportPreview | null>(null);

  const reset = () => {
    setMarkdown('');
    setPreview(null);
    setMode('h1');
    setSpeakUntagged(true);
    setCombineMaxChars(0);
    setCustomOpenTag('<vorlesen>');
    setCustomCloseTag('</vorlesen>');
    setNarratorProfileId('none');
  };

  const loadFile = async (file: File) => {
    const text = await file.text();
    setMarkdown(text);
    setPreview(null);
  };

  const runPreview = async () => {
    if (!markdown.trim()) {
      toast({ title: t('import.empty'), variant: 'destructive' });
      return;
    }
    try {
      const result = await previewMutation.mutateAsync({
        storyId,
        data: {
          markdown,
          mode,
          speak_untagged: speakUntagged,
          combine_max_chars: combineMaxChars,
          custom_open_tag: customOpenTag,
          custom_close_tag: customCloseTag,
        },
      });
      setPreview(result);
    } catch (error) {
      toast({
        title: t('import.previewFailed'),
        description: error instanceof Error ? error.message : String(error),
        variant: 'destructive',
      });
    }
  };

  const commit = async () => {
    if (!preview) return;
    try {
      await commitMutation.mutateAsync({
        storyId,
        data: {
          chapters: preview.chapters.map((c) => ({
            title: c.title,
            segments: c.segments.map((s) => ({
              text: s.text,
              speaker_hint: s.speaker_hint,
              // Persist only a real region tag (custom / read_aloud). The
              // "untagged" marker is a parser/UI sentinel, not a real tag, so
              // it must not tint every segment amber.
              tag: s.tags.find((t) => t !== 'untagged') ?? null,
            })),
          })),
          narrator_name: profiles?.find((p) => p.id === narratorProfileId)?.name ?? 'Narrator',
          narrator_profile_id: narratorProfileId === 'none' ? null : narratorProfileId,
        },
      });
      reset();
      onOpenChange(false);
      toast({ title: t('import.committed') });
    } catch (error) {
      toast({
        title: t('import.commitFailed'),
        description: error instanceof Error ? error.message : String(error),
        variant: 'destructive',
      });
    }
  };

  const totalSegments = preview?.chapters.reduce((n, c) => n + c.segments.length, 0) ?? 0;

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v);
        if (!v) reset();
      }}
    >
      <DialogContent className="sm:max-w-2xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{t('import.title')}</DialogTitle>
          <DialogDescription>{t('import.description')}</DialogDescription>
        </DialogHeader>

        <div className="space-y-3 overflow-y-auto pr-1">
          <div className="flex items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept=".md,.markdown,.txt,text/markdown,text/plain"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void loadFile(file);
                e.target.value = '';
              }}
            />
            <Button variant="outline" size="sm" onClick={() => fileInputRef.current?.click()}>
              <Upload className="mr-2 h-4 w-4" />
              {t('import.chooseFile')}
            </Button>
            {markdown && (
              <span className="text-xs text-muted-foreground truncate">
                {markdown.length} {t('import.chars')}
              </span>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label className="text-xs">{t('import.splitMode')}</Label>
              <Select value={mode} onValueChange={(v) => setMode(v as MarkdownImportRequest['mode'])}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SPLIT_MODES.map((m) => (
                    <SelectItem key={m.value} value={m.value}>
                      {t(m.label)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="import-combine" className="text-xs">
                {t('import.combine')}
              </Label>
              <Input
                id="import-combine"
                type="number"
                min={0}
                step={20}
                value={combineMaxChars}
                onChange={(e) => setCombineMaxChars(Number(e.target.value) || 0)}
                className="h-8 text-xs"
              />
            </div>
          </div>

          {/* Custom separator tags — splits segments WITHIN chapters */}
          <div className="rounded-lg border p-2.5 space-y-2 bg-background">
            <Label className="text-xs">{t('import.customTags')}</Label>
            <p className="text-[11px] text-muted-foreground">{t('import.customTagsHint')}</p>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label className="text-[10px] text-muted-foreground">{t('import.openTag')}</Label>
                <Input
                  value={customOpenTag}
                  onChange={(e) => setCustomOpenTag(e.target.value)}
                  placeholder="<vorlesen>"
                  className="h-8 text-xs font-mono"
                />
              </div>
              <div className="space-y-1">
                <Label className="text-[10px] text-muted-foreground">{t('import.closeTag')}</Label>
                <Input
                  value={customCloseTag}
                  onChange={(e) => setCustomCloseTag(e.target.value)}
                  placeholder="</vorlesen>"
                  className="h-8 text-xs font-mono"
                />
              </div>
            </div>
          </div>

          {/* Narrator — set before creation, defaults every segment */}
          <div className="space-y-1.5">
            <Label className="text-xs">{t('import.narrator')}</Label>
            <Select value={narratorProfileId} onValueChange={setNarratorProfileId}>
              <SelectTrigger className="h-8 text-xs">
                <SelectValue placeholder={t('import.narratorPlaceholder')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">{t('settings.noVoice')}</SelectItem>
                {(profiles ?? []).map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {(mode === 'read_aloud' || customOpenTag.trim() || customCloseTag.trim()) && (
            <label
              htmlFor="import-speak-untagged"
              className="flex items-center gap-2 text-xs text-muted-foreground"
            >
              <Checkbox
                id="import-speak-untagged"
                checked={speakUntagged}
                onCheckedChange={(v) => setSpeakUntagged(!!v)}
              />
              {t('import.speakUntagged')}
            </label>
          )}

          <Button size="sm" onClick={runPreview} disabled={previewMutation.isPending || !markdown.trim()}>
            {previewMutation.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin mr-2" />
            ) : (
              <FileText className="h-3.5 w-3.5 mr-2" />
            )}
            {t('import.preview')}
          </Button>

          {preview && (
            <div className="space-y-3 border rounded-lg p-3 bg-muted/20">
              <p className="text-xs font-medium text-muted-foreground">
                {t('import.previewTitle', {
                  chapters: preview.chapters.length,
                  segments: totalSegments,
                })}
              </p>
              {preview.chapters.map((chapter, ci) => (
                <div key={`${ci}-${chapter.title}`} className="space-y-1">
                  <p className="text-sm font-medium flex items-center gap-2">
                    {chapter.title}
                    <Badge variant="outline" className="text-[10px] h-4">
                      {chapter.segments.length}
                    </Badge>
                  </p>
                  <ul className="space-y-1">
                    {chapter.segments.map((seg) => {
                      const tagged = seg.tags.includes('custom') || seg.tags.includes('read_aloud');
                      return (
                        <li
                          key={`${ci}-${seg.source_span}`}
                          className={cn(
                            'text-xs pl-3 border-l',
                            tagged
                              ? 'text-foreground border-amber-500 bg-amber-500/5'
                              : 'text-muted-foreground border-border',
                          )}
                        >
                          <span className="line-clamp-2">{seg.text}</span>
                          {tagged && (
                            <span className="text-[10px] text-amber-500">{t('editor.tagged')}</span>
                          )}
                          {seg.speaker_hint && (
                            <span className="text-[10px] text-accent">@{seg.speaker_hint}</span>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button
            onClick={commit}
            disabled={!preview || commitMutation.isPending || preview.chapters.length === 0}
          >
            {commitMutation.isPending && (
              <Loader2 className="h-3.5 w-3.5 animate-spin mr-2" />
            )}
            {t('import.commit', { count: totalSegments })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
