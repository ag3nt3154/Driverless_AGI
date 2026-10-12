"""tests/rpa/test_keys.py — the driver-neutral `key` chord syntax."""
from __future__ import annotations

import pytest

from rpa import RpaError
from rpa.keys import escape_uia_text, parse_chord, to_uia


@pytest.mark.parametrize(("spec", "expected"), [
    ("enter", "{Enter}"),
    ("ctrl+s", "{Ctrl}s"),
    ("Ctrl+Shift+S", "{Ctrl}{Shift}s"),
    ("alt+f4", "{Alt}{F4}"),
    ("shift+tab", "{Shift}{Tab}"),
    ("esc", "{Esc}"),
])
def test_chords_translate_to_uiautomation_notation(spec, expected):
    assert to_uia(spec) == expected


@pytest.mark.parametrize("spec", ["^+s", "ctrl+", "", "hyper+s", "ctrl+ctrl+s", "ctrl+enterr"])
def test_bad_chords_are_rejected_with_the_syntax(spec):
    with pytest.raises(RpaError):
        parse_chord(spec)


def test_literal_text_braces_are_escaped_for_uiautomation():
    assert escape_uia_text("a{b}c") == "a{{}b{}}c"
    assert escape_uia_text("^+s") == "^+s"  # only braces are special to SendKeys


def test_plus_key_with_a_modifier():
    assert parse_chord("ctrl++") == (("ctrl",), "+")
