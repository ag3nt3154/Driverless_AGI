"""tests/test_rpa_tools.py — rpa_record / rpa_save through UiSession + FakeDriver,
end to end with the real ui_act tool (Subtask 13 / 14)."""
from __future__ import annotations

import copy

import pytest

from rpa.drivers.fake import FakeDriver
from rpa.model import Root
from rpa.store import WorkflowStore
from rpa.workflow import parse_workflow
from tools.rpa import RpaApproveTool, RpaRecordTool, RpaRunTool, RpaSaveTool
from tools.ui import UiActTool, UiObserveTool, UiRootsTool, UiSession

_ROOT = Root(id="r1", kind="window", title="MyApp", pid=1, url=None, app="app.exe")

_TREE = [
    {"role": "Button", "name": "OK", "automation_id": "btnOK", "bbox": (0, 0, 50, 20)},
    {"role": "Button", "name": "Send", "automation_id": "btnSend", "bbox": (0, 30, 50, 50)},
    {"role": "Edit", "name": "Password", "automation_id": "pwd", "secure": True, "bbox": (0, 60, 50, 80)},
    {"role": "Edit", "name": "Note", "automation_id": "note", "bbox": (0, 90, 50, 110)},
    {"role": "Button", "name": "Cancel", "automation_id": "btnCancel", "bbox": (0, 120, 50, 140)},
]


class _Cfg:
    def __init__(self, project_path, autonomous: bool = False) -> None:
        self.autonomous = autonomous
        self.display_name = "dagi"
        self.model = "test-model"
        self.project_path = project_path


class _AskSpy:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def on_ask_user(self, question: str, options: list[dict], timeout) -> str:
        self.calls.append((question, options, timeout))
        return "Allow" if "Allow dagi" in question else "Allow once"


def _make_session(tmp_path):
    driver = FakeDriver({"r1": _ROOT}, {"r1": copy.deepcopy(_TREE)})
    session = UiSession(_Cfg(tmp_path), _AskSpy(), uia_driver=driver)
    return session, driver


def _observe(session, root_id, **kwargs) -> str:
    result = UiObserveTool(session).run(root=root_id, **kwargs)
    output = result.output if hasattr(result, "output") else result
    return output.splitlines()[0]


def test_rpa_record_refuses_when_already_recording(tmp_path):
    session, _driver = _make_session(tmp_path)
    out1 = RpaRecordTool(session).run(name="demo", goal="export")
    assert out1.startswith("recording")
    out2 = RpaRecordTool(session).run(name="other", goal="x")
    assert out2.startswith("Error")


def test_rpa_save_without_recording_is_an_error(tmp_path):
    session, _driver = _make_session(tmp_path)
    out = RpaSaveTool(session).run()
    assert out.startswith("Error")


def test_full_record_act_save_round_trip_writes_workflow_yaml(tmp_path):
    session, driver = _make_session(tmp_path)
    UiRootsTool(session).run(launch="r1")

    RpaRecordTool(session).run(name="demo", goal="click ok then send")
    obs = _observe(session, "w:r1")
    UiActTool(session).run(root="w:r1", target=0, action="click", obs=obs)
    obs2 = _observe(session, "w:r1")
    UiActTool(session).run(root="w:r1", target=1, action="click", obs=obs2)

    result = RpaSaveTool(session).run()
    assert result.startswith("saved draft workflow 'demo'")

    store = WorkflowStore(tmp_path / ".dagi" / "rpa")
    workflow = store.load("demo")
    assert [s.act for s in workflow.steps] == ["click", "click"]
    assert session.recorder is None


def test_failed_or_refused_act_adds_nothing_to_the_trace(tmp_path):
    session, driver = _make_session(tmp_path)
    UiRootsTool(session).run(launch="r1")
    RpaRecordTool(session).run(name="demo", goal="g")
    obs = _observe(session, "w:r1")

    # A bad target index: ui_act returns an error and must not call record_act.
    result = UiActTool(session).run(root="w:r1", target=999, action="click", obs=obs)
    assert result.startswith("Error")

    RpaSaveTool(session).run()
    workflow = WorkflowStore(tmp_path / ".dagi" / "rpa").load("demo")
    assert workflow.steps == []


