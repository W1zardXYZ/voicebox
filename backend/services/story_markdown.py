"""
Markdown segmentation for story imports (spec §4.3 / §4.4).

Pure logic — no DB, no network. Takes markdown text and a split *mode* and
produces a chapter → segment preview:

- **h1**: one chapter per ``#`` heading; sub-headings are structural (not
  spoken); every content block becomes a segment.
- **h2**: one chapter per ``##`` heading (``#`` parents auto-promoted into the
  chapter title).
- **paragraph**: a single chapter; every non-empty paragraph is a segment.
- **read_aloud**: chapters by ``#``; only content inside a read-aloud region
  becomes a segment, unless ``speak_untagged`` is on (then untagged content is
  also segmented, flagged with the ``untagged`` tag).

Supported read-aloud delimiters (spec §4.4):

- ``[read aloud]`` … ``[/read aloud]`` (optionally ``[read aloud: Narrator]``
  to pre-assign a speaker)
- ``<readaloud>`` … ``</readaloud>``
- ``[[read]]`` … ``[[/read]]``
- ``<!-- read aloud -->`` … ``<!-- /read aloud -->``

Deliberately line-based rather than a full CommonMark parse: the segmentation
contract only needs headings, paragraph boundaries, and the tag regions, and a
small tested state machine keeps the dependency surface at zero.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── read-aloud region delimiters ──────────────────────────────────────────

# (opener regex with optional speaker-hint capture group, closer regex)
_READ_ALOUD_PAIRS: list[tuple[re.Pattern, re.Pattern]] = [
    (
        re.compile(r"\[\s*read aloud(?:\s*:\s*([^\]]*?))?\s*\]", re.IGNORECASE),
        re.compile(r"\[\s*/\s*read aloud\s*\]", re.IGNORECASE),
    ),
    (
        re.compile(r"<readaloud(?:\s+speaker\s*=\s*\"([^\"]*)\")?\s*>", re.IGNORECASE),
        re.compile(r"</readaloud\s*>", re.IGNORECASE),
    ),
    (re.compile(r"\[\[\s*read\s*\]\]"), re.compile(r"\[\[\s*/\s*read\s*\]\]")),
    (
        re.compile(r"<!--\s*read aloud(?:\s*:\s*([^-]*?))?\s*-->", re.IGNORECASE),
        re.compile(r"<!--\s*/\s*read aloud\s*-->", re.IGNORECASE),
    ),
]

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")

# Dialogue-style speaker hints: `**Narrator:** text` / `Narrator: "..."`.
_DIALOGUE_RE = re.compile(
    r"^\s*(?:\*\*)?([A-Za-z\u00C0-\u017F][\w\-' ]{0,40}?)(?:\*\*)?\s*[:：]\s*(.+)$",
    re.DOTALL,
)

# Words that can never be part of a character name — rejects prose like
# "Das war der Moment: Sie lachte." while keeping "Narrator"/"Marta"/"Uncle Bob".
_DIALOGUE_STOPWORDS = frozenset(
    {
        "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem",
        "einer", "und", "oder", "aber", "war", "ist", "sind", "waren", "wird",
        "werden", "wurde", "hat", "haben", "hatte", "es", "sie", "er", "wir",
        "ich", "du", "ihr", "als", "wie", "so", "da", "dann", "dort", "hier",
        "nicht", "kein", "keine", "mit", "ohne", "auf", "an", "in", "zu", "bei",
        "von", "aus", "nach", "über", "für", "gegen", "um", "the", "and", "was",
        "but", "for", "with", "that", "this", "then", "when", "there",
    }
)

_MARKDOWN_INLINE_RE = [
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),  # bold
    (re.compile(r"__(.+?)__"), r"\1"),      # bold
    (re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)"), r"\1"),  # italic
    (re.compile(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)"), r"\1"),        # italic
    (re.compile(r"\[([^\]]+)\]\([^)]+\)"), r"\1"),                # links
    (re.compile(r"<[^>]+>"), ""),                                 # html tags
]

_VALID_MODES = ("h1", "h2", "paragraph", "read_aloud")


@dataclass
class Block:
    """A line-group: either a heading or a run of content lines."""

    kind: str  # "heading" | "content"
    level: int = 0
    text: str = ""
    speaker_hint: str | None = None
    tags: list[str] = field(default_factory=list)
    start: int = 0  # char offset into the source markdown
    end: int = 0


@dataclass
class Segment:
    """One proposed segment."""

    text: str
    speaker_hint: str | None = None
    tags: list[str] = field(default_factory=list)
    source_span: str = ""


@dataclass
class Chapter:
    """One proposed chapter."""

    title: str
    level: int
    segments: list[Segment] = field(default_factory=list)


def clean_segment_text(text: str) -> str:
    """Strip inline markdown formatting from text that will be synthesized."""
    out = text
    for pattern, repl in _MARKDOWN_INLINE_RE:
        out = pattern.sub(repl, out)
    # Collapse runs of whitespace (incl. newlines inside a block) to single
    # spaces, then trim.
    return re.sub(r"\s+", " ", out).strip()


def dialogue_speaker_hint(text: str) -> str | None:
    """Return a speaker hint for dialogue-style lines, else None.

    Matches ``Character: "…"`` and ``**Character:** …`` when the "character"
    looks like a name (short, no sentence-ending punctuation).
    """
    m = _DIALOGUE_RE.match(text)
    if not m:
        return None
    name = m.group(1).strip()
    if not name or len(name) > 40:
        return None
    # A real dialogue line's remainder should be short-ish; guard against
    # prose with an interior colon.
    remainder = m.group(2).strip()
    if not remainder or len(remainder) > 300:
        return None
    if re.search(r"[.!?]\s*$", name):
        return None
    name_words = name.lower().split()
    if any(w in _DIALOGUE_STOPWORDS for w in name_words):
        return None
    return name


def parse_markdown_blocks(markdown: str) -> list[Block]:
    """Split *markdown* into heading/content blocks, tracking read-aloud
    regions and their speaker hints."""
    blocks: list[Block] = []
    in_region = False
    region_speaker: str | None = None

    buf: list[str] = []
    buf_start = 0
    # Region state is snapshotted when a buffer *starts*: the closer line can
    # reset in_region/region_speaker before the buffer is flushed.
    buf_region = False
    buf_speaker: str | None = None
    offset = 0

    def flush() -> None:
        nonlocal buf, buf_region, buf_speaker
        if not buf:
            return
        text = clean_segment_text("".join(buf))
        if text:
            blocks.append(
                Block(
                    kind="content",
                    text=text,
                    speaker_hint=buf_speaker,
                    tags=["read_aloud"] if buf_region else [],
                    start=buf_start,
                    end=offset,
                )
            )
        buf = []
        buf_region = False
        buf_speaker = None

    for line in markdown.splitlines(keepends=True):
        line_len = len(line)
        line_start = offset
        offset += line_len
        content = line.rstrip("\r\n")

        stripped = content.strip()
        if not stripped:
            flush()
            continue

        if not in_region:
            heading = _HEADING_RE.match(content)
            if heading:
                flush()
                blocks.append(
                    Block(
                        kind="heading",
                        level=len(heading.group(1)),
                        text=heading.group(2).strip(),
                        start=line_start,
                        end=line_start + len(content),
                    )
                )
                continue

        # Detect closer first so `[read aloud] … [/read aloud]` on one line
        # closes before the next opener would apply.
        region_piece = content
        if in_region:
            for _open_re, close_re in _READ_ALOUD_PAIRS:
                m = close_re.search(region_piece)
                if m:
                    region_piece = region_piece[: m.start()]
                    in_region = False
                    region_speaker = None
                    break

        if not in_region:
            for open_re, _close_re in _READ_ALOUD_PAIRS:
                m = open_re.search(region_piece)
                if m:
                    hint = m.group(1).strip() if m.lastindex else None
                    region_speaker = hint or None
                    in_region = True
                    region_piece = region_piece[: m.start()] + region_piece[m.end() :]
                    break

        if region_piece.strip():
            if not buf:
                buf_start = line_start
                buf_region = in_region
                buf_speaker = region_speaker
            buf.append(region_piece)
        else:
            # The line was entirely a tag — flush any pending content so a
            # region boundary never merges into an unrelated block.
            flush()

    flush()
    return blocks


def _build_chapter(
    blocks: list[Block], title: str, level: int, mode: str, speak_untagged: bool
) -> Chapter:
    chapter = Chapter(title=title, level=level)
    for b in blocks:
        if b.kind != "content":
            continue
        is_region = "read_aloud" in b.tags
        if mode == "read_aloud" and not is_region and not speak_untagged:
            continue
        tags = list(b.tags)
        if mode == "read_aloud" and not is_region:
            tags.append("untagged")
        chapter.segments.append(
            Segment(
                text=b.text,
                speaker_hint=b.speaker_hint or dialogue_speaker_hint(b.text),
                tags=tags,
                source_span=f"{b.start}:{b.end}",
            )
        )
    return chapter


def _apply_combine(chapter: Chapter, combine_max_chars: int) -> None:
    """Merge consecutive segments whose combined length stays under
    *combine_max_chars*, so we don't produce thousands of micro-segments."""
    if combine_max_chars <= 0 or len(chapter.segments) < 2:
        return
    merged: list[Segment] = []
    for seg in chapter.segments:
        if merged:
            prev = merged[-1]
            if len(prev.text) + len(seg.text) + 1 <= combine_max_chars:
                prev.text = f"{prev.text} {seg.text}"
                prev.tags = sorted(set(prev.tags + seg.tags))
                prev.speaker_hint = prev.speaker_hint or seg.speaker_hint
                continue
        merged.append(Segment(text=seg.text, speaker_hint=seg.speaker_hint, tags=list(seg.tags), source_span=seg.source_span))
    chapter.segments = merged


