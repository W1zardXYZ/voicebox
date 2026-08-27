"""Spec §4.3/§4.4 — markdown import segmentation (pure logic, no DB)."""

import pytest

from backend.services.story_markdown import (
    clean_segment_text,
    dialogue_speaker_hint,
    parse_markdown_blocks,
    segment_markdown,
)

SAMPLE = """# Kapitel Eins

Der Wind wehte kalt über die Ebene.

Es war ein langer Weg bis zur Stadt.

## Unterabschnitt

Eine zweite Szene beginnt hier.

# Kapitel Zwei

Am Morgen erreichten sie das Tor.
"""


def test_h1_mode_creates_chapter_per_h1():
    chapters = segment_markdown(SAMPLE, mode="h1")
    assert [c.title for c in chapters] == ["Kapitel Eins", "Kapitel Zwei"]
    # Chapter 1: two paragraphs + the h2 section's paragraph (children of the
    # H1 chapter); the h2 heading itself is structural, not spoken.
    assert len(chapters[0].segments) == 3
    assert chapters[0].segments[0].text == "Der Wind wehte kalt über die Ebene."
    assert chapters[0].segments[2].text == "Eine zweite Szene beginnt hier."
    assert len(chapters[1].segments) == 1


def test_h2_mode_auto_promotes_h1():
    chapters = segment_markdown(SAMPLE, mode="h2")
    assert [c.title for c in chapters] == [
        "Kapitel Eins",
        "Kapitel Eins — Unterabschnitt",
        "Kapitel Zwei",
    ]
    # Direct H1 content gets its own chapter; the h2 section is auto-promoted
    # with its H1 parent; content after the last H1 closes its own chapter.
    assert [s.text for s in chapters[0].segments] == [
        "Der Wind wehte kalt über die Ebene.",
        "Es war ein langer Weg bis zur Stadt.",
    ]
    assert [s.text for s in chapters[1].segments] == ["Eine zweite Szene beginnt hier."]
    assert [s.text for s in chapters[2].segments] == ["Am Morgen erreichten sie das Tor."]


def test_paragraph_mode_single_chapter():
    chapters = segment_markdown(SAMPLE, mode="paragraph")
    assert len(chapters) == 1
    assert chapters[0].title == "Kapitel Eins"  # first H1 promotes the title
    assert len(chapters[0].segments) == 4  # every non-heading paragraph


def test_read_aloud_regions_become_segments():
    md = """# Szene

[read aloud: Narrator]
Es war einmal ein König.
[/read aloud]

Das ist nur Kontext, nicht gesprochen.
"""
    # speak_untagged=False → only the region is a segment.
    chapters = segment_markdown(md, mode="read_aloud", speak_untagged=False)
    assert len(chapters) == 1
    assert len(chapters[0].segments) == 1
    seg = chapters[0].segments[0]
    assert seg.text == "Es war einmal ein König."
    assert seg.speaker_hint == "Narrator"
    assert "read_aloud" in seg.tags

    # speak_untagged=True → untagged text is also segmented, flagged.
    chapters = segment_markdown(md, mode="read_aloud", speak_untagged=True)
    assert len(chapters[0].segments) == 2
    untagged = chapters[0].segments[1]
    assert "untagged" in untagged.tags
    assert untagged.text == "Das ist nur Kontext, nicht gesprochen."


def test_read_aloud_alternate_delimiters():
    md = """# T

<readaloud>
Erste Passage.
</readaloud>

<!-- read aloud -->
Zweite Passage.
<!-- /read aloud -->
"""
    chapters = segment_markdown(md, mode="read_aloud", speak_untagged=False)
    texts = [s.text for s in chapters[0].segments]
    assert texts == ["Erste Passage.", "Zweite Passage."]


def test_combine_max_chars_merges_short_segments():
    md = """# K

Kurzer Satz eins.

Kurzer Satz zwei.

Dies ist ein deutlich längerer dritter Absatz, der alleine bleibt.
"""
    # Budget 80: short+short (27) fits, but adding the long paragraph (59)
    # would exceed it — so the long one stays alone.
    chapters = segment_markdown(md, mode="h1", combine_max_chars=80)
    texts = [s.text for s in chapters[0].segments]
    assert len(texts) == 2
    assert texts[0] == "Kurzer Satz eins. Kurzer Satz zwei."


def test_heading_not_spoken():
    md = "# Titel\n\n# Kapitel\n\nText des Kapitels.\n"
    chapters = segment_markdown(md, mode="h1")
    # "Titel" is a heading → never a segment; empty chapter is not emitted.
    assert [c.title for c in chapters] == ["Kapitel"]
    assert all(s.text != "Titel" for c in chapters for s in c.segments)


def test_dialogue_speaker_hint():
    assert dialogue_speaker_hint('**Narrator:** Der Wind wehte.') == "Narrator"
    assert dialogue_speaker_hint('Marta: "Komm her!"') == "Marta"
    assert dialogue_speaker_hint("Das war der Moment: Sie lachte.") is None
    assert dialogue_speaker_hint("Normaler Satz ohne Sprecher.") is None


def test_clean_segment_text_strips_markdown():
    assert (
        clean_segment_text("**Fett** und *kursiv* und [Link](https://x.de) und <b>tag</b>")
        == "Fett und kursiv und Link und tag"
    )


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        segment_markdown("# x\n\ntext", mode="bogus")


def test_parse_blocks_tracks_offsets():
    md = "# A\n\nErster Block.\n"
    blocks = parse_markdown_blocks(md)
    assert blocks[0].kind == "heading"
    assert blocks[0].text == "A"
    content = blocks[1]
    assert content.kind == "content"
    assert md[content.start : content.end].strip() == "Erster Block."
