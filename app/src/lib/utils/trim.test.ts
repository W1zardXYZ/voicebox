import { describe, expect, test } from 'bun:test';
import { MIN_CLIP_DURATION_MS, computeTrimValues } from './trim';

// A 10-second clip with no existing trims unless stated otherwise.
const DURATION = 10_000;

describe('computeTrimValues', () => {
  describe('start handle', () => {
    test('dragging right trims from the start', () => {
      expect(computeTrimValues('start', 500, 0, 0, DURATION)).toEqual({
        trim_start_ms: 500,
        trim_end_ms: 0,
      });
    });

    test('dragging left restores previously trimmed audio', () => {
      expect(computeTrimValues('start', -300, 1000, 0, DURATION)).toEqual({
        trim_start_ms: 700,
        trim_end_ms: 0,
      });
    });

    test('clamps at zero when restoring past the clip start', () => {
      expect(computeTrimValues('start', -5000, 1000, 0, DURATION)).toEqual({
        trim_start_ms: 0,
        trim_end_ms: 0,
      });
    });

    test('never trims below the minimum clip duration', () => {
      const result = computeTrimValues('start', 99_999, 0, 2000, DURATION);
      // Clamp lands exactly on the minimum, which the guard rejects.
      expect(result).toBeNull();
    });

    test('rounds fractional millisecond deltas', () => {
      expect(computeTrimValues('start', 100.6, 0, 0, DURATION)).toEqual({
        trim_start_ms: 101,
        trim_end_ms: 0,
      });
    });

    test('preserves the untouched end trim', () => {
      expect(computeTrimValues('start', 250, 0, 400, DURATION)).toEqual({
        trim_start_ms: 250,
        trim_end_ms: 400,
      });
    });
  });

  describe('end handle', () => {
    test('dragging left trims from the end', () => {
      expect(computeTrimValues('end', -500, 0, 0, DURATION)).toEqual({
        trim_start_ms: 0,
        trim_end_ms: 500,
      });
    });

    test('dragging right restores previously trimmed audio', () => {
      expect(computeTrimValues('end', 300, 0, 1000, DURATION)).toEqual({
        trim_start_ms: 0,
        trim_end_ms: 700,
      });
    });

    test('clamps at zero when restoring past the clip end', () => {
      expect(computeTrimValues('end', 5000, 0, 1000, DURATION)).toEqual({
        trim_start_ms: 0,
        trim_end_ms: 0,
      });
    });

    test('never trims below the minimum clip duration', () => {
      expect(computeTrimValues('end', -99_999, 3000, 0, DURATION)).toBeNull();
    });
  });

  describe('minimum duration guard', () => {
    test('rejects drags that leave less than the minimum audible clip', () => {
      // 9.5s already trimmed; taking 450ms more leaves only 50ms.
      expect(computeTrimValues('start', 450, 5000, 4500, DURATION)).toBeNull();
    });

    test('allows a drag that leaves just over the minimum', () => {
      expect(computeTrimValues('start', 399, 5000, 4500, DURATION)).toEqual({
        trim_start_ms: 5399,
        trim_end_ms: 4500,
      });
    });

    test('boundary: exactly the minimum remaining is rejected', () => {
      // trim_start + trim_end === duration - MIN_CLIP_DURATION_MS
      expect(
        computeTrimValues('start', 400, 5000, 4500, DURATION)?.trim_start_ms ?? null,
      ).toBeNull();
      expect(MIN_CLIP_DURATION_MS).toBe(100);
    });
  });

  test('zero delta is a no-op that returns the initial trims', () => {
    expect(computeTrimValues('start', 0, 1200, 800, DURATION)).toEqual({
      trim_start_ms: 1200,
      trim_end_ms: 800,
    });
  });
});