def segment_markdown(
    markdown: str,
    *,
    mode: str = "h1",
    speak_untagged: bool = True,
    combine_max_chars: int = 0,
) -> list[Chapter]:
    """Segment *markdown* into chapters/segments per the split *mode*.

    Raises ``ValueError`` for an unknown mode. Returns a list of Chapter
    dataclasses (see the module docstring for per-mode semantics).
    """
    if mode not in _VALID_MODES:
        raise ValueError(f"Unknown split mode: {mode}. Use one of {', '.join(_VALID_MODES)}")

    blocks = parse_markdown_blocks(markdown)
    chapters: list[Chapter] = []
    pending_title: str | None = None  # title of the chapter `current` belongs to
    pending_level = 0
    current: list[Block] = []
    pending_h1: str | None = None  # h2 mode: most recent H1, auto-promoted
    single_title: str | None = None  # paragraph mode: first H1 becomes the title

    def flush() -> None:
        nonlocal current, pending_title
        if not current:
            current = []
            pending_title = None
            return
        chapter = _build_chapter(
            current, pending_title or "Untitled", pending_level, mode, speak_untagged
        )
        _apply_combine(chapter, combine_max_chars)
        if chapter.segments:
            chapters.append(chapter)
        current = []
        pending_title = None

    for b in blocks:
        if b.kind == "heading":
            if mode == "paragraph":
                if b.level == 1 and single_title is None and not chapters and not current:
                    single_title = b.text
                continue
            if mode in ("h1", "read_aloud"):
                if b.level == 1:
                    flush()
                    pending_title = b.text
                    pending_level = 1
                # deeper headings are structural — not spoken
                continue
            # mode == "h2"
            if b.level == 1:
                flush()
                pending_title = b.text
                pending_level = 1
                pending_h1 = b.text
            elif b.level == 2:
                flush()
                pending_title = f"{pending_h1} — {b.text}" if pending_h1 else b.text
                pending_level = 2
                pending_h1 = None
            continue

        # content block — belongs to the chapter pending_title names
        current.append(b)

    if mode == "paragraph" and single_title and pending_title is None:
        pending_title = single_title
    flush()

    if not chapters:
        chapters.append(Chapter(title="Untitled", level=0))

    return chapters