def test_secure_value_stored_as_secret_ref_canary_never_in_files(tmp_path, monkeypatch):
    monkeypatch.setenv("DAGI_TEST_PW", "s3cr3t-canary")
    session, driver = _make_session(tmp_path)
    UiRootsTool(session).run(launch="r1")
    RpaRecordTool(session).run(name="demo", goal="g")
    obs = _observe(session, "w:r1")

    UiActTool(session).run(
        root="w:r1", target=2, action="set_value", obs=obs, value="${env:DAGI_TEST_PW}",
    )

    store = WorkflowStore(tmp_path / ".dagi" / "rpa")
    trace_text = (store.dir("demo") / "trace.jsonl").read_text(encoding="utf-8")
    assert "s3cr3t" not in trace_text

    RpaSaveTool(session).run()
    workflow = store.load("demo")
    assert workflow.steps[0].value == "{{ secrets.dagi_test_pw }}"
    yaml_text = (store.dir("demo") / "workflow.yaml").read_text(encoding="utf-8")
    assert "s3cr3t" not in yaml_text


def test_send_button_compiles_with_confirm_once(tmp_path):
    session, driver = _make_session(tmp_path)
    UiRootsTool(session).run(launch="r1")
    RpaRecordTool(session).run(name="demo", goal="g")
    obs = _observe(session, "w:r1")

    UiActTool(session).run(root="w:r1", target=1, action="click", obs=obs)

    RpaSaveTool(session).run()
    workflow = WorkflowStore(tmp_path / ".dagi" / "rpa").load("demo")
    assert workflow.steps[0].confirm == "once"


def test_duplicate_recording_name_refused_unless_removed(tmp_path):
    session, driver = _make_session(tmp_path)
    UiRootsTool(session).run(launch="r1")
    RpaRecordTool(session).run(name="demo", goal="g")
    obs = _observe(session, "w:r1")
    UiActTool(session).run(root="w:r1", target=0, action="click", obs=obs)
    RpaSaveTool(session).run()

    out = RpaRecordTool(session).run(name="demo", goal="again")
    assert out.startswith("Error")

    store = WorkflowStore(tmp_path / ".dagi" / "rpa")
    (store.dir("demo") / "workflow.yaml").unlink()
    (store.dir("demo") / "trace.jsonl").unlink()
    out2 = RpaRecordTool(session).run(name="demo", goal="again")
    assert out2.startswith("recording")


def test_rpa_save_error_keeps_recording_active(tmp_path):
    session, driver = _make_session(tmp_path)
    UiRootsTool(session).run(launch="r1")
    RpaRecordTool(session).run(name="demo", goal="g")
    obs = _observe(session, "w:r1")
    UiActTool(session).run(root="w:r1", target=0, action="click", obs=obs)

    bad_cleanup = [{"op": "delete", "step": "does-not-exist"}]
    result = RpaSaveTool(session).run(cleanup=bad_cleanup)
    assert result.startswith("Error")
    assert session.recorder is not None

    ok_result = RpaSaveTool(session).run(cleanup=[])
    assert ok_result.startswith("saved draft workflow")
    assert session.recorder is None


def test_same_trace_saved_twice_is_byte_identical_yaml(tmp_path):
    session, driver = _make_session(tmp_path)
    UiRootsTool(session).run(launch="r1")
    RpaRecordTool(session).run(name="demo", goal="g")
    obs = _observe(session, "w:r1")
    UiActTool(session).run(root="w:r1", target=0, action="click", obs=obs)
    RpaSaveTool(session).run()
    store = WorkflowStore(tmp_path / ".dagi" / "rpa")
    first_yaml = (store.dir("demo") / "workflow.yaml").read_text(encoding="utf-8")

    (store.dir("demo") / "workflow.yaml").unlink()
    (store.dir("demo") / "trace.jsonl").unlink()
    session2, driver2 = _make_session(tmp_path)
    UiRootsTool(session2).run(launch="r1")
    RpaRecordTool(session2).run(name="demo", goal="g")
    obs2 = _observe(session2, "w:r1")
    UiActTool(session2).run(root="w:r1", target=0, action="click", obs=obs2)
    RpaSaveTool(session2).run()
    second_yaml = (store.dir("demo") / "workflow.yaml").read_text(encoding="utf-8")

    assert first_yaml == second_yaml


