import { useStoryStore } from '@/stores/storyStore';
import { StoryContent } from './StoryContent';
import { StoryList } from './StoryList';

export function StoriesTab() {
  const selectedStoryId = useStoryStore((state) => state.selectedStoryId);

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden -mx-8">
      {/* Main content area */}
      <div className="flex-1 min-h-0 flex gap-6 overflow-hidden relative">
        {/* Left Column - Story List. Hidden when inside a project so the
            editor gets full width (spec: hide projects sidebar in project). */}
        {!selectedStoryId && (
          <div className="flex flex-col min-h-0 overflow-hidden w-full max-w-[360px] shrink-0">
            <StoryList />
          </div>
        )}

        {/* Right Column - Story Content / project editor */}
        <div className="flex flex-col min-h-0 overflow-hidden flex-1">
          <StoryContent />
        </div>
      </div>
    </div>
  );
}
