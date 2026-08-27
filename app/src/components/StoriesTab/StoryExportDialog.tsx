import { Download, Loader2 } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { useToast } from '@/components/ui/use-toast';
import { useExportStoryAudio } from '@/lib/hooks/useStories';
import { cn } from '@/lib/utils/cn';

/**
 * Export dialog for the story editor. Lets you pick a format (WAV / MP3) and a
 * scope — the whole book as one file, or each chapter as its own file (a ZIP
 * with one audio file per chapter, for audiobook chapter splits).
 */
export function StoryExportDialog({
  story,
  open,
  onOpenChange,
}: {
  story: { id: string; name: string };
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const exportAudio = useExportStoryAudio();
  const [format, setFormat] = useState<'wav' | 'mp3'>('wav');
  const [scope, setScope] = useState<'all' | 'chapters'>('chapters');

  const handleExport = () => {
    exportAudio.mutate(
      { storyId: story.id, storyName: story.name, format, scope },
      {
        onSuccess: () => onOpenChange(false),
        onError: (error) =>
          toast({
            title: t('storyContent.toast.exportFailed'),
            description: error instanceof Error ? error.message : String(error),
            variant: 'destructive',
          }),
      },
    );
  };

  const optionClass = (active: boolean) =>
    cn(
      'rounded-lg border px-3 py-2 text-sm font-medium transition-colors',
      active
        ? 'border-accent bg-accent/10 text-foreground'
        : 'text-muted-foreground hover:bg-muted/50',
    );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{t('exportDialog.title')}</DialogTitle>
          <DialogDescription>{t('exportDialog.description')}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label className="text-xs">{t('exportDialog.format')}</Label>
            <div className="grid grid-cols-2 gap-2">
              {(['wav', 'mp3'] as const).map((f) => (
                <button key={f} type="button" onClick={() => setFormat(f)} className={optionClass(format === f)}>
                  {f.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label className="text-xs">{t('exportDialog.scope')}</Label>
            <div className="grid grid-cols-2 gap-2">
              <button type="button" onClick={() => setScope('all')} className={optionClass(scope === 'all')}>
                {t('exportDialog.wholeBook')}
              </button>
              <button
                type="button"
                onClick={() => setScope('chapters')}
                className={optionClass(scope === 'chapters')}
              >
                {t('exportDialog.eachChapter')}
              </button>
            </div>
            {scope === 'chapters' && (
              <p className="text-xs text-muted-foreground">{t('exportDialog.chaptersHint')}</p>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button onClick={handleExport} disabled={exportAudio.isPending}>
            {exportAudio.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Download className="mr-2 h-4 w-4" />
            )}
            {t('exportDialog.download')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
