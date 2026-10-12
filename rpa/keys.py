"""rpa/keys.py — one key-chord syntax for every driver (`computer_use_interact_with_window` action `key`).

A chord is `+`-joined, case-insensitive: optional modifiers then one key, e.g.
`enter`, `ctrl+s`, `ctrl+shift+s`, `alt+f4`, `shift+tab`. Each driver translates
a parsed chord into its own notation (uiautomation `{Ctrl}{Shift}s`, WebDriver
key codes), so the model never sees driver-specific syntax such as `^+s`.
"""
from __future__ import annotations

from rpa import RpaError

MODIFIERS = ("ctrl", "shift", "alt", "win")

#: Named keys -> uiautomation SpecialKeyNames.
NAMED_KEYS = {
    "enter": "Enter", "tab": "Tab", "escape": "Esc", "esc": "Esc", "backspace": "Back",
    "delete": "Delete", "insert": "Insert", "space": "Space", "home": "Home", "end": "End",
    "pageup": "PageUp", "pagedown": "PageDown", "up": "Up", "down": "Down",
    "left": "Left", "right": "Right",
    **{f"f{n}": f"F{n}" for n in range(1, 13)},
}

_UIA_MODIFIERS = {"ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "win": "Win"}
_SYNTAX = "a chord like enter, ctrl+s, ctrl+shift+s, alt+f4 (modifiers: ctrl, shift, alt, win)"


def parse_chord(spec: str | None) -> tuple[tuple[str, ...], str]:
    """`"ctrl+shift+s"` -> `(("ctrl", "shift"), "s")`; raises RpaError on bad syntax."""
    text = (spec or "").strip().lower()
    if text == "+" or text.endswith("++"):  # "+" / "ctrl++": the + key itself
        parts = [*(p.strip() for p in text[:-2].split("+") if text != "+"), "+"]
    else:
        parts = [p.strip() for p in text.split("+")]
    if not parts or not parts[-1]:
        raise RpaError(f"key: empty chord; expected {_SYNTAX}")
    *mods, key = parts
    for mod in mods:
        if mod not in MODIFIERS:
            raise RpaError(f"key: unknown modifier {mod!r} in {spec!r}; expected {_SYNTAX}")
    if len(set(mods)) != len(mods):
        raise RpaError(f"key: repeated modifier in {spec!r}")
    if key not in NAMED_KEYS and len(key) != 1:
        raise RpaError(f"key: unknown key {key!r} in {spec!r}; expected {_SYNTAX}")
    return tuple(mods), key


def escape_uia_text(text: str) -> str:
    """Text for uiautomation SendKeys typed literally: braces are its key-name syntax."""
    return "".join("{" + ch + "}" if ch in "{}" else ch for ch in text)


def to_uia(spec: str) -> str:
    """Chord -> uiautomation SendKeys notation, e.g. `ctrl+shift+s` -> `{Ctrl}{Shift}s`."""
    mods, key = parse_chord(spec)
    keypart = "{" + NAMED_KEYS[key] + "}" if key in NAMED_KEYS else escape_uia_text(key)
    return "".join("{" + _UIA_MODIFIERS[m] + "}" for m in mods) + keypart
