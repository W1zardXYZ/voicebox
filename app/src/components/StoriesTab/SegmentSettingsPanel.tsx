import { Headphones, Loader2, Play, Plus, Trash2, Users } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
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
import { Slider } from '@/components/ui/slider';
import { useToast } from '@/components/ui/use-toast';
import { apiClient } from '@/lib/api/client';
import type { StoryCharacter, StoryDetailResponse, StorySegment } from '@/lib/api/types';
import { getLanguageOptionsForEngine } from '@/lib/constants/languages';
import { usePlayerStore } from '@/stores/playerStore';
import {
  useCreateCharacter,
  useDeleteCharacter,
  useDeleteSegment,
  useGenerateSegment,
  useRelayoutStoryItems,
  useSegmentVolume,
  useUpdateCharacter,
  useUpdateSegment,
  useUpdateStory,
} from '@/lib/hooks/useStories';
import { useProfiles } from '@/lib/hooks/useProfiles';
import { cn } from '@/lib/utils/cn';

/** Engine choices with their sizes (empty = no model-size option). */
const ENGINE_CHOICES: { engine: string; label: string; sizes?: string[] }[] = [
  { engine: 'qwen', label: 'Qwen3-TTS', sizes: ['1.7B', '0.6B'] },
  { engine: 'qwen_custom_voice', label: 'Qwen CustomVoice', sizes: ['1.7B', '0.6B'] },
  { engine: 'luxtts', label: 'LuxTTS' },
  { engine: 'chatterbox', label: 'Chatterbox' },
  { engine: 'chatterbox_turbo', label: 'Chatterbox Turbo' },
  { engine: 'tada', label: 'TADA', sizes: ['1B', '3B'] },
  { engine: 'kokoro', label: 'Kokoro 82M' },
];

const STATUS_STYLE: Record<StorySegment['status'], string> = {
  draft: 'bg-muted text-muted-foreground',
  queued: 'bg-muted text-muted-foreground',
  generating: 'bg-accent/15 text-accent border-accent/30',
  completed: 'bg-emerald-500/15 text-emerald-600 border-emerald-500/30',
  error: 'bg-destructive/15 text-destructive border-destructive/30',
};

/** Select sentinel for "use the project default" in override dropdowns. */
const DEFAULT = '__default__';

/**
 * The right-side settings panel (spec: "clip" + "project" tabs mirroring
 * ElevenLabs). The Clip tab edits the selected segment (character/voice,
 * volume, fades, generate). The Project tab renames/deletes the project and
 * manages its characters (add character → name + voice; narrator toggle).
 */
