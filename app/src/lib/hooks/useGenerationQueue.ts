import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/api/client';
import { useGenerationStore } from '@/stores/generationStore';

/**
 * Polls GET /generate/queue (spec §6) while any generation is active.
 * Polling stops when the queue drains so the panel doesn't sit on a
 * never-ending background request.
 */
export function useGenerationQueue() {
  const isGenerating = useGenerationStore((s) => s.isGenerating);
  const hasProgress = useGenerationStore((s) => s.progressById.size > 0);

  return useQuery({
    queryKey: ['generationQueue'],
    queryFn: () => apiClient.getGenerationQueue(),
    refetchInterval: (query) => {
      const hasItems = (query.state.data?.items.length ?? 0) > 0;
      return isGenerating || hasProgress || hasItems ? 2000 : false;
    },
  });
}