def _trace_acts(tmp_path):
    import json
    store = WorkflowStore(tmp_path / ".dagi" / "rpa")
    lines = (store.dir("demo") / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if json.loads(line)["kind"] == "act"]


def test_an_act_that_closes_its_own_root_is_still_recorded(tmp_path, monkeypatch):
    from rpa import RpaError
    session, driver = _make_session(tmp_path)
    UiRootsTool(session).run(launch="r1")
    RpaRecordTool(session).run(name="demo", goal="close it")
    obs = _observe(session, "w:r1")
    real_act = driver.act

    def act_then_vanish(root, el, action, value=None):
        real_act(root, el, action, value)
        monkeypatch.setattr(driver, "outline", lambda *a, **k: (_ for _ in ()).throw(RpaError("gone")))

    monkeypatch.setattr(driver, "act", act_then_vanish)
    out = UiActTool(session).run(root="w:r1", target=4, action="close_window", obs=obs)
    assert out.startswith("ok: close_window")
    acts = _trace_acts(tmp_path)
    assert [a["action"] for a in acts] == ["close_window"] and acts[0]["expect_candidates"] == []


def test_locators_come_from_the_ui_before_the_act(tmp_path, monkeypatch):
    """The click makes a second "OK" appear; the recorded role+name locator must still
    be the one that was unique when the button was clicked."""
    session, driver = _make_session(tmp_path)
    UiRootsTool(session).run(launch="r1")
    RpaRecordTool(session).run(name="demo", goal="click ok")
    obs = _observe(session, "w:r1")
    real_act = driver.act

    def act_then_add_twin(root, el, action, value=None):
        real_act(root, el, action, value)
        driver._trees["r1"].insert(0, {"role": "Button", "name": "OK", "bbox": (0, 200, 50, 220)})

    monkeypatch.setattr(driver, "act", act_then_add_twin)
    UiActTool(session).run(root="w:r1", target=0, action="click", obs=obs)
    [act] = _trace_acts(tmp_path)
    assert {"uia": {"automation_id": "btnOK"}} in act["locators"]
    assert {"uia": {"role": "Button", "name": "OK"}} in act["locators"]


# -- rpa_run / rpa_approve (Subtask 16) --------------------------------------


def _save_workflow(tmp_path, data, *, status: str = "draft") -> WorkflowStore:
    store = WorkflowStore(tmp_path / ".dagi" / "rpa")
    store.save(parse_workflow(data), status=status)
    return store


def _ok_wf(name: str = "demo") -> dict:
    return {
        "name": name,
        "steps": [{
            "id": "click_ok",
            "act": "click",
            "root": {"window": {"title_re": "MyApp"}},
            "target": {"locators": [{"uia": {"automation_id": "btnOK"}}]},
        }],
    }


def test_rpa_run_happy_path(tmp_path):
    session, driver = _make_session(tmp_path)
    _save_workflow(tmp_path, _ok_wf())
    out = RpaRunTool(session).run(name="demo")
    assert "status: ok" in out
    assert [a[2] for a in driver.acts] == ["click"]


def test_rpa_run_halt_offers_repair_and_starts_nothing(tmp_path):
    session, driver = _make_session(tmp_path)
    _save_workflow(tmp_path, {
        "name": "demo",
        "steps": [{
            "id": "click_missing",
            "act": "click",
            "root": {"window": {"title_re": "MyApp"}},
            "target": {"locators": [{"uia": {"automation_id": "nope"}}]},
        }],
    })
    out = RpaRunTool(session).run(name="demo")
    assert "`click_missing` halted" in out
    assert "rpa_repair" in out
    assert "do not start it unasked" in out
    assert driver.acts == []


