"""tests/rpa/test_compiler.py — compile_trace determinism and restricted cleanup (Subtask 14)."""
from __future__ import annotations

import pytest

from rpa import RpaError
from rpa.compiler import apply_cleanup, compile_trace
from rpa.workflow import SecretRef, dump_workflow

_OK_ENTRY = {
    "kind": "act",
    "n": 1,
    "root": {"kind": "window", "app": "app.exe", "title_re": "MyApp"},
    "action": "click",
    "value": None,
    "locators": [{"uia": {"automation_id": "btnOK"}}],
    "expect_candidates": [{"present": {"uia": {"role": "Button", "name": "Saved"}}}],
    "before": {"role": "Button", "name": "OK", "path": []},
}

_SEND_ENTRY = {
    "kind": "act",
    "n": 2,
    "root": {"kind": "window", "app": "app.exe", "title_re": "MyApp"},
    "action": "click",
    "value": None,
    "locators": [{"uia": {"automation_id": "btnSend"}}],
    "expect_candidates": [{"window": "Sent"}],
    "before": {"role": "Button", "name": "Send", "path": []},
}

_SECRET_ENV_ENTRY = {
    "kind": "act",
    "n": 3,
    "root": {"kind": "window", "app": "app.exe", "title_re": "MyApp"},
    "action": "set_value",
    "value": {"secret_env": "PORTAL_PW"},
    "locators": [{"uia": {"automation_id": "pwd"}}],
    "expect_candidates": [],
    "before": {"role": "Edit", "name": "Password", "path": []},
}

_BARE_SECRET_ENTRY = {
    "kind": "act",
    "n": 4,
    "root": {"kind": "window", "app": "app.exe", "title_re": "MyApp"},
    "action": "set_value",
    "value": {"secret": True},
    "locators": [{"uia": {"automation_id": "pwd"}}],
    "expect_candidates": [],
    "before": {"role": "Edit", "name": "Password", "path": []},
}

_FOCUS_ENTRY = {
    "kind": "act",
    "n": 0,
    "root": {"kind": "window", "app": "app.exe", "title_re": "MyApp"},
    "action": "focus",
    "value": None,
    "locators": [{"uia": {"automation_id": "note"}}],
    "expect_candidates": [],
    "before": {"role": "Edit", "name": "Note", "path": []},
}


def test_same_trace_compiles_to_byte_identical_yaml_twice():
    entries = [_OK_ENTRY, _SEND_ENTRY]
    wf1 = compile_trace(entries, "demo", "export the thing")
    wf2 = compile_trace(entries, "demo", "export the thing")
    assert dump_workflow(wf1) == dump_workflow(wf2)


def test_steps_get_sequential_ids():
    wf = compile_trace([_OK_ENTRY, _SEND_ENTRY], "demo", "g")
    assert [s.id for s in wf.steps] == ["step_01", "step_02"]


def test_send_step_gets_confirm_once():
    wf = compile_trace([_SEND_ENTRY], "demo", "g")
    assert wf.steps[0].confirm == "once"


def test_ok_step_gets_no_confirm():
    wf = compile_trace([_OK_ENTRY], "demo", "g")
    assert wf.steps[0].confirm is None


def test_expect_prefers_window_over_present_over_value_equals():
    entry = dict(_OK_ENTRY, expect_candidates=[
        {"present": {"uia": {"role": "Button", "name": "x"}}},
        {"window": "Done"},
        {"value_equals": "y"},
    ])
    wf = compile_trace([entry], "demo", "g")
    assert wf.steps[0].expect == {"window": "Done", "timeout": 10}


def test_expect_none_when_no_candidates():
    wf = compile_trace([dict(_OK_ENTRY, expect_candidates=[])], "demo", "g")
    assert wf.steps[0].expect is None


def test_secret_env_value_becomes_template_and_declares_secret():
    wf = compile_trace([_SECRET_ENV_ENTRY], "demo", "g")
    assert wf.steps[0].value == "{{ secrets.portal_pw }}"
    assert wf.secrets == {"portal_pw": SecretRef(env="PORTAL_PW")}


def test_bare_secret_marker_is_a_compile_error():
    with pytest.raises(RpaError):
        compile_trace([_BARE_SECRET_ENTRY], "demo", "g")