export function SegmentSettingsPanel({
  story,
  selectedSegment,
  onSegmentChanged,
}: {
  story: StoryDetailResponse;
  selectedSegment: StorySegment | null;
  onSegmentChanged?: () => void;
}) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { data: profiles } = useProfiles();
  const updateSegment = useUpdateSegment();
  const generateSegment = useGenerateSegment();
  const deleteSegment = useDeleteSegment();
  const setVolume = useSegmentVolume();
  const updateStory = useUpdateStory();
  const relayoutStoryItems = useRelayoutStoryItems();
  const createCharacter = useCreateCharacter();
  const updateCharacter = useUpdateCharacter();
  const deleteCharacter = useDeleteCharacter();
  const playerStore = usePlayerStore();

  const [tab, setTab] = useState<'clip' | 'project'>('clip');
  const [renameValue, setRenameValue] = useState(story.name);
  const [newCharName, setNewCharName] = useState('');
  const [newCharProfile, setNewCharProfile] = useState<string>('none');
  const [charDialogOpen, setCharDialogOpen] = useState(false);

  const listen = () => {
    if (!selectedSegment?.generation_id) return;
    playerStore.setAudioWithAutoPlay(
      apiClient.getAudioUrl(selectedSegment.generation_id),
      selectedSegment.generation_id,
      selectedSegment.profile_id ?? null,
      selectedSegment.text,
    );
  };
  const canListen = !!selectedSegment?.generation_id && selectedSegment.status === 'completed';

  // Per-segment override: null → fall back to the project default.
  const commitSegmentModel = (patch: Partial<{ engine: string | null; model_size: string | null; language: string | null; tag: string | null }>) => {
    if (!selectedSegment) return;
    updateSegment.mutate(
      { storyId: story.id, segmentId: selectedSegment.id, data: patch },
      { onError: (e) => toast({ title: t('segments.saveFailed'), description: String(e), variant: 'destructive' }) },
    );
  };

  // Project-wide default engine/model/language.
  const commitProjectDefault = (patch: Partial<{ default_engine: string | null; default_model_size: string | null; default_language: string | null }>) => {
    updateStory.mutate(
      {
        storyId: story.id,
        data: {
          name: story.name,
          description: story.description,
          default_engine: story.default_engine,
          default_model_size: story.default_model_size,
          default_language: story.default_language,
          ...patch,
        },
      },
      { onError: (e) => toast({ title: t('segments.saveFailed'), description: String(e), variant: 'destructive' }) },
    );
  };

  const activeEngine = (selectedSegment?.engine ?? story.default_engine) || 'qwen';
  const engineChoice = ENGINE_CHOICES.find((c) => c.engine === activeEngine);
  const effectiveLangOptions = getLanguageOptionsForEngine(activeEngine);

  const assignCharacter = (characterId: string) => {
    if (!selectedSegment) return;
    updateSegment.mutate(
      { storyId: story.id, segmentId: selectedSegment.id, data: { character_id: characterId } },
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
    if (!selectedSegment) return;
    updateSegment.mutate(
      { storyId: story.id, segmentId: selectedSegment.id, data: { [field]: Math.round(value) } },
      { onError: (e) => toast({ title: t('segments.saveFailed'), description: String(e), variant: 'destructive' }) },
    );
  };

  const onVolumeChange = (v: number[]) => {
    if (!selectedSegment) return;
    setVolume.mutate({ storyId: story.id, segmentId: selectedSegment.id, volume: v[0] });
  };

  const addCharacter = () => {
    if (!newCharName.trim()) return;
    createCharacter.mutate(
      {
        storyId: story.id,
        data: {
          name: newCharName.trim(),
          profile_id: newCharProfile === 'none' ? null : newCharProfile,
          is_narrator: story.characters.length === 0,
        },
      },
      {
        onSuccess: () => {
          setCharDialogOpen(false);
          setNewCharName('');
          setNewCharProfile('none');
          onSegmentChanged?.();
        },
        onError: (e) => toast({ title: t('chapters.generateFailed'), description: String(e), variant: 'destructive' }),
      },
    );
  };

  const toggleNarrator = (character: StoryCharacter) => {
    updateCharacter.mutate({ storyId: story.id, characterId: character.id, data: { is_narrator: !character.is_narrator } });
  };

  const isBusy = selectedSegment
    ? selectedSegment.status === 'queued' || selectedSegment.status === 'generating'
    : false;

  return (
    <div className="w-72 shrink-0 border-l bg-muted/10 flex flex-col min-h-0">
      {/* Tabs */}
      <div className="flex border-b shrink-0">
        {(['clip', 'project'] as const).map((name) => (
          <button
            key={name}
            type="button"
            onClick={() => setTab(name)}
            className={cn(
              'flex-1 py-2 text-xs font-medium text-muted-foreground hover:text-foreground border-b-2 transition-colors',
              tab === name ? 'border-accent text-foreground' : 'border-transparent',
            )}
          >
            {t(`settings.tabs.${name}`)}
          </button>
        ))}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3">
        {tab === 'clip' ? (
          selectedSegment ? (
            <>
              <div className="flex items-center gap-2">
                <Badge className={cn('text-[10px] h-5', STATUS_STYLE[selectedSegment.status])}>
                  {t(`segments.status.${selectedSegment.status}`)}
                </Badge>
                {selectedSegment.character_name && (
                  <span className="text-xs text-muted-foreground truncate">
                    {selectedSegment.character_name}
                  </span>
                )}
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs">{t('settings.character')}</Label>
                <Select
                  value={selectedSegment.character_id ?? 'narrator'}
                  onValueChange={assignCharacter}
                >
                  <SelectTrigger className="h-8 w-full text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="narrator">
                      {t('settings.narratorDefault')}
                    </SelectItem>
                    {story.characters.map((c) => (
                      <SelectItem key={c.id} value={c.id}>
                        {c.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Manual mark/tag — tints the segment in the editor */}
              <label className="flex items-center justify-between gap-2 rounded border bg-card px-2 py-1.5 text-xs">
                <span className="flex items-center gap-1.5">
                  <span
                    className={cn(
                      'inline-block h-2 w-2 rounded-full',
                      selectedSegment.tag ? 'bg-amber-500' : 'bg-muted-foreground/40',
                    )}
                  />
                  {t('settings.markTagged')}
                </span>
                <input
                  type="checkbox"
                  checked={!!selectedSegment.tag}
                  onChange={(e) =>
                    commitSegmentModel({ tag: e.target.checked ? 'marked' : null })
                  }
                  className="h-4 w-4"
                />
              </label>

              <div className="space-y-1.5">
                <Label className="text-xs">{t('segments.volume')}</Label>
                <div className="flex items-center gap-2">
                  <Slider
                    value={[selectedSegment.volume ?? 1]}
                    min={0}
                    max={2}
                    step={0.05}
                    onValueChange={onVolumeChange}
                    className="flex-1"
                  />
                  <span className="text-xs tabular-nums text-muted-foreground w-10 text-right">
                    {Math.round((selectedSegment.volume ?? 1) * 100)}%
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                {(['fade_in_ms', 'fade_out_ms'] as const).map((field) => (
                  <div key={field} className="space-y-1">
                    <Label className="text-xs">
                      {field === 'fade_in_ms' ? t('segments.fadeIn') : t('segments.fadeOut')}
                    </Label>
                    <div className="flex items-center gap-1">
                      <input
                        type="number"
                        min={0}
                        max={5000}
                        step={50}
                        defaultValue={selectedSegment[field] ?? 0}
                        onBlur={(e) => commitFade(field, Number(e.target.value) || 0)}
                        className="h-8 w-full rounded border bg-background px-2 text-xs tabular-nums"
                      />
                      <span className="text-[10px] text-muted-foreground">ms</span>
                    </div>
                  </div>
                ))}
              </div>

              {/* Model override for this clip (engine/model/language) */}
              <div className="space-y-1.5 pt-1">
                <Label className="text-xs flex items-center gap-1">
                  {t('settings.segmentOverride')}
                </Label>
                <Select
                  value={selectedSegment.engine ?? DEFAULT}
                  onValueChange={(v) => commitSegmentModel({ engine: v === DEFAULT ? null : v })}
                >
                  <SelectTrigger className="h-8 w-full text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={DEFAULT}>{t('settings.useDefault')}</SelectItem>
                    {ENGINE_CHOICES.map((c) => (
                      <SelectItem key={c.engine} value={c.engine}>
                        {c.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {engineChoice?.sizes?.length ? (
                  <Select
                    value={selectedSegment.model_size ?? DEFAULT}
                    onValueChange={(v) => commitSegmentModel({ model_size: v === DEFAULT ? null : v })}
                  >
                    <SelectTrigger className="h-8 w-full text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={DEFAULT}>{t('settings.useDefault')}</SelectItem>
                      {engineChoice!.sizes!.map((s) => (
                        <SelectItem key={s} value={s}>
                          {s}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : null}
                <Select
                  value={selectedSegment.language ?? DEFAULT}
                  onValueChange={(v) => commitSegmentModel({ language: v === DEFAULT ? null : v })}
                >
                  <SelectTrigger className="h-8 w-full text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={DEFAULT}>{t('settings.useDefault')}</SelectItem>
                    {effectiveLangOptions.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <Button
                className="w-full"
                variant="outline"
                size="sm"
                onClick={listen}
                disabled={!canListen}
                title={canListen ? t('settings.listen') : t('segments.generateFirst')}
              >
                <Headphones className="h-3.5 w-3.5 mr-1.5" />
                {t('settings.listen')}
              </Button>
              <Button
                className="w-full"
                size="sm"
                onClick={() =>
                  generateSegment.mutate({ storyId: story.id, segmentId: selectedSegment.id })
                }
                disabled={isBusy || generateSegment.isPending}
              >
                {isBusy ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
                ) : (
                  <Play className="h-3.5 w-3.5 mr-1.5" />
                )}
                {t('segments.generate')}
              </Button>
              <Button
                variant="ghost"
                className="w-full text-destructive hover:text-destructive"
                size="sm"
                onClick={() =>
                  deleteSegment.mutate({ storyId: story.id, segmentId: selectedSegment.id })
                }
              >
                <Trash2 className="h-3.5 w-3.5 mr-1.5" />
                {t('segments.delete')}
              </Button>
            </>
          ) : (
            <p className="text-xs text-muted-foreground">{t('settings.selectSegment')}</p>
          )
        ) : (
          <>
            <div className="space-y-1.5">
              <Label className="text-xs">{t('settings.projectName')}</Label>
              <Input
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
                onBlur={() => {
                  if (renameValue.trim() && renameValue.trim() !== story.name) {
                    updateStory.mutate({ storyId: story.id, data: { name: renameValue.trim(), description: story.description } });
                  }
                }}
                className="h-8 text-xs"
              />
            </div>

            {/* Project-wide default engine/model/language */}
            <div className="space-y-1.5 pt-1">
              <Label className="text-xs">{t('settings.projectDefaults')}</Label>
              <Select
                value={story.default_engine ?? DEFAULT}
                onValueChange={(v) => commitProjectDefault({ default_engine: v === DEFAULT ? null : v })}
              >
                <SelectTrigger className="h-8 w-full text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={DEFAULT}>{t('settings.useDefault')}</SelectItem>
                  {ENGINE_CHOICES.map((c) => (
                    <SelectItem key={c.engine} value={c.engine}>
                      {c.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {ENGINE_CHOICES.find((c) => c.engine === (story.default_engine ?? 'qwen'))?.sizes?.length ? (
                <Select
                  value={story.default_model_size ?? DEFAULT}
                  onValueChange={(v) => commitProjectDefault({ default_model_size: v === DEFAULT ? null : v })}
                >
                  <SelectTrigger className="h-8 w-full text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={DEFAULT}>{t('settings.useDefault')}</SelectItem>
                    {ENGINE_CHOICES.find((c) => c.engine === (story.default_engine ?? 'qwen'))!.sizes!.map((s) => (
                      <SelectItem key={s} value={s}>
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : null}
              <Select
                value={story.default_language ?? DEFAULT}
                onValueChange={(v) => commitProjectDefault({ default_language: v === DEFAULT ? null : v })}
              >
                <SelectTrigger className="h-8 w-full text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={DEFAULT}>{t('settings.useDefault')}</SelectItem>
                  {getLanguageOptionsForEngine(story.default_engine ?? 'qwen').map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Segment pause between clips (project-wide) */}
            <div className="space-y-1.5 pt-1">
              <Label className="text-xs">{t('settings.segmentPause')}</Label>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min={0}
                  max={10000}
                  step={50}
                  defaultValue={story.segment_pause_ms ?? 400}
                  onBlur={(e) => {
                    const value = Math.max(0, Math.round(Number(e.target.value) || 0));
                    updateStory.mutate(
                      {
                        storyId: story.id,
                        data: {
                          name: story.name,
                          description: story.description,
                          segment_pause_ms: value,
                        },
                      },
                      {
                        onError: (err) =>
                          toast({ title: t('segments.saveFailed'), description: String(err), variant: 'destructive' }),
                      },
                    );
                    relayoutStoryItems.mutate({ storyId: story.id });
                  }}
                  className="h-8 w-24 rounded border bg-background px-2 text-xs tabular-nums"
                />
                <span className="text-[10px] text-muted-foreground">ms</span>
              </div>
              <p className="text-[10px] text-muted-foreground">{t('settings.segmentPauseHint')}</p>
            </div>

            <div className="pt-1">
              <div className="flex items-center justify-between mb-1.5">
                <Label className="text-xs flex items-center gap-1">
                  <Users className="h-3.5 w-3.5" />
                  {t('settings.characters')}
                </Label>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 w-6 px-0 text-muted-foreground"
                  onClick={() => setCharDialogOpen(true)}
                >
                  <Plus className="h-3.5 w-3.5" />
                </Button>
              </div>
              {story.characters.length === 0 ? (
                <p className="text-xs text-muted-foreground">{t('settings.noCharacters')}</p>
              ) : (
                <div className="space-y-1">
                  {story.characters.map((c) => (
                    <div
                      key={c.id}
                      className="flex items-center gap-1.5 rounded border bg-card px-2 py-1.5"
                    >
                      <button
                        type="button"
                        onClick={() => toggleNarrator(c)}
                        title={t('settings.toggleNarrator')}
                        className="text-xs font-medium truncate flex-1 text-left"
                      >
                        {c.name}
                        {c.is_narrator && (
                          <span className="ml-1 text-[10px] text-accent">★</span>
                        )}
                      </button>
                      <Select
                        value={c.profile_id ?? 'none'}
                        onValueChange={(pid) =>
                          updateCharacter.mutate({
                            storyId: story.id,
                            characterId: c.id,
                            data: { profile_id: pid === 'none' ? null : pid },
                          })
                        }
                      >
                        <SelectTrigger className="h-6 w-28 text-[10px]">
                          <SelectValue />
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
                      <button
                        type="button"
                        className="text-muted-foreground hover:text-destructive"
                        onClick={() => deleteCharacter.mutate({ storyId: story.id, characterId: c.id })}
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* Add character dialog */}
      <Dialog open={charDialogOpen} onOpenChange={setCharDialogOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>{t('settings.addCharacter')}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label className="text-xs">{t('settings.characterName')}</Label>
              <Input
                autoFocus
                value={newCharName}
                onChange={(e) => setNewCharName(e.target.value)}
                className="h-10 text-sm"
                placeholder="Narrator"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') addCharacter();
                }}
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">{t('settings.voice')}</Label>
              <Select value={newCharProfile} onValueChange={setNewCharProfile}>
                <SelectTrigger className="h-10 w-full text-sm">
                  <SelectValue />
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
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCharDialogOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button onClick={addCharacter} disabled={!newCharName.trim() || createCharacter.isPending}>
              {t('settings.saveCharacter')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
