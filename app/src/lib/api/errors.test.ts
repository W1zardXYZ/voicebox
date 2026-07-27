import { describe, expect, test } from 'bun:test';
import { formatErrorDetail } from './errors';

const FALLBACK = 'HTTP error! status: 500';

describe('formatErrorDetail', () => {
  test('returns string details as-is', () => {
    expect(formatErrorDetail('Profile not found', FALLBACK)).toBe('Profile not found');
  });

  test('returns empty string details as-is (not the fallback)', () => {
    expect(formatErrorDetail('', FALLBACK)).toBe('');
  });

  test('joins FastAPI validation error arrays on msg', () => {
    const detail = [
      { loc: ['body', 'text'], msg: 'field required', type: 'value_error.missing' },
      { loc: ['body', 'seed'], msg: 'value is not a valid integer', type: 'type_error.integer' },
    ];
    expect(formatErrorDetail(detail, FALLBACK)).toBe(
      'field required; value is not a valid integer',
    );
  });

  test('falls back to message key within array entries', () => {
    expect(formatErrorDetail([{ message: 'boom' }], FALLBACK)).toBe('boom');
  });

  test('stringifies array entries with neither msg nor message', () => {
    expect(formatErrorDetail([{ code: 42 }], FALLBACK)).toBe('{"code":42}');
  });

  test('returns empty string for an empty array', () => {
    expect(formatErrorDetail([], FALLBACK)).toBe('');
  });

  test('uses message property of object details', () => {
    expect(formatErrorDetail({ message: 'engine offline' }, FALLBACK)).toBe('engine offline');
  });

  test('stringifies objects without a string message', () => {
    expect(formatErrorDetail({ message: 42, hint: 'x' }, FALLBACK)).toBe(
      '{"message":42,"hint":"x"}',
    );
    expect(formatErrorDetail({ error: 'nested' }, FALLBACK)).toBe('{"error":"nested"}');
  });

  test('falls back for null, undefined, and primitives', () => {
    expect(formatErrorDetail(null, FALLBACK)).toBe(FALLBACK);
    expect(formatErrorDetail(undefined, FALLBACK)).toBe(FALLBACK);
    expect(formatErrorDetail(404, FALLBACK)).toBe(FALLBACK);
    expect(formatErrorDetail(true, FALLBACK)).toBe(FALLBACK);
  });

  test('preserves unicode in messages', () => {
    expect(formatErrorDetail('模型未加载 🎙️', FALLBACK)).toBe('模型未加载 🎙️');
  });
});
