import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/lib/api/client';
import type {
  MarkdownImportCommitRequest,
  MarkdownImportRequest,
  StoryCharacterCreate,
  StoryCharacterUpdate,
  StoryCreate,
  StoryItemBatchUpdate,
  StoryItemCreate,
  StoryItemMove,
  StoryItemReorder,
  StoryItemSplit,
  StoryItemTrim,
  StoryItemVersionUpdate,
  StoryItemVolumeUpdate,
  StorySegmentUpdate,
} from '@/lib/api/types';
import { usePlatform } from '@/platform/PlatformContext';
import { useGenerationStore } from '@/stores/generationStore';

export function useStories() {
  return useQuery({
    queryKey: ['stories'],
    queryFn: () => apiClient.listStories(),
  });
}

export function useStory(storyId: string | null) {
  return useQuery({
    queryKey: ['stories', storyId],
    queryFn: () => apiClient.getStory(storyId!),
    enabled: !!storyId,
  });
}

export function useCreateStory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: StoryCreate) => apiClient.createStory(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
    },
  });
}

export function useUpdateStory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ storyId, data }: { storyId: string; data: StoryCreate }) =>
      apiClient.updateStory(storyId, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      queryClient.invalidateQueries({ queryKey: ['stories', variables.storyId] });
    },
  });
}

export function useDeleteStory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (storyId: string) => apiClient.deleteStory(storyId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
    },
  });
}

export function useAddStoryItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ storyId, data }: { storyId: string; data: StoryItemCreate }) =>
      apiClient.addStoryItem(storyId, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      queryClient.invalidateQueries({ queryKey: ['stories', variables.storyId] });
    },
  });
}

export function useRemoveStoryItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ storyId, itemId }: { storyId: string; itemId: string }) =>
      apiClient.removeStoryItem(storyId, itemId),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      queryClient.invalidateQueries({ queryKey: ['stories', variables.storyId] });
    },
  });
}

export function useUpdateStoryItemTimes() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ storyId, data }: { storyId: string; data: StoryItemBatchUpdate }) =>
      apiClient.updateStoryItemTimes(storyId, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      queryClient.invalidateQueries({ queryKey: ['stories', variables.storyId] });
    },
  });
}

export function useReorderStoryItems() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ storyId, data }: { storyId: string; data: StoryItemReorder }) =>
      apiClient.reorderStoryItems(storyId, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      queryClient.invalidateQueries({ queryKey: ['stories', variables.storyId] });
    },
  });
}

export function useMoveStoryItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      storyId,
      itemId,
      data,
    }: {
      storyId: string;
      itemId: string;
      data: StoryItemMove;
    }) => apiClient.moveStoryItem(storyId, itemId, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      queryClient.invalidateQueries({ queryKey: ['stories', variables.storyId] });
    },
  });
}

export function useTrimStoryItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      storyId,
      itemId,
      data,
    }: {
      storyId: string;
      itemId: string;
      data: StoryItemTrim;
    }) => apiClient.trimStoryItem(storyId, itemId, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      queryClient.invalidateQueries({ queryKey: ['stories', variables.storyId] });
    },
  });
}

export function useUpdateStoryItemVolume() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      storyId,
      itemId,
      data,
    }: {
      storyId: string;
      itemId: string;
      data: StoryItemVolumeUpdate;
    }) => apiClient.updateStoryItemVolume(storyId, itemId, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      queryClient.invalidateQueries({ queryKey: ['stories', variables.storyId] });
    },
  });
}

export function useSplitStoryItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      storyId,
      itemId,
      data,
    }: {
      storyId: string;
      itemId: string;
      data: StoryItemSplit;
    }) => apiClient.splitStoryItem(storyId, itemId, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      queryClient.invalidateQueries({ queryKey: ['stories', variables.storyId] });
    },
  });
}

export function useDuplicateStoryItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ storyId, itemId }: { storyId: string; itemId: string }) =>
      apiClient.duplicateStoryItem(storyId, itemId),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      queryClient.invalidateQueries({ queryKey: ['stories', variables.storyId] });
    },
  });
}

export function useSetStoryItemVersion() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      storyId,
      itemId,
      data,
    }: {
      storyId: string;
      itemId: string;
      data: StoryItemVersionUpdate;
    }) => apiClient.setStoryItemVersion(storyId, itemId, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      queryClient.invalidateQueries({ queryKey: ['stories', variables.storyId] });
    },
  });
}

export function useExportStoryAudio() {
  const platform = usePlatform();

  return useMutation({
    mutationFn: async ({
      storyId,
      storyName,
      format = 'wav',
      scope = 'all',
    }: {
      storyId: string;
      storyName: string;
      format?: 'wav' | 'mp3';
      scope?: 'all' | 'chapters';
    }) => {
      const blob = await apiClient.exportStoryAudio(storyId, { format, scope });

      // Create safe filename
      const safeName = storyName
        .substring(0, 50)
        .replace(/[^a-z0-9]/gi, '-')
        .toLowerCase();
      const ext = scope === 'chapters' ? 'zip' : format === 'mp3' ? 'mp3' : 'wav';
      const filename = `${safeName || 'story'}${scope === 'chapters' ? '-chapters' : ''}.${ext}`;

      await platform.filesystem.saveFile(filename, blob, [
        {
          name: ext.toUpperCase(),
          extensions: [ext],
        },
      ]);

      return blob;
    },
  });
}

// ── Chapters / segments / markdown import (spec §4) ────────────────────────

