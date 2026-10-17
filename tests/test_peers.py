"""Tests for pyside_gui.peers — text formats and selection rules (no Qt)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import types

import pytest

from pyside_gui.peers import (
    MAX_POST,
    HEAD,
    TAGS,
    task_post,
    report_post,
    pick_eviction,
    limit_error,
    active_notice,
)


def peer(handle="fixer_ab12", state="idle", last_outcome="done", last_active=0.0):
    return types.SimpleNamespace(
        handle=handle, state=state, last_outcome=last_outcome, last_active=last_active
    )


# ---- task_post ----

def test_task_post_short_no_attach():
    text, attach = task_post("fixer_ab12", "do x")
    assert text == "@fixer_ab12 [task] do x"
    assert attach is False


def test_task_post_boundary_exactly_700_not_attached():
    peer_name = "p"
    prefix = f"@{peer_name} [task] "
    task = "a" * (MAX_POST - len(prefix))
    text = f"{prefix}{task}"
    assert len(text) == MAX_POST
    out_text, attach = task_post(peer_name, task)
    assert out_text == text
    assert attach is False


def test_task_post_boundary_701_is_attached():
    peer_name = "p"
    prefix = f"@{peer_name} [task] "
    task = "a" * (MAX_POST - len(prefix) + 1)
    out_text, attach = task_post(peer_name, task)
    assert attach is True
    assert len(out_text) <= MAX_POST


def test_task_post_long_task_attaches_and_fits():
    peer_name = "fixer_ab12"
    task = "x" * 5000
    text, attach = task_post(peer_name, task)
    assert attach is True
    assert text.startswith(f"@{peer_name} [task] ")
    assert text.endswith("… (full task in task.md)")
    assert len(text) <= MAX_POST
    assert f"[task] {task[:HEAD]}…" in text


def test_task_post_long_form_fits_for_realistic_handles():
    # Handles are <= 41 chars (slug_uuid8-ish, generously bounded).
    for n in (1, 10, 20, 41):
        peer_name = "h" * n
        task = "x" * 5000
        text, attach = task_post(peer_name, task)
        assert attach is True
        assert len(text) <= MAX_POST


# ---- report_post ----

def test_report_post_done_exact():
    out = report_post("main_1111", "done", "all good")
    assert out == "@main_1111 [done] all good"


def test_report_post_max_continuations_exact():
    out = report_post("main_1111", "max-continuations", "ran out of turns")
    assert out == "@main_1111 [max-continuations] ran out of turns"


def test_report_post_error_exact():
    out = report_post("main_1111", "error", "boom")
    assert out == "@main_1111 [error] boom"


def test_report_post_long_body_cut_and_ends_with_ellipsis():
    out = report_post("main_1111", "done", "y" * 5000)
    assert len(out) <= MAX_POST
    assert out.endswith("…")


def test_report_post_head_is_at_most_500_chars_even_when_post_would_fit():
    assert report_post("main_1111", "done", "y" * 500) == "@main_1111 [done] " + "y" * 500
    out = report_post("main_1111", "done", "y" * 600)  # 618 chars uncut: still cut (D12)
    assert out == "@main_1111 [done] " + "y" * 500 + "…"


def test_report_post_empty_body_becomes_no_text():
    out = report_post("main_1111", "error", "   ")
    assert out == "@main_1111 [error] (no text)"
    out2 = report_post("main_1111", "error", "")
    assert out2 == "@main_1111 [error] (no text)"


def test_report_post_invalid_tag_raises():
    with pytest.raises(ValueError):
        report_post("main_1111", "stopped", "x")


# ---- pick_eviction ----

def test_pick_eviction_lru_among_eligible():
    p1 = peer("a", "idle", "done", last_active=5.0)
    p2 = peer("b", "idle", "done", last_active=1.0)
    p3 = peer("c", "idle", "done", last_active=3.0)
    assert pick_eviction([p1, p2, p3]) is p2


def test_pick_eviction_skips_bad_outcomes():
    p1 = peer("a", "idle", "error", last_active=1.0)
    p2 = peer("b", "idle", "max-continuations", last_active=2.0)
    p3 = peer("c", "idle", None, last_active=3.0)
    assert pick_eviction([p1, p2, p3]) is None


def test_pick_eviction_skips_non_idle_states():
    p1 = peer("a", "running", "done", last_active=1.0)
    p2 = peer("b", "waiting", "done", last_active=2.0)
    p3 = peer("c", "paused", "done", last_active=3.0)
    assert pick_eviction([p1, p2, p3]) is None


def test_pick_eviction_none_when_empty():
    assert pick_eviction([]) is None


# ---- limit_error ----

def test_limit_error_exact_string():
    p1 = peer("fixer_ab12", "running")
    p2 = peer("docs_9f3e", "waiting")
    out = limit_error([p1, p2], 2)
    assert out == (
        "Error: 2 spawned agents are open and none can be closed: "
        "fixer_ab12 (running), docs_9f3e (waiting for you). "
        "Wait for a [done] message, close one in the Agents view, "
        "or post a follow-up to an idle one."
    )


# ---- active_notice ----

def test_active_notice_lists_running_and_waiting_in_order():
    p1 = peer("a", "idle")
    p2 = peer("b", "running")
    p3 = peer("c", "waiting")
    p4 = peer("d", "paused")
    out = active_notice([p1, p2, p3, p4])
    assert out == (
        "⏹ Stopped. Peers still active: b (running), c (waiting for you). "
        "See the Agents view."
    )


def test_active_notice_none_when_all_idle_or_paused_or_error():
    p1 = peer("a", "idle")
    p2 = peer("b", "paused")
    p3 = peer("c", "error")
    assert active_notice([p1, p2, p3]) is None


def test_importing_peers_loads_no_qt():
    probe = "import sys, pyside_gui.peers; print(any(m.startswith('PySide6') for m in sys.modules))"
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                            cwd=Path(__file__).resolve().parents[1], check=True)
    assert result.stdout.strip() == "False"