def test_rpa_approve_autonomous_records_nothing_and_does_not_ask(tmp_path):
    session, driver = _make_session(tmp_path)
    session.config.autonomous = True
    store = _save_workflow(tmp_path, _ok_wf())
    store.mark_verified("demo")
    ask_spy = session.callbacks

    out = RpaApproveTool(session).run(name="demo")

    assert out.startswith("Error")
    assert ask_spy.calls == []
    assert store.state("demo")["status"] != "approved"


def test_rpa_approve_reject_records_nothing(tmp_path):
    session, driver = _make_session(tmp_path)
    session.callbacks.on_ask_user = lambda q, o, t: "Reject"
    store = _save_workflow(tmp_path, _ok_wf())
    store.mark_verified("demo")

    out = RpaApproveTool(session).run(name="demo")

    assert "not approved" in out
    assert store.state("demo")["status"] != "approved"


def test_rpa_verify_then_approve_flow(tmp_path):
    session, driver = _make_session(tmp_path)
    store = _save_workflow(tmp_path, _ok_wf())

    verify_out = RpaRunTool(session).run(name="demo", verify=True)
    assert "Verified" in verify_out

    session.callbacks.on_ask_user = lambda q, o, t: "Approve"
    approve_out = RpaApproveTool(session).run(name="demo")

    assert approve_out.startswith("approved")
    assert store.state("demo")["status"] == "approved"


def test_interrupt_cancel_sets_the_session_flag_and_rpa_run_clears_it(tmp_path):
    session, _driver = _make_session(tmp_path)
    UiActTool(session).cancel()
    assert session.cancel_event.is_set()
    from tools.rpa import RpaRunTool
    RpaRunTool(session).run(name="does-not-exist")
    assert not session.cancel_event.is_set()


def test_recorded_acts_on_a_launched_window_compile_with_launched_by(tmp_path):
    session, _driver = _make_session(tmp_path)
    RpaRecordTool(session).run(name="demo", goal="launch and click")
    UiRootsTool(session).run(launch="r1")
    obs = _observe(session, "w:r1")
    UiActTool(session).run(root="w:r1", target=0, action="click", obs=obs)
    out = RpaSaveTool(session).run()
    assert "launched_by: step_01" in out, out


def test_a_recorded_root_close_compiles_to_a_step_without_target(tmp_path):
    session, _driver = _make_session(tmp_path)
    RpaRecordTool(session).run(name="demo", goal="open and close")
    UiRootsTool(session).run(launch="r1")
    UiActTool(session).run(root="w:r1", action="close_window")
    out = RpaSaveTool(session).run()
    assert "act: close_window" in out and "target" not in out.split("act: close_window")[1].split("- id:")[0]


def test_windows_a_replay_opened_are_dagis_afterwards(tmp_path):
    """Close them later: a replay's launched windows must show up in ui_roots."""
    session, driver = _make_session(tmp_path)
    store = WorkflowStore(tmp_path / ".dagi" / "rpa")
    from rpa.workflow import parse_workflow
    store.save(parse_workflow({"name": "opener", "steps": [{"id": "step_01", "launch": "r1"}]}))
    from tools.rpa import RpaRunTool
    out = RpaRunTool(session).run(name="opener")
    assert "opened: w:r1" in out
    assert "w:r1 | window" in UiRootsTool(session).run()


def test_listing_roots_never_starts_firefox():
    class _LazyBrowser:
        started = False
        def roots(self):
            raise AssertionError("listing started Firefox")
    session = UiSession(_Cfg(None), _AskSpy(), uia_driver=FakeDriver({}, {}), browser_driver=_LazyBrowser())
    UiRootsTool(session).run()


def test_an_esc_stop_is_reported_as_deliberate_not_as_a_failure(tmp_path):
    session, driver = _make_session(tmp_path)
    store = WorkflowStore(tmp_path / ".dagi" / "rpa")
    from rpa.workflow import parse_workflow
    store.save(parse_workflow({"name": "stopme", "steps": [{"id": "step_01", "launch": "r1"}]}))
    from tools.rpa import RpaRunTool
    tool = RpaRunTool(session)
    real_launch = driver.launch
    driver.launch = lambda target: (session.cancel_event.set(), real_launch(target))[1]
    driver_steps = {"id": "step_02", "act": "close_window", "root": {"window": {"title_re": "x", "launched_by": "step_01"}}}
    store.save(parse_workflow({"name": "stopme", "steps": [{"id": "step_01", "launch": "r1"}, driver_steps]}))
    out = tool.run(name="stopme")
    assert "status: cancelled" in out and "deliberate stop" in out
    assert "repair" not in out.split("deliberate stop")[0]
    assert "Offer the Admiral a repair" not in out