function invalidateStoryQueries(queryClient: ReturnType<typeof useQueryClient>, storyId: string) {
  queryClient.invalidateQueries({ queryKey: ['stories'] });
  queryClient.invalidateQueries({ queryKey: ['stories', storyId] });
}

export function useMarkdownImportPreview() {
  return useMutation({
    mutationFn: ({ storyId, data }: { storyId: string; data: MarkdownImportRequest }) =>
      apiClient.importMarkdownPreview(storyId, data),
  });
}

export function useCommitMarkdownImport() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ storyId, data }: { storyId: string; data: MarkdownImportCommitRequest }) =>
      apiClient.commitMarkdownImport(storyId, data),
    onSuccess: (_, variables) => invalidateStoryQueries(queryClient, variables.storyId),
  });
}

export function useCreateChapter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ storyId, title }: { storyId: string; title: string }) =>
      apiClient.createChapter(storyId, { title }),
    onSuccess: (_, variables) => invalidateStoryQueries(queryClient, variables.storyId),
  });
}

export function useUpdateChapter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      storyId,
      chapterId,
      data,
    }: {
      storyId: string;
      chapterId: string;
      data: { title?: string; order_index?: number };
    }) => apiClient.updateChapter(storyId, chapterId, data),
    onSuccess: (_, variables) => invalidateStoryQueries(queryClient, variables.storyId),
  });
}

export function useDeleteChapter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ storyId, chapterId }: { storyId: string; chapterId: string }) =>
      apiClient.deleteChapter(storyId, chapterId),
    onSuccess: (_, variables) => invalidateStoryQueries(queryClient, variables.storyId),
  });
}

export function useCreateSegment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      storyId,
      data,
    }: {
      storyId: string;
      data: { chapter_id: string; text: string; profile_id?: string | null };
    }) => apiClient.createSegment(storyId, data),
    onSuccess: (_, variables) => invalidateStoryQueries(queryClient, variables.storyId),
  });
}

export function useUpdateSegment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      storyId,
      segmentId,
      data,
    }: {
      storyId: string;
      segmentId: string;
      data: StorySegmentUpdate;
    }) => apiClient.updateSegment(storyId, segmentId, data),
    onSuccess: (_, variables) => invalidateStoryQueries(queryClient, variables.storyId),
  });
}

export function useDeleteSegment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ storyId, segmentId }: { storyId: string; segmentId: string }) =>
      apiClient.deleteSegment(storyId, segmentId),
    onSuccess: (_, variables) => invalidateStoryQueries(queryClient, variables.storyId),
  });
}

export function useSegmentVolume() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      storyId,
      segmentId,
      volume,
    }: {
      storyId: string;
      segmentId: string;
      volume: number;
    }) => apiClient.setSegmentVolume(storyId, segmentId, volume),
    onSuccess: (_, variables) => invalidateStoryQueries(queryClient, variables.storyId),
  });
}

export function useGenerateSegment() {
  const queryClient = useQueryClient();
  const addPendingGeneration = useGenerationStore((s) => s.addPendingGeneration);
  return useMutation({
    mutationFn: ({
      storyId,
      segmentId,
      profileId,
    }: {
      storyId: string;
      segmentId: string;
      profileId?: string | null;
    }) => apiClient.generateSegment(storyId, segmentId, { profile_id: profileId }),
    onSuccess: (segment, variables) => {
      // Register the generation so the progress SSE tracks it and refreshes
      // the story/timeline once it completes.
      if (segment?.generation_id) addPendingGeneration(segment.generation_id);
      invalidateStoryQueries(queryClient, variables.storyId);
    },
  });
}

export function useCreateCharacter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ storyId, data }: { storyId: string; data: StoryCharacterCreate }) =>
      apiClient.createCharacter(storyId, data),
    onSuccess: (_, variables) => invalidateStoryQueries(queryClient, variables.storyId),
  });
}

export function useUpdateCharacter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      storyId,
      characterId,
      data,
    }: {
      storyId: string;
      characterId: string;
      data: StoryCharacterUpdate;
    }) => apiClient.updateCharacter(storyId, characterId, data),
    onSuccess: (_, variables) => invalidateStoryQueries(queryClient, variables.storyId),
  });
}

export function useDeleteCharacter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ storyId, characterId }: { storyId: string; characterId: string }) =>
      apiClient.deleteCharacter(storyId, characterId),
    onSuccess: (_, variables) => invalidateStoryQueries(queryClient, variables.storyId),
  });
}

export function useReorderSegments() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ storyId, segmentIds }: { storyId: string; segmentIds: string[] }) =>
      apiClient.reorderSegments(storyId, segmentIds),
    onSuccess: (_, variables) => invalidateStoryQueries(queryClient, variables.storyId),
  });
}

export function useGenerateManySegments() {
  const queryClient = useQueryClient();
  const addPendingGeneration = useGenerationStore((s) => s.addPendingGeneration);
  return useMutation({
    mutationFn: ({
      storyId,
      segmentIds,
      profileId,
    }: {
      storyId: string;
      segmentIds: string[];
      profileId?: string | null;
    }) => apiClient.generateManySegments(storyId, { segment_ids: segmentIds, profile_id: profileId }),
    onSuccess: (segments, variables) => {
      // Track every enqueued generation so the progress SSE refreshes the
      // story/timeline as each one finishes.
      (segments ?? []).forEach((s) => {
        if (s?.generation_id) addPendingGeneration(s.generation_id);
      });
      invalidateStoryQueries(queryClient, variables.storyId);
    },
  });
}
