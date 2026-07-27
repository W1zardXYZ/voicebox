import { describe, expect, test } from 'bun:test';
import { parseChangelog } from './parseChangelog';

const SAMPLE = `# Changelog

All notable changes to this project will be documented in this file.

## [0.5.0] - 2026-06-01

### Added

- Story track editor
- Cloud login

## [0.4.1]

### Fixed

- Trim clamping

## [0.4.0] - 2026-04-15

Initial public release.

[0.5.0]: https://example.com/compare/v0.4.1...v0.5.0
[0.4.1]: https://example.com/compare/v0.4.0...v0.4.1
`;

describe('parseChangelog', () => {
  test('splits entries on version headings', () => {
    const entries = parseChangelog(SAMPLE);
    expect(entries.map((e) => e.version)).toEqual(['0.5.0', '0.4.1', '0.4.0']);
  });

  test('extracts the date when present and null otherwise', () => {
    const entries = parseChangelog(SAMPLE);
    expect(entries[0].date).toBe('2026-06-01');
    expect(entries[1].date).toBeNull();
  });

  test('keeps the markdown body between headings', () => {
    const entries = parseChangelog(SAMPLE);
    expect(entries[0].body).toBe('### Added\n\n- Story track editor\n- Cloud login');
    expect(entries[2].body).toBe('Initial public release.');
  });

  test('strips trailing link reference definitions from the last body', () => {
    const entries = parseChangelog(SAMPLE);
    expect(entries[2].body).toBe('Initial public release.');
    expect(entries[2].body).not.toContain('example.com');
  });

  test('returns an empty array when no headings match', () => {
    expect(parseChangelog('')).toEqual([]);
    expect(parseChangelog('# Changelog\n\nNothing yet.')).toEqual([]);
  });

  test('handles a heading with an empty body', () => {
    const entries = parseChangelog('## [1.0.0] - 2026-01-01\n');
    expect(entries).toEqual([{ version: '1.0.0', date: '2026-01-01', body: '' }]);
  });

  test('accepts non-semver headings like Unreleased', () => {
    const entries = parseChangelog('## [Unreleased]\n\n### Added\n\n- WIP\n');
    expect(entries[0].version).toBe('Unreleased');
    expect(entries[0].date).toBeNull();
    expect(entries[0].body).toBe('### Added\n\n- WIP');
  });
});
