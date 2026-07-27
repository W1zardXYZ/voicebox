import { describe, expect, test } from 'bun:test';
import { formatDuration, formatEngineName, formatFileSize } from './format';

describe('formatDuration', () => {
  test('formats zero', () => {
    expect(formatDuration(0)).toBe('0:00');
  });

  test('pads single-digit seconds', () => {
    expect(formatDuration(65)).toBe('1:05');
  });

  test('handles the minute boundary', () => {
    expect(formatDuration(59)).toBe('0:59');
    expect(formatDuration(60)).toBe('1:00');
  });

  test('floors fractional seconds', () => {
    expect(formatDuration(89.9)).toBe('1:29');
  });

  test('does not roll minutes into hours', () => {
    expect(formatDuration(3661)).toBe('61:01');
  });
});

describe('formatFileSize', () => {
  test('special-cases zero', () => {
    expect(formatFileSize(0)).toBe('0 Bytes');
  });

  test('formats bytes below 1 KB', () => {
    expect(formatFileSize(512)).toBe('512 Bytes');
    expect(formatFileSize(1023)).toBe('1023 Bytes');
  });

  test('formats KB, MB, and GB boundaries', () => {
    expect(formatFileSize(1024)).toBe('1 KB');
    expect(formatFileSize(1024 ** 2)).toBe('1 MB');
    expect(formatFileSize(1024 ** 3)).toBe('1 GB');
  });

  test('rounds to two decimal places', () => {
    expect(formatFileSize(1536)).toBe('1.5 KB');
    expect(formatFileSize(2_684_354_560)).toBe('2.5 GB');
    expect(formatFileSize(1_234_567)).toBe('1.18 MB');
  });
});

describe('formatEngineName', () => {
  test('maps known engines to display names', () => {
    expect(formatEngineName('luxtts')).toBe('LuxTTS');
    expect(formatEngineName('chatterbox')).toBe('Chatterbox');
    expect(formatEngineName('chatterbox_turbo')).toBe('Chatterbox Turbo');
  });

  test('defaults to Qwen when engine is undefined', () => {
    expect(formatEngineName()).toBe('Qwen');
    expect(formatEngineName(undefined, '1.7B')).toBe('Qwen');
  });

  test('appends the model size for qwen only', () => {
    expect(formatEngineName('qwen', '1.7B')).toBe('Qwen 1.7B');
    expect(formatEngineName('qwen')).toBe('Qwen');
    expect(formatEngineName('luxtts', '1.7B')).toBe('LuxTTS');
  });

  test('passes unknown engines through verbatim', () => {
    expect(formatEngineName('kokoro')).toBe('kokoro');
  });
});