# -- rpa_repair / rpa_patch (Subtask 17) -------------------------------------


def _patch_wf(name: str = "demo") -> dict:
    return {
        "name": name,
        "steps": [
            {
                "id": "click_ok",
                "act": "click",
                "root": {"window": {"title_re": "MyApp"}},
                "target": {"locators": [{"uia": {"automation_id": "btnOK"}}]},
            },
            {
                "id": "send_it",
                "act": "click",
                "confirm": "once",
                "root": {"window": {"title_re": "MyApp"}},
                "target": {"locators": [{"uia": {"automation_id": "btnSend"}}]},
            },
        ],
    }


def _save_patch_wf(tmp_path) -> WorkflowStore:
    store = WorkflowStore(tmp_path / ".dagi" / "rpa")
    store.save(parse_workflow(_patch_wf()), status="draft")
    return store


def _record_halt(store, name, step_id, reason="no locator matched"):
    import json as _json
    run_dir = store.dir(name) / "runs" / "20261012T000000Z"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        _json.dumps({"name": name, "status": "halted", "halted_step": step_id, "reason": reason}),
        encoding="utf-8",
    )
    store.record_run(name, "halted", reason=reason, run_dir=run_dir, verify=False)


def _ask_router(answers):
    def on_ask_user(question, options, timeout):
        for keyword, answer in answers:
            if keyword in question:
                return answer
        return "Deny"
    return on_ask_user


def test_rpa_repair_errors_for_a_non_halted_workflow(tmp_path):
    session, _driver = _make_session(tmp_path)
    _save_patch_wf(tmp_path)
    from tools.rpa import RpaRepairTool

    out = RpaRepairTool(session).run(name="demo")
    assert out.startswith("Error")


def test_rpa_repair_shows_halted_step_and_instructions(tmp_path):
    session, _driver = _make_session(tmp_path)
    store = _save_patch_wf(tmp_path)
    _record_halt(store, "demo", "click_ok")
    from tools.rpa import RpaRepairTool

    out = RpaRepairTool(session).run(name="demo")
    assert "halted step: click_ok" in out
    assert "no locator matched" in out
    assert "ui_observe" in out
    assert "never approve" in out


def test_rpa_patch_rejects_literal_locator_without_asking(tmp_path):
    session, _driver = _make_session(tmp_path)
    _save_patch_wf(tmp_path)
    ask_spy = session.callbacks  # _AskSpy records every call
    from tools.rpa import RpaPatchTool

    ops = [{
        "op": "replace_step", "step_id": "click_ok",
        "step": {"target": {"locators": [{"uia": {"automation_id": "btnCancel"}}]}},
    }]
    out = RpaPatchTool(session).run(name="demo", ops=ops)

    assert out.startswith("Error")
    assert ask_spy.calls == []


def test_rpa_patch_question_fences_the_diff(tmp_path):
    session, _driver = _make_session(tmp_path)
    store = _save_patch_wf(tmp_path)
    UiRootsTool(session).run(launch="r1")
    obs = _observe(session, "w:r1")
    seen = []

    def deny_after_seeing(question, options, timeout):
        seen.append(question)
        return "Reject"

    session.callbacks.on_ask_user = deny_after_seeing
    from tools.rpa import RpaPatchTool
    ops = [{
        "op": "replace_step", "step_id": "click_ok",
        "step": {"target": {"root": "w:r1", "obs": obs, "index": 4}},
    }]
    out = RpaPatchTool(session).run(name="demo", ops=ops)

    assert out == "not patched"
    assert "```diff\n" in seen[0]
    assert seen[0].rstrip().endswith("```")


