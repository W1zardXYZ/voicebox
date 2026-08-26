"""
Pronunciation dictionary unit tests.

CRUD paths need a live SQLite session, so these cover the pure application
hook (``apply_dictionary``) by stubbing the entry store.
"""

import backend.services.dictionary as dictionary


def _fake_entries(language):
    # Models the real store's language filter: "ALL" entries always match;
    # language-pinned entries only when the requested language matches.
    entries = [
        {"word": "stichwort", "phonemes": "ˈʃtɪçˌvɔʁt", "language": "ALL", "notes": None},
        {"word": "nvidia", "phonemes": "ɛnˈvɪdiə", "language": "ALL", "notes": None},
    ]
    if language == "en":
        entries.append({"word": "qwen", "phonemes": "kwɛn", "language": "en", "notes": None})
    return entries


def test_apply_dictionary_rewrites_known_words(monkeypatch):
    monkeypatch.setattr(dictionary, "list_entries", _fake_entries)
    out = dictionary.apply_dictionary("I use the Stichwort qwen model", language="en")
    assert "<phoneme" in out
    assert "stichwort" not in out  # replaced
    assert "Stichwort" not in out
    assert "ˈʃtɪçˌvɔʁt" in out


def test_apply_dictionary_keeps_unknown_words(monkeypatch):
    monkeypatch.setattr(dictionary, "list_entries", _fake_entries)
    out = dictionary.apply_dictionary("hello world", language="en")
    assert out == "hello world"


def test_apply_dictionary_honours_language_filter(monkeypatch):
    monkeypatch.setattr(dictionary, "list_entries", _fake_entries)
    # "qwen" is pinned to "en" only — in "de" it should stay plain, but
    # "stichwort"/"nvidia" (ALL) still rewrite.
    out = dictionary.apply_dictionary("qwen stichwort nvidia", language="de")
    assert "kwɛn" not in out
    assert "ˈʃtɪçˌvɔʁt" in out
    assert "ɛnˈvɪdiə" in out


def test_apply_dictionary_empty_db_returns_input(monkeypatch):
    monkeypatch.setattr(dictionary, "list_entries", lambda language: [])
    out = dictionary.apply_dictionary("nothing here", language="en")
    assert out == "nothing here"
