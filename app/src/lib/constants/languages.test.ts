import { describe, expect, test } from 'bun:test';
import {
  ALL_LANGUAGES,
  ENGINE_LANGUAGES,
  LANGUAGE_CODES,
  LANGUAGE_OPTIONS,
  getLanguageOptionsForEngine,
} from './languages';

describe('ENGINE_LANGUAGES', () => {
  test('every engine maps only to codes defined in ALL_LANGUAGES', () => {
    for (const [engine, codes] of Object.entries(ENGINE_LANGUAGES)) {
      for (const code of codes) {
        expect(ALL_LANGUAGES[code], `${engine} references unknown code "${code}"`).toBeDefined();
      }
    }
  });

  test('no engine lists a language twice', () => {
    for (const [engine, codes] of Object.entries(ENGINE_LANGUAGES)) {
      expect(new Set(codes).size, `${engine} has duplicate codes`).toBe(codes.length);
    }
  });

  test('every engine supports at least English', () => {
    for (const codes of Object.values(ENGINE_LANGUAGES)) {
      expect(codes).toContain('en');
    }
  });

  test('English-only engines list exactly one language', () => {
    expect(ENGINE_LANGUAGES.luxtts).toEqual(['en']);
    expect(ENGINE_LANGUAGES.chatterbox_turbo).toEqual(['en']);
  });

  test('qwen and qwen_custom_voice support the same languages', () => {
    expect(ENGINE_LANGUAGES.qwen_custom_voice).toEqual(ENGINE_LANGUAGES.qwen);
  });
});

describe('getLanguageOptionsForEngine', () => {
  test('builds value/label pairs from ALL_LANGUAGES', () => {
    expect(getLanguageOptionsForEngine('luxtts')).toEqual([{ value: 'en', label: 'English' }]);
  });

  test('preserves the engine declaration order', () => {
    const values = getLanguageOptionsForEngine('qwen').map((o) => o.value);
    expect(values).toEqual([...ENGINE_LANGUAGES.qwen]);
  });

  test('falls back to qwen languages for unknown engines', () => {
    expect(getLanguageOptionsForEngine('does-not-exist')).toEqual(
      getLanguageOptionsForEngine('qwen'),
    );
  });
});

describe('language option exports', () => {
  test('LANGUAGE_CODES covers every ALL_LANGUAGES key exactly once', () => {
    const codes: string[] = [...LANGUAGE_CODES].sort();
    expect(codes).toEqual(Object.keys(ALL_LANGUAGES).sort());
    expect(new Set(LANGUAGE_CODES).size).toBe(LANGUAGE_CODES.length);
  });

  test('LANGUAGE_OPTIONS labels match ALL_LANGUAGES', () => {
    for (const option of LANGUAGE_OPTIONS) {
      expect(option.label).toBe(ALL_LANGUAGES[option.value]);
    }
  });
});
