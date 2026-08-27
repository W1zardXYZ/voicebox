import { useRouterState } from '@tanstack/react-router';
import { TitleBarDragRegion } from '@/components/TitleBarDragRegion';
import { AudioKeepAlive } from '@/components/AudioPlayer/AudioKeepAlive';
import { AudioPlayer } from '@/components/AudioPlayer/AudioPlayer';
import { StoryTrackEditor } from '@/components/StoriesTab/StoryTrackEditor';
import { GenerationQueuePanel } from '@/components/AppFrame/GenerationQueuePanel';
import { TOP_SAFE_AREA_PADDING } from '@/lib/constants/ui';
import { cn } from '@/lib/utils/cn';
import { useStoryStore } from '@/stores/storyStore';
import { usePlayerStore } from '@/stores/playerStore';
import { useStory } from '@/lib/hooks/useStories';

interface AppFrameProps {
  children: React.ReactNode;
}

export function AppFrame({ children }: AppFrameProps) {
  const routerState = useRouterState();
  const isStoriesRoute = routerState.location.pathname === '/stories';

  const selectedStoryId = useStoryStore((state) => state.selectedStoryId);
  const activeChapterId = useStoryStore((state) => state.activeChapterId);
  const audioUrl = usePlayerStore((state) => state.audioUrl);
  const { data: story } = useStory(selectedStoryId);

  // Scope the footer timeline to the chapter being edited: when the active
  // chapter has segments, only show the items traced back to them. Flat
  // (legacy) stories with no chapters keep showing every item.
  const activeChapter =
    story?.chapters.find((c) => c.id === activeChapterId) ?? story?.chapters[0] ?? null;
  const activeSegmentIds = new Set(activeChapter?.segments.map((s) => s.id) ?? []);
  const timelineItems =
    !story || activeSegmentIds.size === 0
      ? story?.items ?? []
      : (story.items ?? []).filter(
          (item) => item.story_segment_id && activeSegmentIds.has(item.story_segment_id),
        );

  // Show the track editor on the stories route with a selected story that has
  // (chapter-scoped) items — unless the user is listening to a single clip, in
  // which case the AudioPlayer bar takes over.
  const showTrackEditor =
    isStoriesRoute &&
    !!selectedStoryId &&
    !!story &&
    timelineItems.length > 0 &&
    !audioUrl;

  return (
    <div
      className={cn('h-screen bg-background flex flex-col overflow-hidden', TOP_SAFE_AREA_PADDING)}
    >
      <TitleBarDragRegion />
      <AudioKeepAlive />
      {children}
      {showTrackEditor ? (
        <StoryTrackEditor storyId={story!.id} items={timelineItems} />
      ) : (
        <AudioPlayer />
      )}
      <GenerationQueuePanel />
    </div>
  );
}
