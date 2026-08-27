import { create } from 'zustand';

/** Live progress for one generation, mirroring the backend status payload. */
export interface GenerationProgress {
  state?: 'queued' | 'loading_model' | 'generating';
  progress?: number | null; // 0..1 while generating (chunk-level)
  chunk_index?: number | null;
  chunk_count?: number | null;
  message?: string | null;
}

interface GenerationState {
  /** IDs of generations currently in progress */
  pendingGenerationIds: Set<string>;
  /** Whether any generation is in progress (derived from pendingGenerationIds) */
  isGenerating: boolean;
  /** Map of generationId → storyId for deferred story additions */
  pendingStoryAdds: Map<string, string>;
  /** Live progress per generation, fed by the status SSE (spec §6). */
  progressById: Map<string, GenerationProgress>;
  addPendingGeneration: (id: string) => void;
  removePendingGeneration: (id: string) => void;
  addPendingStoryAdd: (generationId: string, storyId: string) => void;
  removePendingStoryAdd: (generationId: string) => string | undefined;
  setActiveGenerationId: (id: string | null) => void;
  activeGenerationId: string | null;
  setGenerationProgress: (id: string, data: GenerationProgress) => void;
  removeGenerationProgress: (id: string) => void;
}

export const useGenerationStore = create<GenerationState>((set, get) => ({
  pendingGenerationIds: new Set(),
  isGenerating: false,
  activeGenerationId: null,
  pendingStoryAdds: new Map(),
  progressById: new Map(),

  addPendingGeneration: (id) =>
    set((state) => {
      const next = new Set(state.pendingGenerationIds);
      next.add(id);
      return { pendingGenerationIds: next, isGenerating: true };
    }),

  removePendingGeneration: (id) =>
    set((state) => {
      const next = new Set(state.pendingGenerationIds);
      next.delete(id);
      const progress = new Map(state.progressById);
      progress.delete(id);
      return { pendingGenerationIds: next, isGenerating: next.size > 0, progressById: progress };
    }),

  addPendingStoryAdd: (generationId, storyId) =>
    set((state) => {
      const next = new Map(state.pendingStoryAdds);
      next.set(generationId, storyId);
      return { pendingStoryAdds: next };
    }),

  removePendingStoryAdd: (generationId) => {
    const storyId = get().pendingStoryAdds.get(generationId);
    if (storyId) {
      set((state) => {
        const next = new Map(state.pendingStoryAdds);
        next.delete(generationId);
        return { pendingStoryAdds: next };
      });
    }
    return storyId;
  },

  setActiveGenerationId: (id) => set({ activeGenerationId: id }),

  setGenerationProgress: (id, data) =>
    set((state) => {
      const next = new Map(state.progressById);
      next.set(id, data);
      return { progressById: next };
    }),

  removeGenerationProgress: (id) =>
    set((state) => {
      if (!state.progressById.has(id)) return {};
      const next = new Map(state.progressById);
      next.delete(id);
      return { progressById: next };
    }),
}));