def test_rpa_patch_reject_leaves_yaml_byte_identical(tmp_path):
    session, _driver = _make_session(tmp_path)
    store = _save_patch_wf(tmp_path)
    UiRootsTool(session).run(launch="r1")
    obs = _observe(session, "w:r1")
    before_yaml = (store.dir("demo") / "workflow.yaml").read_text(encoding="utf-8")

    session.callbacks.on_ask_user = lambda q, o, t: "Reject"
    from tools.rpa import RpaPatchTool
    ops = [{
        "op": "replace_step", "step_id": "click_ok",
        "step": {"target": {"root": "w:r1", "obs": obs, "index": 4}},
    }]
    out = RpaPatchTool(session).run(name="demo", ops=ops)

    after_yaml = (store.dir("demo") / "workflow.yaml").read_text(encoding="utf-8")
    assert out == "not patched"
    assert before_yaml == after_yaml


def test_rpa_patch_autonomous_refuses_without_asking(tmp_path):
    session, _driver = _make_session(tmp_path)
    session.config.autonomous = True
    store = _save_patch_wf(tmp_path)
    before_yaml = (store.dir("demo") / "workflow.yaml").read_text(encoding="utf-8")
    from tools.rpa import RpaPatchTool

    out = RpaPatchTool(session).run(name="demo", ops=[{"op": "delete_step", "step_id": "send_it"}])

    assert out.startswith("Error")
    after_yaml = (store.dir("demo") / "workflow.yaml").read_text(encoding="utf-8")
    assert before_yaml == after_yaml


def test_rpa_patch_no_frontend_refuses_without_asking(tmp_path):
    driver = FakeDriver({"r1": _ROOT}, {"r1": copy.deepcopy(_TREE)})
    session = UiSession(_Cfg(tmp_path), None, uia_driver=driver)
    store = _save_patch_wf(tmp_path)
    before_yaml = (store.dir("demo") / "workflow.yaml").read_text(encoding="utf-8")
    from tools.rpa import RpaPatchTool

    out = RpaPatchTool(session).run(name="demo", ops=[{"op": "delete_step", "step_id": "send_it"}])

    assert out.startswith("Error")
    after_yaml = (store.dir("demo") / "workflow.yaml").read_text(encoding="utf-8")
    assert before_yaml == after_yaml


def test_rpa_patch_approve_writes_patched_yaml_from_observation_and_reruns(tmp_path):
    session, _driver = _make_session(tmp_path)
    store = _save_patch_wf(tmp_path)
    UiRootsTool(session).run(launch="r1")
    obs = _observe(session, "w:r1")

    session.callbacks.on_ask_user = _ask_router([
        ("Patch workflow", "Approve and re-run"),
        ("Confirm click", "Allow once"),
    ])
    from tools.rpa import RpaPatchTool
    ops = [{
        "op": "replace_step", "step_id": "click_ok",
        "step": {"target": {"root": "w:r1", "obs": obs, "index": 4}},
    }]
    out = RpaPatchTool(session).run(name="demo", ops=ops)

    workflow = store.load("demo")
    assert workflow.steps[0].target["locators"][0] == {"uia": {"automation_id": "btnCancel"}}
    assert out.startswith("patched 'demo':")
    assert "status: ok" in out
    assert "Verified" in out


def test_rpa_patch_changed_confirm_step_needs_second_confirm_cancel_writes_nothing(tmp_path):
    session, _driver = _make_session(tmp_path)
    store = _save_patch_wf(tmp_path)
    UiRootsTool(session).run(launch="r1")
    obs = _observe(session, "w:r1")
    store.mark_verified("demo")
    store.approve("demo")
    assert "send_it" in store.state("demo")["approved_hash_by_step"]

    session.callbacks.on_ask_user = _ask_router([
        ("changes confirm step", "Cancel"),
        ("Patch workflow", "Approve and re-run"),
    ])
    from tools.rpa import RpaPatchTool
    ops = [{
        "op": "replace_step", "step_id": "send_it",
        "step": {"target": {"root": "w:r1", "obs": obs, "index": 4}},
    }]
    before_yaml = (store.dir("demo") / "workflow.yaml").read_text(encoding="utf-8")
    out = RpaPatchTool(session).run(name="demo", ops=ops)

    after_yaml = (store.dir("demo") / "workflow.yaml").read_text(encoding="utf-8")
    assert out == "not patched"
    assert before_yaml == after_yaml
    assert "send_it" in store.state("demo")["approved_hash_by_step"]


