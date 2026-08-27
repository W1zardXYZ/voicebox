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
  const timelineCollapsed = useStoryStore((state) => state.timelineCollapsed);
  const audioUrl = usePlayerStore((state) => state.audioUrl);
  const { data: story } = useStory(selectedStoryId);

  // Show the whole book in the footer timeline (all chapters sequential), so
  // every segment is visible and plays end-to-end. The chapter rail in the
  // editor still drives the segment view.
  const timelineItems = story?.items ?? [];

  // Show the track editor on the stories route with a selected story that has
  // items — unless the timeline is collapsed or the user is listening to a
  // single clip, in which case the AudioPlayer bar takes over.
  const showTrackEditor =
    isStoriesRoute &&
    !!selectedStoryId &&
    !!story &&
    timelineItems.length > 0 &&
    !timelineCollapsed &&
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
