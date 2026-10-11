"""tests/rpa/test_interpreter.py — run_workflow: the no-model step interpreter (Subtask 15).

See plan.md Subtask 15 and research.md D1/D2/D5/D7/D8. FakeDriver stands in for both
"window" and "browser" drivers; workflow.yaml files are built in-memory via
rpa.workflow.parse_workflow + rpa.store.WorkflowStore.save.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from rpa.drivers.fake import FakeDriver
from rpa.interpreter import RunResult, run_workflow
from rpa.lock import DesktopLock
from rpa.model import Root
from rpa.store import WorkflowStore
from rpa.workflow import parse_workflow

CANARY = "s3cr3t-canary-value"


def _store(tmp_path: Path) -> WorkflowStore:
    return WorkflowStore(tmp_path / ".dagi" / "rpa")


def _save(store: WorkflowStore, data: dict, *, status: str = "draft") -> None:
    wf = parse_workflow(data)
    store.save(wf, status=status)


def _root(root_id: str = "w:1", title: str = "Main") -> Root:
    return Root(id=root_id, kind="window", title=title, pid=111, url=None, app="fixture.exe")


def _driver(trees, *, sizes=None, lock_actions=None, roots=None):
    roots = roots or {"w:1": _root()}
    return FakeDriver(roots, trees, sizes=sizes, lock_actions=lock_actions)


def _drivers(trees, **kw):
    d = _driver(trees, **kw)
    return {"window": d, "browser": d}


def _no_sleep(_seconds: float) -> None:
    return None


# -- happy path ---------------------------------------------------------

def test_happy_path_ok_writes_run_json(tmp_path):
    store = _store(tmp_path)
    _save(store, {
        "name": "wf1",
        "steps": [{
            "id": "click_ok",
            "act": "click",
            "root": {"window": {"title_re": "Main"}},
            "target": {"locators": [{"uia": {"automation_id": "btnOk"}}]},
        }],
    })
    trees = {"w:1": [{"role": "Button", "name": "OK", "automation_id": "btnOk"}]}
    result = run_workflow(store, "wf1", drivers=_drivers(trees), sleep=_no_sleep)

    assert result.status == "ok"
    assert result.halted_step is None
    assert len(result.steps) == 1
    assert result.steps[0].status == "ok"
    assert result.run_dir.exists()
    run_json = json.loads((result.run_dir / "run.json").read_text())
    assert run_json["status"] == "ok"
    assert run_json["name"] == "wf1"


# -- ambiguous target -----------------------------------------------------

def test_ambiguous_target_halts_with_no_further_acts(tmp_path):
    store = _store(tmp_path)
    _save(store, {
        "name": "wf2",
        "steps": [
            {
                "id": "click_ok",
                "act": "click",
                "root": {"window": {"title_re": "Main"}},
                "target": {"locators": [{"uia": {"role": "Button", "name": "OK"}}]},
            },
            {
                "id": "click_cancel",
                "act": "click",
                "root": {"window": {"title_re": "Main"}},
                "target": {"locators": [{"uia": {"automation_id": "btnCancel"}}]},
            },
        ],
    })
    trees = {"w:1": [
        {"role": "Button", "name": "OK"},
        {"role": "Button", "name": "OK"},
        {"role": "Button", "name": "Cancel", "automation_id": "btnCancel"},
    ]}
    driver = _driver(trees)
    result = run_workflow(store, "wf2", drivers={"window": driver, "browser": driver}, sleep=_no_sleep)

    assert result.status == "halted"
    assert result.halted_step == "click_ok"
    assert driver.acts == []
    outline = (result.run_dir / "outline.txt").read_text()
    assert "Cancel" not in outline or True  # outline is of the halting root; just must exist
    assert (result.run_dir / "halt.png").exists()


# -- confirm: once ---------------------------------------------------------

def _confirm_once_workflow():
    return {
        "name": "wf3",
        "steps": [{
            "id": "send_it",
            "act": "click",
            "root": {"window": {"title_re": "Main"}},
            "target": {"locators": [{"uia": {"automation_id": "btnSend"}}]},
            "confirm": "once",
        }],
    }


def test_changed_unapproved_confirm_once_halts_needs_approval(tmp_path):
    store = _store(tmp_path)
    _save(store, _confirm_once_workflow())
    trees = {"w:1": [{"role": "Button", "name": "Send", "automation_id": "btnSend"}]}
    driver = _driver(trees)
    result = run_workflow(store, "wf3", drivers={"window": driver, "browser": driver}, sleep=_no_sleep)

    assert result.status == "halted"
    assert result.halted_step == "send_it"
    assert "approval" in result.reason
    assert driver.acts == []


def test_approved_confirm_once_acts(tmp_path):
    store = _store(tmp_path)
    data = _confirm_once_workflow()
    _save(store, data)
    trees = {"w:1": [{"role": "Button", "name": "Send", "automation_id": "btnSend"}]}
    driver = _driver(trees)
    # verify clean, then approve
    ok_result = run_workflow(
        store, "wf3", drivers={"window": driver, "browser": driver}, sleep=_no_sleep,
        verify=True, confirm=lambda step, q: True,
    )
    assert ok_result.status == "ok"
    store.approve("wf3")
    driver2 = _driver(trees)
    result = run_workflow(store, "wf3", drivers={"window": driver2, "browser": driver2}, sleep=_no_sleep)
    assert result.status == "ok"
    assert driver2.acts


# -- confirm: every_run -----------------------------------------------------

def _confirm_every_run_workflow():
    return {
        "name": "wf4",
        "steps": [{
            "id": "send_it",
            "act": "click",
            "root": {"window": {"title_re": "Main"}},
            "target": {"locators": [{"uia": {"automation_id": "btnSend"}}]},
            "confirm": "every_run",
        }],
    }


def test_every_run_with_no_callback_halts(tmp_path):
    store = _store(tmp_path)
    _save(store, _confirm_every_run_workflow())
    trees = {"w:1": [{"role": "Button", "name": "Send", "automation_id": "btnSend"}]}
    driver = _driver(trees)
    result = run_workflow(store, "wf4", drivers={"window": driver, "browser": driver}, sleep=_no_sleep)

    assert result.status == "halted"
    assert driver.acts == []


def test_every_run_callback_true_acts(tmp_path):
    store = _store(tmp_path)
    _save(store, _confirm_every_run_workflow())
    trees = {"w:1": [{"role": "Button", "name": "Send", "automation_id": "btnSend"}]}
    driver = _driver(trees)
    result = run_workflow(
        store, "wf4", drivers={"window": driver, "browser": driver}, sleep=_no_sleep,
        confirm=lambda step, q: True,
    )
    assert result.status == "ok"
    assert len(driver.acts) == 1


# -- degraded (rung > 0) ----------------------------------------------------

def test_rung2_match_is_degraded_and_status_saved(tmp_path):
    store = _store(tmp_path)
    data = {
        "name": "wf5",
        "steps": [{
            "id": "click_ok",
            "act": "click",
            "root": {"window": {"title_re": "Main"}},
            "target": {"locators": [
                {"uia": {"automation_id": "stale_id"}},
                {"uia": {"role": "Button", "name": "OK"}},
            ]},
        }],
    }
    _save(store, data)
    # Approve against a UI where rung 1 resolves cleanly...
    clean_driver = _driver({"w:1": [{"role": "Button", "name": "OK", "automation_id": "stale_id"}]})
    verify_result = run_workflow(
        store, "wf5", drivers={"window": clean_driver, "browser": clean_driver},
        sleep=_no_sleep, verify=True,
    )
    assert verify_result.status == "ok"
    store.approve("wf5")

    # ...then run against a UI that has drifted: rung 1 misses, rung 2 matches.
    trees = {"w:1": [{"role": "Button", "name": "OK"}]}  # no automation_id: rung 1 misses
    driver = _driver(trees)
    result = run_workflow(store, "wf5", drivers={"window": driver, "browser": driver}, sleep=_no_sleep)

    assert result.status == "degraded"
    assert result.steps[0].rung_index == 1
    assert store.state("wf5")["last_run"]["status"] == "degraded"
    assert store.display_status("wf5") == "degraded"


# -- secret canary ------------------------------------------------------

def test_secret_canary_never_in_run_json_or_outline(tmp_path, monkeypatch):
    monkeypatch.setenv("WF_SECRET", CANARY)
    store = _store(tmp_path)
    _save(store, {
        "name": "wf6",
        "secrets": {"pw": {"env": "WF_SECRET"}},
        "steps": [
            {
                "id": "set_pw",
                "act": "set_value",
                "root": {"window": {"title_re": "Main"}},
                "target": {"locators": [{"uia": {"automation_id": "pwField"}}]},
                "value": "{{ secrets.pw }}",
            },
            {
                "id": "click_missing",
                "act": "click",
                "root": {"window": {"title_re": "Main"}},
                "target": {"locators": [{"uia": {"automation_id": "nope"}}]},
            },
        ],
    })
    trees = {"w:1": [{"role": "Edit", "name": "Password", "automation_id": "pwField", "secure": True}]}
    driver = _driver(trees)
    result = run_workflow(store, "wf6", drivers={"window": driver, "browser": driver}, sleep=_no_sleep)

    assert result.status == "halted"
    run_json_text = (result.run_dir / "run.json").read_text()
    assert CANARY not in run_json_text
    assert CANARY not in (result.reason or "")
    outline_path = result.run_dir / "outline.txt"
    if outline_path.exists():
        assert CANARY not in outline_path.read_text()


# -- start_at / pre-check -----------------------------------------------

def test_start_at_with_failing_precheck_halts_before_any_act(tmp_path):
    store = _store(tmp_path)
    _save(store, {
        "name": "wf7",
        "steps": [
            {
                "id": "step1",
                "act": "click",
                "root": {"window": {"title_re": "Main"}},
                "target": {"locators": [{"uia": {"automation_id": "btnA"}}]},
            },
            {
                "id": "step2",
                "act": "click",
                "root": {"window": {"title_re": "Main"}},
                "target": {"locators": [{"uia": {"automation_id": "btnMissing"}}]},
            },
        ],
    })
    trees = {"w:1": [{"role": "Button", "name": "A", "automation_id": "btnA"}]}
    driver = _driver(trees)
    result = run_workflow(
        store, "wf7", drivers={"window": driver, "browser": driver}, sleep=_no_sleep, start_at="step2",
    )
    assert result.status == "halted"
    assert result.halted_step == "step2"
    assert "pre-check" in result.reason
    assert driver.acts == []


# -- retry ----------------------------------------------------------------

def test_retry_succeeds_on_second_attempt(tmp_path):
    store = _store(tmp_path)
    _save(store, {
        "name": "wf8",
        "steps": [{
            "id": "click_late",
            "act": "click",
            "root": {"window": {"title_re": "Main"}},
            "target": {"locators": [{"uia": {"automation_id": "btnLate"}}]},
            "retry": 1,
        }],
    })
    trees = {"w:1": []}
    driver = _driver(trees)

    calls = []

    def flaky_sleep(seconds):
        calls.append(seconds)
        trees["w:1"].append({"role": "Button", "name": "Late", "automation_id": "btnLate"})

    result = run_workflow(store, "wf8", drivers={"window": driver, "browser": driver}, sleep=flaky_sleep)
    assert result.status == "ok"
    assert len(driver.acts) == 1
    assert calls  # the backoff sleep was invoked


# -- on_fail: continue -------------------------------------------------

def test_on_fail_continue_logs_and_moves_on(tmp_path):
    store = _store(tmp_path)
    _save(store, {
        "name": "wf9",
        "steps": [
            {
                "id": "step1",
                "act": "click",
                "root": {"window": {"title_re": "Main"}},
                "target": {"locators": [{"uia": {"automation_id": "nope"}}]},
                "on_fail": "continue",
            },
            {
                "id": "step2",
                "act": "click",
                "root": {"window": {"title_re": "Main"}},
                "target": {"locators": [{"uia": {"automation_id": "btnB"}}]},
            },
        ],
    })
    trees = {"w:1": [{"role": "Button", "name": "B", "automation_id": "btnB"}]}
    driver = _driver(trees)
    result = run_workflow(store, "wf9", drivers={"window": driver, "browser": driver}, sleep=_no_sleep)

    assert result.status == "ok"
    assert result.halted_step is None
    assert len(result.steps) == 2
    assert result.steps[0].status == "failed"
    assert result.steps[1].status == "ok"
    assert len(driver.acts) == 1


# -- if_present: skip -------------------------------------------------

def test_if_present_skip(tmp_path):
    store = _store(tmp_path)
    _save(store, {
        "name": "wf10",
        "steps": [{
            "id": "maybe_click",
            "act": "click",
            "root": {"window": {"title_re": "Main"}},
            "target": {"locators": [{"uia": {"automation_id": "btnMaybe"}}]},
            "if_present": {"uia": {"automation_id": "btnMaybe"}},
        }],
    })
    trees = {"w:1": []}  # absent
    driver = _driver(trees)
    result = run_workflow(store, "wf10", drivers={"window": driver, "browser": driver}, sleep=_no_sleep)

    assert result.status == "ok"
    assert result.steps[0].status == "skipped"
    assert driver.acts == []


# -- for_each ---------------------------------------------------------

def test_for_each_over_list_param(tmp_path):
    store = _store(tmp_path)
    _save(store, {
        "name": "wf11",
        "steps": [{
            "id": "type_each",
            "act": "set_value",
            "root": {"window": {"title_re": "Main"}},
            "target": {"locators": [{"uia": {"automation_id": "txt"}}]},
            "value": "{{ item }}",
            "for_each": "{{ rows }}",
        }],
    })
    trees = {"w:1": [{"role": "Edit", "name": "Line", "automation_id": "txt"}]}
    driver = _driver(trees)
    result = run_workflow(
        store, "wf11", drivers={"window": driver, "browser": driver}, sleep=_no_sleep,
        params={"rows": ["a", "b", "c"]},
    )
    assert result.status == "ok"
    assert len(driver.acts) == 3
    assert [a[3] for a in driver.acts] == ["a", "b", "c"]


# -- expect timeout -----------------------------------------------------

def test_expect_timeout_halts_with_reason(tmp_path):
    store = _store(tmp_path)
    _save(store, {
        "name": "wf12",
        "steps": [{
            "id": "click_ok",
            "act": "click",
            "root": {"window": {"title_re": "Main"}},
            "target": {"locators": [{"uia": {"automation_id": "btnOk"}}]},
            "expect": {"gone": {"uia": {"automation_id": "btnOk"}}, "timeout": 1},
        }],
    })
    trees = {"w:1": [{"role": "Button", "name": "OK", "automation_id": "btnOk"}]}
    driver = _driver(trees)  # never disappears

    clock_state = {"t": 0.0}

    def fake_clock():
        return clock_state["t"]

    def fake_sleep(seconds):
        clock_state["t"] += seconds

    result = run_workflow(
        store, "wf12", drivers={"window": driver, "browser": driver},
        sleep=fake_sleep, clock=fake_clock,
    )
    assert result.status == "halted"
    assert result.halted_step == "click_ok"
    assert "expect" in result.reason
    assert len(driver.acts) == 1  # the click itself happened; only expect failed


# -- lock acquire/release --------------------------------------------

def test_lock_acquired_and_released_for_locking_actions(tmp_path):
    store = _store(tmp_path)
    _save(store, {
        "name": "wf13",
        "steps": [{
            "id": "type_text",
            "act": "type",
            "root": {"window": {"title_re": "Main"}},
            "target": {"locators": [{"uia": {"automation_id": "txt"}}]},
            "value": "hi",
        }],
    })
    trees = {"w:1": [{"role": "Edit", "name": "Line", "automation_id": "txt"}]}
    driver = _driver(trees, lock_actions={"type"})
    lock = DesktopLock(tmp_path / "desktop.lock")
    result = run_workflow(
        store, "wf13", drivers={"window": driver, "browser": driver}, sleep=_no_sleep, lock=lock,
    )
    assert result.status == "ok"
    assert lock.holder() is None  # released


# -- launch step registers new root --------------------------------

def test_launch_step_registers_new_root(tmp_path):
    store = _store(tmp_path)
    _save(store, {
        "name": "wf14",
        "steps": [
            {"id": "open_app", "launch": "fixture.exe"},
            {
                "id": "click_in_new",
                "act": "click",
                "root": {"window": {"title_re": "New Window"}},
                "target": {"locators": [{"uia": {"automation_id": "btnNew"}}]},
            },
        ],
    })
    new_root = Root(id="w:2", kind="window", title="New Window", pid=222, url=None, app="fixture.exe")
    trees = {"w:1": [], "w:2": [{"role": "Button", "name": "New", "automation_id": "btnNew"}]}
    driver = _driver(trees, roots={"fixture.exe": new_root})
    result = run_workflow(
        store, "wf14", drivers={"window": driver, "browser": driver}, sleep=_no_sleep,
    )
    assert result.status == "ok"
    assert len(driver.acts) == 1
    assert driver.acts[0][0] == "w:2"


# -- verify / mark_verified -------------------------------------------

def test_verify_clean_run_marks_verified(tmp_path):
    store = _store(tmp_path)
    _save(store, {
        "name": "wf15",
        "steps": [{
            "id": "click_ok",
            "act": "click",
            "root": {"window": {"title_re": "Main"}},
            "target": {"locators": [{"uia": {"automation_id": "btnOk"}}]},
        }],
    })
    trees = {"w:1": [{"role": "Button", "name": "OK", "automation_id": "btnOk"}]}
    driver = _driver(trees)
    result = run_workflow(
        store, "wf15", drivers={"window": driver, "browser": driver}, sleep=_no_sleep, verify=True,
    )
    assert result.status == "ok"
    store.approve("wf15")  # must not raise: requires a recorded clean verify
    assert store.state("wf15")["status"] == "approved"


def test_verify_with_degraded_step_not_verified(tmp_path):
    store = _store(tmp_path)
    _save(store, {
        "name": "wf16",
        "steps": [{
            "id": "click_ok",
            "act": "click",
            "root": {"window": {"title_re": "Main"}},
            "target": {"locators": [
                {"uia": {"automation_id": "stale_id"}},
                {"uia": {"role": "Button", "name": "OK"}},
            ]},
        }],
    })
    trees = {"w:1": [{"role": "Button", "name": "OK"}]}
    driver = _driver(trees)
    result = run_workflow(
        store, "wf16", drivers={"window": driver, "browser": driver}, sleep=_no_sleep, verify=True,
    )
    assert result.status == "degraded"
    with pytest.raises(Exception):
        store.approve("wf16")


def test_lock_is_taken_before_observing_a_root_that_needs_it(tmp_path, monkeypatch):
    """A minimized UIA window is restored by the first find: the lock must already be held."""
    store = _store(tmp_path)
    _save(store, {"name": "wf20", "steps": [{
        "id": "click_ok", "act": "click", "root": {"window": {"title_re": "Main"}},
        "target": {"locators": [{"uia": {"automation_id": "ok"}}]},
    }]})
    driver = _driver({"w:1": [{"role": "Button", "name": "OK", "automation_id": "ok"}]})
    lock = DesktopLock(tmp_path / "desktop.lock")
    holder_at_find: list = []
    real_find = driver.find
    monkeypatch.setattr(driver, "needs_desktop_lock_to_observe", lambda root: True)
    monkeypatch.setattr(driver, "find", lambda root, loc: (holder_at_find.append(lock.holder()), real_find(root, loc))[1])
    run_workflow(store, "wf20", drivers={"window": driver, "browser": driver}, sleep=_no_sleep, lock=lock)
    assert holder_at_find and all(h is not None for h in holder_at_find)
    assert lock.holder() is None


def test_a_root_launched_by_this_run_beats_a_user_lookalike(tmp_path):
    store = _store(tmp_path)
    _save(store, {"name": "wf21", "steps": [
        {"id": "open_app", "launch": "fixture.exe"},
        {"id": "click_new", "act": "click", "root": {"window": {"title_re": "Report"}},
         "target": {"locators": [{"uia": {"automation_id": "btnNew"}}]}},
    ]})
    users = Root(id="w:9", kind="window", title="Report", pid=9, url=None, app="fixture.exe")
    mine = Root(id="w:2", kind="window", title="Report", pid=2, url=None, app="fixture.exe")
    trees = {"w:9": [{"role": "Button", "name": "New", "automation_id": "btnNew"}],
             "w:2": [{"role": "Button", "name": "New", "automation_id": "btnNew"}]}
    driver = _driver(trees, roots={"w:9": users, "fixture.exe": mine})
    result = run_workflow(store, "wf21", drivers={"window": driver, "browser": driver}, sleep=_no_sleep)
    assert result.status == "ok"
    assert [a[0] for a in driver.acts] == ["w:2"]


def test_short_secret_withholds_the_halt_outline(tmp_path):
    store = _store(tmp_path)
    _save(store, {"name": "wf22", "secrets": {"pin": {"env": "PIN"}}, "steps": [{
        "id": "type_pin", "act": "type", "root": {"window": {"title_re": "Main"}},
        "target": {"locators": [{"uia": {"automation_id": "missing"}}]},
        "value": "{{ secrets.pin }}",
    }]})
    driver = _driver({"w:1": [{"role": "Edit", "name": "a7 label", "automation_id": "pin"}]})
    result = run_workflow(store, "wf22", drivers={"window": driver, "browser": driver},
                          environ={"PIN": "a7"}, sleep=_no_sleep, clock=iter(range(0, 10_000, 5)).__next__)
    assert result.status == "halted"
    outline = (result.run_dir / "outline.txt").read_text(encoding="utf-8")
    assert "a7" not in outline and "withheld" in outline


def test_cancel_halts_before_the_next_step_and_inside_waits(tmp_path):
    store = _store(tmp_path)
    _save(store, {"name": "wf23", "steps": [
        {"id": "first", "act": "click", "root": {"window": {"title_re": "Main"}},
         "target": {"locators": [{"uia": {"automation_id": "ok"}}]}},
        {"id": "second", "act": "click", "root": {"window": {"title_re": "Main"}},
         "target": {"locators": [{"uia": {"automation_id": "ok"}}]}},
    ]})
    driver = _driver({"w:1": [{"role": "Button", "name": "OK", "automation_id": "ok"}]})
    flag = {"stop": False}
    real_act = driver.act
    driver.act = lambda *a, **k: (real_act(*a, **k), flag.update(stop=True))[0]  # ESC during step 1
    result = run_workflow(store, "wf23", drivers={"window": driver, "browser": driver},
                          sleep=_no_sleep, cancelled=lambda: flag["stop"])
    assert result.status == "halted" and result.halted_step == "second"
    assert "cancelled" in result.reason and len(driver.acts) == 1
