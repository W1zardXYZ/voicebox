import type { StoryItemTrim } from '@/lib/api/types';

/** Clips are never allowed to shrink below this effective duration. */
export const MIN_CLIP_DURATION_MS = 100;

/**
 * Computes new trim values for a clip while a trim handle is being dragged.
 *
 * `deltaMs` is the signed drag distance converted to milliseconds. Dragging
 * the start handle right increases `trim_start_ms` (trims more from the
 * start); dragging it left restores. The end handle mirrors this for
 * `trim_end_ms`. Both values are clamped so the clip keeps at least
 * MIN_CLIP_DURATION_MS of audible content.
 *
 * Returns null when the drag would leave less than the minimum duration.
 */
export function computeTrimValues(
  side: 'start' | 'end',
  deltaMs: number,
  initialTrimStart: number,
  initialTrimEnd: number,
  originalDurationMs: number,
): StoryItemTrim | null {
  let newTrimStart = initialTrimStart;
  let newTrimEnd = initialTrimEnd;

  if (side === 'start') {
    newTrimStart = Math.round(
      Math.max(
        0,
        Math.min(
          initialTrimStart + deltaMs,
          originalDurationMs - initialTrimEnd - MIN_CLIP_DURATION_MS,
        ),
      ),
    );
  } else {
    newTrimEnd = Math.round(
      Math.max(
        0,
        Math.min(
          initialTrimEnd - deltaMs,
          originalDurationMs - initialTrimStart - MIN_CLIP_DURATION_MS,
        ),
      ),
    );
  }

  if (newTrimStart + newTrimEnd >= originalDurationMs - MIN_CLIP_DURATION_MS) {
    return null;
  }

  return {
    trim_start_ms: newTrimStart,
    trim_end_ms: newTrimEnd,
  };
}