def test_launch_entry_becomes_a_launch_step():
    launch_entry = {"kind": "launch", "target": "notepad.exe", "app": "notepad.exe", "title_re": "Notepad"}
    wf = compile_trace([launch_entry, _OK_ENTRY], "demo", "g")
    assert wf.steps[0].launch == "notepad.exe"
    assert wf.steps[0].act is None
    assert wf.steps[1].id == "step_02"


def test_adjacent_duplicate_focus_acts_collapse():
    wf = compile_trace([_FOCUS_ENTRY, dict(_FOCUS_ENTRY, n=1), _OK_ENTRY], "demo", "g")
    focus_steps = [s for s in wf.steps if s.act == "focus"]
    assert len(focus_steps) == 1


def test_root_window_and_browser_compile_shape():
    wf = compile_trace([_OK_ENTRY], "demo", "g")
    assert wf.steps[0].root == {"window": {"title_re": "MyApp"}}
    browser_entry = dict(_OK_ENTRY, root={"kind": "browser", "app": "example.com", "url_re": "https://example.com/x"})
    wf2 = compile_trace([browser_entry], "demo", "g")
    assert wf2.steps[0].root == {"browser": {"url_re": "https://example.com/x"}}


# --- apply_cleanup -----------------------------------------------------------


def _base_workflow():
    return compile_trace([_OK_ENTRY, _SEND_ENTRY], "demo", "g")


def test_delete_removes_a_step():
    wf = apply_cleanup(_base_workflow(), [{"op": "delete", "step": "step_02"}])
    assert [s.id for s in wf.steps] == ["step_01"]


def test_rename_changes_the_id():
    wf = apply_cleanup(_base_workflow(), [{"op": "rename", "step": "step_01", "to": "click_ok"}])
    assert wf.steps[0].id == "click_ok"


def test_rename_rejects_a_bad_id():
    with pytest.raises(RpaError):
        apply_cleanup(_base_workflow(), [{"op": "rename", "step": "step_01", "to": "Bad Id"}])


def test_param_replaces_value_and_declares_param():
    wf = apply_cleanup(_base_workflow(), [
        {"op": "param", "step": "step_01", "field": "value", "name": "report_date", "default": "2026-01-01"},
    ])
    assert wf.steps[0].value == "{{ report_date }}"
    assert wf.params["report_date"].default == "2026-01-01"


def test_flag_sets_confirm_and_sensitive_and_expect_file():
    wf = apply_cleanup(_base_workflow(), [
        {"op": "flag", "step": "step_01", "confirm": "every_run", "sensitive": True, "expect_file": "out.csv"},
    ])
    step = wf.steps[0]
    assert step.confirm == "every_run"
    assert step.sensitive is True
    assert step.expect == {"file_exists": "out.csv", "timeout": 10}


def test_unknown_op_is_rejected():
    with pytest.raises(RpaError):
        apply_cleanup(_base_workflow(), [{"op": "nuke", "step": "step_01"}])


def test_op_touching_locators_is_rejected():
    with pytest.raises(RpaError):
        apply_cleanup(_base_workflow(), [
            {"op": "flag", "step": "step_01", "target": {"locators": [{"coords": {"x": 1, "y": 1}}]}},
        ])


def test_unknown_field_on_a_known_op_is_rejected():
    with pytest.raises(RpaError):
        apply_cleanup(_base_workflow(), [{"op": "delete", "step": "step_01", "extra": 1}])


def test_cleanup_result_round_trips_through_parse_workflow():
    wf = apply_cleanup(_base_workflow(), [{"op": "rename", "step": "step_01", "to": "click_ok"}])
    from rpa.workflow import parse_workflow
    import yaml
    assert parse_workflow(yaml.safe_load(dump_workflow(wf))) == wf


def test_rename_to_an_existing_id_is_rejected():
    with pytest.raises(RpaError):
        apply_cleanup(_base_workflow(), [{"op": "rename", "step": "step_01", "to": "step_02"}])


@pytest.mark.parametrize("field", ["target", "locators", "root", "expect"])
def test_param_on_any_field_but_value_is_rejected(field):
    with pytest.raises(RpaError):
        apply_cleanup(_base_workflow(), [
            {"op": "param", "step": "step_01", "field": field, "name": "p", "default": "x"},
        ])
