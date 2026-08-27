import { useCallback, useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useToast } from '@/components/ui/use-toast';
import { apiClient } from '@/lib/api/client';
import { useGenerationSettings } from '@/lib/hooks/useSettings';
import { useGenerationStore } from '@/stores/generationStore';
import { usePlayerStore } from '@/stores/playerStore';

interface QueueItem {
  generation_id: string;
  state?: string;
  progress?: number | null;
  chunk_index?: number | null;
  chunk_count?: number | null;
  message?: string | null;
}

interface DoneEvent {
  type: 'done';
  id: string;
  status: 'completed' | 'failed' | 'not_found' | string;
  duration?: number | null;
  error?: string | null;
  source?: string | null;
}

// Agent-initiated generations are played by the floating pill, not the
// main-window AudioPlayer. Skip autoplay here to avoid double-playback.
const AGENT_SOURCES = new Set(['mcp', 'rest']);

/**
 * Subscribes to a single queue SSE stream (GET /generate/queue/stream) instead
 * of opening one EventSource per generation — the browser caps ~6 connections
 * per host, which froze the queue beyond a handful of items. The stream carries
 * per-item progress for the whole queue and one-off `done` events when a
 * generation leaves, so status/completion handling stays correct end-to-end.
 */
export function useGenerationProgress() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const pendingIds = useGenerationStore((s) => s.pendingGenerationIds);
  const removePendingGeneration = useGenerationStore((s) => s.removePendingGeneration);
  const removePendingStoryAdd = useGenerationStore((s) => s.removePendingStoryAdd);
  const setGenerationProgress = useGenerationStore((s) => s.setGenerationProgress);
  const removeGenerationProgress = useGenerationStore((s) => s.removeGenerationProgress);
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const setAudioWithAutoPlay = usePlayerStore((s) => s.setAudioWithAutoPlay);
  const { settings: genSettings } = useGenerationSettings();
  const autoplayOnGenerate = genSettings?.autoplay_on_generate ?? true;

  const isPlayingRef = useRef(isPlaying);
  const autoplayRef = useRef(autoplayOnGenerate);
  isPlayingRef.current = isPlaying;
  autoplayRef.current = autoplayOnGenerate;

  const sourceRef = useRef<EventSource | null>(null);

  const handleDone = useCallback(
    (data: DoneEvent) => {
      const id = data.id;
      removePendingGeneration(id);
      removeGenerationProgress(id);

      // Refetch history + always refresh the story (segment statuses + timeline).
      queryClient.refetchQueries({ queryKey: ['history'] });
      queryClient.invalidateQueries({ queryKey: ['stories'] });

      if (data.status === 'completed') {
        const storyId = removePendingStoryAdd(id);
        if (storyId) {
          apiClient
            .addStoryItem(storyId, { generation_id: id })
            .then(() => {
              queryClient.invalidateQueries({ queryKey: ['stories'] });
              queryClient.invalidateQueries({ queryKey: ['stories', storyId] });
              toast({
                title: 'Added to story',
                description: data.duration
                  ? `Audio generated (${data.duration.toFixed(2)}s) and added to story`
                  : 'Audio generated and added to story',
              });
            })
            .catch(() => {
              toast({
                title: 'Generation complete',
                description: 'Audio generated but failed to add to story',
                variant: 'destructive',
              });
            });
        }

        // Auto-play if enabled and nothing is currently playing. Skip
        // agent-initiated sources — the floating pill plays those itself.
        const isAgentSpeak = data.source ? AGENT_SOURCES.has(data.source) : false;
        if (autoplayRef.current && !isPlayingRef.current && !isAgentSpeak) {
          setAudioWithAutoPlay(apiClient.getAudioUrl(id), id, '', '');
        }
      } else if (data.status === 'failed' || data.status === 'not_found') {
        removePendingStoryAdd(id);
        toast({
          title: data.status === 'not_found' ? 'Generation not found' : 'Generation failed',
          description: data.error || 'An error occurred during generation',
          variant: 'destructive',
        });
      }
    },
    [queryClient, removePendingGeneration, removeGenerationProgress, removePendingStoryAdd, toast, setAudioWithAutoPlay],
  );

  const handleDoneRef = useRef(handleDone);
  handleDoneRef.current = handleDone;

  useEffect(() => {
    const shouldOpen = pendingIds.size > 0;
    if (shouldOpen) {
      if (sourceRef.current) return; // already connected
      const source = new EventSource(apiClient.getGenerationQueueStreamUrl());
      sourceRef.current = source;

      source.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'done') {
            handleDoneRef.current(data);
          } else if (Array.isArray(data.items)) {
            for (const item of data.items as QueueItem[]) {
              if (
                item.state !== undefined ||
                item.progress !== undefined ||
                item.chunk_index !== undefined ||
                item.chunk_count !== undefined ||
                item.message !== undefined
              ) {
                setGenerationProgress(item.generation_id, {
                  state: item.state as 'queued' | 'loading_model' | 'generating',
                  progress: item.progress,
                  chunk_index: item.chunk_index,
                  chunk_count: item.chunk_count,
                  message: item.message,
                });
              }
            }
          }
        } catch {
          // Ignore parse errors from heartbeats etc.
        }
      };

      source.onerror = () => {
        source.close();
        sourceRef.current = null;
        queryClient.refetchQueries({ queryKey: ['history'] });
      };
    } else if (sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
    }
  }, [pendingIds.size, setGenerationProgress, queryClient]);

  // Unmount-only cleanup — close the single stream.
  useEffect(() => {
    return () => {
      sourceRef.current?.close();
      sourceRef.current = null;
    };
  }, []);
}
