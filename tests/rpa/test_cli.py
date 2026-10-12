"""tests/rpa/test_cli.py — rpa/__main__.py: exit codes, --param, approve gating
(Subtask 16). Drivers and store are injected so no real UIA/Firefox is touched."""
from __future__ import annotations

from rpa.__main__ import main
from rpa.drivers.fake import FakeDriver
from rpa.model import Root
from rpa.store import WorkflowStore
from rpa.workflow import parse_workflow

_ROOT = Root(id="w:1", kind="window", title="Main", pid=111, url=None, app="fixture.exe")


def _store(tmp_path) -> WorkflowStore:
    return WorkflowStore(tmp_path / ".dagi" / "rpa")


def _save(store, data, *, status: str = "draft") -> None:
    store.save(parse_workflow(data), status=status)


def _drivers(tree):
    d = FakeDriver({"w:1": _ROOT}, {"w:1": tree})
    return {"window": d, "browser": d}


def _ok_workflow(name: str = "demo") -> dict:
    return {
        "name": name,
        "steps": [{
            "id": "click_ok",
            "act": "click",
            "root": {"window": {"title_re": "Main"}},
            "target": {"locators": [{"uia": {"automation_id": "btnOk"}}]},
        }],
    }


def _degraded_workflow(name: str = "demo") -> dict:
    return {
        "name": name,
        "steps": [{
            "id": "click_ok",
            "act": "click",
            "root": {"window": {"title_re": "Main"}},
            "target": {"locators": [
                {"uia": {"automation_id": "no-such-id"}},
                {"uia": {"role": "Button", "name": "OK"}},
            ]},
        }],
    }


def _halted_workflow(name: str = "demo") -> dict:
    return {
        "name": name,
        "steps": [{
            "id": "click_missing",
            "act": "click",
            "root": {"window": {"title_re": "Main"}},
            "target": {"locators": [{"uia": {"automation_id": "nope"}}]},
        }],
    }


def test_run_ok_exit_0(tmp_path):
    store = _store(tmp_path)
    _save(store, _ok_workflow())
    drivers = _drivers([{"role": "Button", "name": "OK", "automation_id": "btnOk"}])
    code = main(["run", "demo"], drivers=drivers, store=store, isatty=lambda: False)
    assert code == 0


def test_run_degraded_exit_1(tmp_path):
    store = _store(tmp_path)
    _save(store, _degraded_workflow())
    drivers = _drivers([{"role": "Button", "name": "OK", "automation_id": "btnOk"}])
    code = main(["run", "demo"], drivers=drivers, store=store, isatty=lambda: False)
    assert code == 1


def test_run_halted_exit_2(tmp_path):
    store = _store(tmp_path)
    _save(store, _halted_workflow())
    drivers = _drivers([{"role": "Button", "name": "OK", "automation_id": "btnOk"}])
    code = main(["run", "demo"], drivers=drivers, store=store, isatty=lambda: False)
    assert code == 2


def test_run_unknown_workflow_exit_3(tmp_path):
    store = _store(tmp_path)
    drivers = {"window": FakeDriver({}, {}), "browser": FakeDriver({}, {})}
    code = main(["run", "nope"], drivers=drivers, store=store, isatty=lambda: False)
    assert code == 3


def test_run_bad_param_exit_3(tmp_path):
    store = _store(tmp_path)
    _save(store, _ok_workflow())
    drivers = _drivers([{"role": "Button", "name": "OK", "automation_id": "btnOk"}])
    code = main(["run", "demo", "--param", "noequals"], drivers=drivers, store=store, isatty=lambda: False)
    assert code == 3


def test_run_param_parsing_reaches_the_workflow(tmp_path):
    store = _store(tmp_path)
    _save(store, {
        "name": "demo",
        "params": {"who": {"default": "nobody"}},
        "steps": [{
            "id": "set_name",
            "act": "set_value",
            "root": {"window": {"title_re": "Main"}},
            "target": {"locators": [{"uia": {"automation_id": "note"}}]},
            "value": "{{ who }}",
        }],
    })
    drivers = _drivers([{"role": "Edit", "name": "Note", "automation_id": "note"}])
    code = main(["run", "demo", "--param", "who=Admiral"], drivers=drivers, store=store, isatty=lambda: False)
    assert code == 0
    assert drivers["window"].acts[0][3] == "Admiral"


def test_run_warns_when_not_approved(tmp_path, capsys):
    store = _store(tmp_path)
    _save(store, _ok_workflow())
    drivers = _drivers([{"role": "Button", "name": "OK", "automation_id": "btnOk"}])
    main(["run", "demo"], drivers=drivers, store=store, isatty=lambda: False)
    err = capsys.readouterr().err.lower()
    assert "not approved" in err or "approve" in err


def test_run_every_run_confirm_without_tty_halts(tmp_path):
    store = _store(tmp_path)
    _save(store, {
        "name": "demo",
        "steps": [{
            "id": "send_it",
            "act": "click",
            "root": {"window": {"title_re": "Main"}},
            "target": {"locators": [{"uia": {"automation_id": "btnSend"}}]},
            "confirm": "every_run",
        }],
    })
    drivers = _drivers([{"role": "Button", "name": "Send", "automation_id": "btnSend"}])
    code = main(["run", "demo"], drivers=drivers, store=store, isatty=lambda: False)
    assert code == 2
    assert drivers["window"].acts == []


def test_approve_refused_before_clean_verify(tmp_path):
    store = _store(tmp_path)
    _save(store, _ok_workflow())
    code = main(["approve", "demo"], store=store, isatty=lambda: True, input_fn=lambda _p: "y")
    assert code == 3
    assert store.state("demo")["status"] != "approved"


def test_approve_without_tty_refused(tmp_path):
    store = _store(tmp_path)
    _save(store, _ok_workflow())
    store.mark_verified("demo")
    code = main(["approve", "demo"], store=store, isatty=lambda: False)
    assert code == 3
    assert store.state("demo")["status"] != "approved"


def test_approve_with_input_y_after_clean_verify_succeeds(tmp_path):
    store = _store(tmp_path)
    _save(store, _ok_workflow())
    drivers = _drivers([{"role": "Button", "name": "OK", "automation_id": "btnOk"}])
    verify_code = main(["run", "demo", "--verify"], drivers=drivers, store=store, isatty=lambda: False)
    assert verify_code == 0

    code = main(["approve", "demo"], store=store, isatty=lambda: True, input_fn=lambda _p: "y")
    assert code == 0
    assert store.state("demo")["status"] == "approved"


def test_list_and_show_smoke(tmp_path, capsys):
    store = _store(tmp_path)
    _save(store, _ok_workflow())

    assert main(["list"], store=store) == 0
    out = capsys.readouterr().out
    assert "demo" in out

    assert main(["show", "demo"], store=store) == 0
    out2 = capsys.readouterr().out
    assert "demo" in out2
