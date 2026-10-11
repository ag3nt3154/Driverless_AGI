"""tests/test_rpa_tools.py — rpa_record / rpa_save through UiSession + FakeDriver,
end to end with the real ui_act tool (Subtask 13 / 14)."""
from __future__ import annotations

import copy

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
