"""tests/rpa/test_workflow.py — D1 workflow format: load, validate, template, hash (Subtask 12)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
import yaml

from rpa import RpaError
from rpa.workflow import (
    Param,
    SecretRef,
    Step,
    Workflow,
    dump_workflow,
    load_workflow,
    parse_workflow,
    render,
    resolve_secrets,
    step_hash,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sales_export.yaml"


# --- fixture load / round-trip ---

def test_fixture_loads():
    wf = load_workflow(FIXTURE)
    assert wf.name == "sales_export"
    assert wf.params["report_date"] == Param(default="{{ yesterday | date('%Y-%m-%d') }}")
    assert wf.secrets["portal_pw"] == SecretRef(env="PORTAL_PW")
    assert [s.id for s in wf.steps] == [
        "launch_app", "open_export_dialog", "set_report_date", "confirm_export",
        "open_portal", "login_to_portal", "upload_file",
    ]
    confirm_export = next(s for s in wf.steps if s.id == "confirm_export")
    assert confirm_export.confirm == "once"
    login = next(s for s in wf.steps if s.id == "login_to_portal")
    assert login.confirm == "every_run"


def test_fixture_round_trips():
    wf = load_workflow(FIXTURE)
    dumped = dump_workflow(wf)
    wf2 = parse_workflow(yaml.safe_load(dumped))
    assert wf2 == wf


# --- validation ---

def test_typo_key_fails_with_path():
    data = {"name": "x", "steps": [{"id": "s1", "act": "click", "targt": {}}]}
    with pytest.raises(RpaError, match=r"steps\[0\]\.targt"):
        parse_workflow(data)


def test_code_step_rejected():
    data = {"name": "x", "steps": [{"id": "s1", "code": "print(1)"}]}
    with pytest.raises(RpaError, match="code steps are not supported in v1"):
        parse_workflow(data)


def test_bad_chord_rejected():
    data = {"name": "x", "steps": [{"id": "s1", "act": "key", "value": "ctrl+plus+plus"}]}
    with pytest.raises(RpaError):
        parse_workflow(data)


def test_templated_chord_is_not_validated():
    data = {"name": "x", "steps": [{"id": "s1", "act": "key", "value": "{{ chord }}"}]}
    parse_workflow(data)  # must not raise


def test_undeclared_secret_rejected():
    data = {"name": "x", "steps": [{"id": "s1", "act": "set_value", "value": "{{ secrets.NOPE }}"}]}
    with pytest.raises(RpaError, match="secrets.NOPE"):
        parse_workflow(data)


def test_declared_secret_ok():
    data = {
        "name": "x",
        "secrets": {"portal_pw": {"env": "PORTAL_PW"}},
        "steps": [{"id": "s1", "act": "set_value", "value": "{{ secrets.portal_pw }}"}],
    }
    parse_workflow(data)  # must not raise


def test_duplicate_step_id_rejected():
    data = {"name": "x", "steps": [
        {"id": "s1", "act": "click"},
        {"id": "s1", "act": "click"},
    ]}
    with pytest.raises(RpaError):
        parse_workflow(data)


def test_bad_step_id_rejected():
    data = {"name": "x", "steps": [{"id": "Bad-ID", "act": "click"}]}
    with pytest.raises(RpaError):
        parse_workflow(data)


def test_act_and_launch_are_mutually_exclusive():
    with pytest.raises(RpaError):
        parse_workflow({"name": "x", "steps": [{"id": "s1", "act": "click", "launch": "x.exe"}]})
    with pytest.raises(RpaError):
        parse_workflow({"name": "x", "steps": [{"id": "s1"}]})


def test_unknown_action_rejected():
    data = {"name": "x", "steps": [{"id": "s1", "act": "nope"}]}
    with pytest.raises(RpaError):
        parse_workflow(data)


def test_unknown_confirm_value_rejected():
    data = {"name": "x", "steps": [{"id": "s1", "act": "click", "confirm": "sometimes"}]}
    with pytest.raises(RpaError):
        parse_workflow(data)


def test_bad_locator_in_target_rejected():
    data = {"name": "x", "steps": [{
        "id": "s1", "act": "click", "target": {"locators": [{"uia": {}, "css": "x"}]},
    }]}
    with pytest.raises(RpaError, match=r"steps\[0\]\.target\.locators\[0\]"):
        parse_workflow(data)


def test_root_requires_exactly_one_kind():
    data = {"name": "x", "steps": [{
        "id": "s1", "act": "click", "root": {"window": {"title_re": "x"}, "browser": {"url_re": "y"}},
    }]}
    with pytest.raises(RpaError):
        parse_workflow(data)


# --- render ---

def test_render_plain_text_unchanged():
    assert render("no templates here", {}) == "no templates here"


def test_render_name():
    assert render("hello {{ name }}", {"name": "world"}) == "hello world"


def test_render_item_and_secrets():
    ctx = {"item": "row-1", "secrets": {"portal_pw": "s3cr3t"}}
    assert render("{{ item }}:{{ secrets.portal_pw }}", ctx) == "row-1:s3cr3t"


def test_render_yesterday_with_injected_now():
    now = dt.date(2026, 10, 11)
    assert render("{{ yesterday | date('%Y-%m-%d') }}", {}, now=now) == "2026-10-10"


def test_render_today_default_str_is_iso():
    now = dt.date(2026, 10, 11)
    assert render("{{ today }}", {}, now=now) == "2026-10-11"


def test_render_unknown_name_raises():
    with pytest.raises(RpaError):
        render("{{ nope }}", {})


def test_render_unknown_dotted_name_raises():
    with pytest.raises(RpaError):
        render("{{ secrets.nope }}", {"secrets": {}})


# --- resolve_secrets ---

def test_resolve_secrets_ok():
    wf = Workflow(name="x", secrets={"portal_pw": SecretRef(env="PORTAL_PW")})
    assert resolve_secrets(wf, {"PORTAL_PW": "s3cr3t"}) == {"portal_pw": "s3cr3t"}


def test_resolve_secrets_missing_var_message_has_no_value():
    wf = Workflow(name="x", secrets={
        "a": SecretRef(env="HAVE_IT"),
        "b": SecretRef(env="MISSING_IT"),
    })
    with pytest.raises(RpaError) as exc_info:
        resolve_secrets(wf, {"HAVE_IT": "super-secret-value"})
    message = str(exc_info.value)
    assert "MISSING_IT" in message
    assert "super-secret-value" not in message


# --- step_hash ---

def test_step_hash_is_stable():
    assert step_hash(Step(id="s1", act="click")) == step_hash(Step(id="s1", act="click"))


@pytest.mark.parametrize("field_name,value", [
    ("value", "x"),
    ("confirm", "once"),
    ("sensitive", True),
    ("retry", 3),
    ("on_fail", "continue"),
])
def test_step_hash_changes_on_any_field_change(field_name, value):
    base = Step(id="s1", act="click")
    changed = Step(**{**base.__dict__, field_name: value})
    assert step_hash(base) != step_hash(changed)
