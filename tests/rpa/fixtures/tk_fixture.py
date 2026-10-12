"""tests/rpa/fixtures/tk_fixture.py — a poor-accessibility Tk window.

Run standalone: `python -m tests.rpa.fixtures.tk_fixture`. Tkinter widgets
expose little to no UIA Name/AutomationId by default, unlike the Qt fixture;
this stands in for apps the desktop driver can only resolve by role/geometry.
"""
from __future__ import annotations

import sys
import tkinter as tk

WINDOW_TITLE = "RPA Tk Fixture"


def main() -> int:
    root = tk.Tk()
    root.title(WINDOW_TITLE)
    root.geometry("320x160")

    entry = tk.Entry(root)
    entry.pack(pady=8)

    button_one = tk.Button(root, text="One")
    button_one.pack(pady=4)

    button_two = tk.Button(root, text="Two")
    button_two.pack(pady=4)

    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