def test_rpa_patch_changed_confirm_step_approved_clears_hash_and_reruns(tmp_path):
    session, _driver = _make_session(tmp_path)
    store = _save_patch_wf(tmp_path)
    UiRootsTool(session).run(launch="r1")
    obs = _observe(session, "w:r1")
    store.mark_verified("demo")
    store.approve("demo")

    session.callbacks.on_ask_user = _ask_router([
        ("changes confirm step", "Confirm change"),
        ("Patch workflow", "Approve and re-run"),
        ("Confirm click", "Allow once"),
    ])
    from tools.rpa import RpaPatchTool
    ops = [{
        "op": "replace_step", "step_id": "send_it",
        "step": {"target": {"root": "w:r1", "obs": obs, "index": 4}},
    }]
    out = RpaPatchTool(session).run(name="demo", ops=ops)

    workflow = store.load("demo")
    assert workflow.steps[1].target["locators"][0] == {"uia": {"automation_id": "btnCancel"}}
    assert "send_it" not in store.state("demo")["approved_hash_by_step"]
    assert "status: ok" in out


@pytest.mark.parametrize("fields", [
    {"expect": {"present": {"uia": {"automation_id": "btnDelete"}}}},
    {"expect": {"gone": {"uia": {"automation_id": "btnDelete"}}, "timeout": 5}},
    {"if_present": {"uia": {"automation_id": "btnDelete"}}},
])
def test_rpa_patch_rejects_literal_locators_in_expect_and_if_present(tmp_path, fields):
    session, _driver = _make_session(tmp_path)
    _save_patch_wf(tmp_path)
    from tools.rpa import RpaPatchTool

    ops = [{"op": "replace_step", "step_id": "click_ok", "step": fields}]
    out = RpaPatchTool(session).run(name="demo", ops=ops)

    assert out.startswith("Error"), out
    assert session.callbacks.calls == []


def test_rpa_patch_resolves_expect_and_if_present_from_an_observation(tmp_path):
    session, _driver = _make_session(tmp_path)
    store = _save_patch_wf(tmp_path)
    UiRootsTool(session).run(launch="r1")
    obs = _observe(session, "w:r1")
    seen = []

    def deny_after_seeing(question, options, timeout):
        seen.append(question)
        return "Reject"

    session.callbacks.on_ask_user = deny_after_seeing
    from tools.rpa import RpaPatchTool
    descriptor = {"root": "w:r1", "obs": obs, "index": 4}
    ops = [{"op": "replace_step", "step_id": "click_ok", "step": {
        "expect": {"present": descriptor, "timeout": 5}, "if_present": descriptor,
    }}]
    out = RpaPatchTool(session).run(name="demo", ops=ops)

    assert out == "not patched"
    assert "btnCancel" in seen[0]  # the diff shows the generated locator
    assert "timeout: 5" in seen[0]


def test_rpa_patch_refuses_root_changes(tmp_path):
    session, _driver = _make_session(tmp_path)
    _save_patch_wf(tmp_path)
    from tools.rpa import RpaPatchTool

    ops = [{"op": "replace_step", "step_id": "click_ok",
            "step": {"root": {"window": {"title_re": ".*"}}}}]
    out = RpaPatchTool(session).run(name="demo", ops=ops)

    assert out.startswith("Error") and "root" in out
    assert session.callbacks.calls == []


def test_rpa_patch_with_no_change_does_not_ask(tmp_path):
    session, _driver = _make_session(tmp_path)
    _save_patch_wf(tmp_path)
    from tools.rpa import RpaPatchTool

    ops = [{"op": "replace_step", "step_id": "click_ok", "step": {"act": "click"}}]
    out = RpaPatchTool(session).run(name="demo", ops=ops)

    assert "no change" in out
    assert session.callbacks.calls == []
