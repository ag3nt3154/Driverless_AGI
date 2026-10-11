"""tests/rpa/test_trace.py — Recorder: trace.jsonl content and refusal rules (Subtask 13)."""
from __future__ import annotations

import json

import pytest

from rpa import RpaError
from rpa.drivers.fake import FakeDriver
from rpa.model import Root
from rpa.store import WorkflowStore
from rpa.trace import Recorder

_ROOT = Root(id="r1", kind="window", title="MyApp", pid=1, url=None, app="app.exe")

_TREE = [
    {"role": "Button", "name": "OK", "automation_id": "btnOK", "bbox": (0, 0, 50, 20)},
    {"role": "Edit", "name": "Password", "automation_id": "pwd", "secure": True, "bbox": (0, 30, 50, 50)},
]


def _driver(tree=None):
    return FakeDriver({"r1": _ROOT}, {"r1": tree if tree is not None else [dict(n) for n in _TREE]})


def _recorder(tmp_path, driver=None, name="demo", goal="export the thing"):
    store = WorkflowStore(tmp_path)
    driver = driver or _driver()
    return Recorder(store, name, goal, driver_for=lambda root: driver), store, driver


def _outline(driver):
    return driver.outline(_ROOT)


def test_start_writes_a_header_line(tmp_path):
    recorder, store, _driver = _recorder(tmp_path)
    recorder.start()

    trace_path = store.dir("demo") / "trace.jsonl"
    lines = trace_path.read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    assert header == {"kind": "header", "name": "demo", "goal": "export the thing", "started_at": header["started_at"]}


def test_start_refuses_a_duplicate_name(tmp_path):
    recorder, store, driver = _recorder(tmp_path)
    recorder.start()
    recorder2, _store2, _driver2 = _recorder(tmp_path, driver=driver)
    with pytest.raises(RpaError):
        recorder2.start()


def test_start_refuses_when_a_workflow_already_exists(tmp_path):
    from rpa.workflow import Step, Workflow
    store = WorkflowStore(tmp_path)
    store.save(Workflow(name="demo", steps=[Step(id="s1", act="click")]))
    recorder, _store, _driver = _recorder(tmp_path)
    with pytest.raises(RpaError):
        recorder.start()


def test_record_act_appends_one_act_line(tmp_path):
    recorder, store, driver = _recorder(tmp_path)
    recorder.start()
    before = _outline(driver)
    element = next(e for e in before.elements if e.name == "OK")
    driver.act(_ROOT, element, "click")
    after = _outline(driver)

    recorder.record_act(_ROOT, element, "click", None, before, after)

    lines = (store.dir("demo") / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[-1])
    assert entry["kind"] == "act"
    assert entry["n"] == 1
    assert entry["action"] == "click"
    assert entry["root"] == {"kind": "window", "app": "app.exe", "title_re": entry["root"]["title_re"]}
    assert entry["before"] == {"role": "Button", "name": "OK", "path": []}


def test_secure_value_is_never_the_literal_and_canary_never_appears(tmp_path):
    recorder, store, driver = _recorder(tmp_path)
    recorder.start()
    before = _outline(driver)
    element = next(e for e in before.elements if e.name == "Password")
    after = _outline(driver)

    recorder.record_act(_ROOT, element, "set_value", "s3cr3t-canary", before, after)

    trace_text = (store.dir("demo") / "trace.jsonl").read_text(encoding="utf-8")
    assert "s3cr3t-canary" not in trace_text
    entry = json.loads(trace_text.splitlines()[-1])
    assert entry["value"] == {"secret": True}


def test_env_reference_value_is_recorded_as_secret_env(tmp_path):
    recorder, store, driver = _recorder(tmp_path)
    recorder.start()
    before = _outline(driver)
    element = next(e for e in before.elements if e.name == "OK")
    after = _outline(driver)

    recorder.record_act(_ROOT, element, "set_value", "${env:MY_SECRET}", before, after)

    entry = json.loads((store.dir("demo") / "trace.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert entry["value"] == {"secret_env": "MY_SECRET"}


def test_generate_locators_are_recorded_with_image_placeholder_replaced(tmp_path):
    recorder, store, driver = _recorder(tmp_path)
    recorder.start()
    before = _outline(driver)
    element = next(e for e in before.elements if e.name == "OK")
    after = _outline(driver)

    recorder.record_act(_ROOT, element, "click", None, before, after)

    entry = json.loads((store.dir("demo") / "trace.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    image_locs = [loc for loc in entry["locators"] if "image" in loc]
    # The placeholder is either filled with a saved crop path, or dropped on capture failure.
    assert image_locs == [] or image_locs[0]["image"].startswith("crops/")
    if image_locs:
        crop_path = store.dir("demo") / image_locs[0]["image"]
        assert crop_path.exists()


def test_record_launch_appends_a_launch_line(tmp_path):
    recorder, store, _driver = _recorder(tmp_path)
    recorder.start()

    recorder.record_launch(_ROOT, "notepad.exe")

    entry = json.loads((store.dir("demo") / "trace.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert entry["kind"] == "launch"
    assert entry["target"] == "notepad.exe"
    assert entry["app"] == "app.exe"


def test_entries_then_stop_returns_recorded_entries(tmp_path):
    recorder, _store, driver = _recorder(tmp_path)
    recorder.start()
    before = _outline(driver)
    element = next(e for e in before.elements if e.name == "OK")
    after = _outline(driver)
    recorder.record_act(_ROOT, element, "click", None, before, after)

    entries = recorder.entries()
    assert [e["kind"] for e in entries] == ["header", "act"]
    assert recorder.stop() == entries


def test_title_regex_generalises_digits_and_makes_star_optional(tmp_path):
    root = Root(id="r2", kind="window", title="*Untitled - Report 42 - Notepad", pid=1, url=None, app="notepad.exe")
    driver = FakeDriver({"r2": root}, {"r2": []})
    store = WorkflowStore(tmp_path)
    recorder = Recorder(store, "demo2", "g", driver_for=lambda r: driver)
    recorder.start()
    recorder.record_launch(root, "notepad.exe")
    entry = json.loads((store.dir("demo2") / "trace.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    import re
    assert re.match(entry["title_re"], "Untitled - Report 42 - Notepad")
    assert re.match(entry["title_re"], "*Untitled - Report 999 - Notepad")


def test_title_and_url_patterns_are_anchored():
    import re
    from rpa.trace import _title_re, _url_re
    assert re.search(_title_re(""), "Some Other Window") is None
    assert re.search(_title_re("Export"), "Export And More") is None
    assert re.search(_title_re("Report 42 - App"), "*Report 7 - App")
    assert re.search(_url_re("http://h/p?q=1"), "http://h/p?q=2")
    assert re.search(_url_re("http://h/p"), "http://h/p/other") is None


def test_expect_builds_locators_for_one_new_element_only(monkeypatch):
    """A dialog adds 100+ elements; building locators for each took minutes on UIA."""
    from rpa import trace
    from rpa.model import Element, Outline, Root
    root = Root(id="w", kind="window", title="App", pid=1, url=None, app="a.exe")
    target = Element(index=0, role="Edit", name="Doc", automation_id="doc", bbox=(0, 0, 9, 9),
                     value="x", secure=False, interactive=True)
    before = Outline(root=root, elements=[target], taken_at=0.0)
    new = [Element(index=i, role="Button", name=f"b{i}", automation_id=None, bbox=(0, 0, 9, 9),
                   value=None, secure=False, interactive=True) for i in range(1, 150)]
    dialog = Element(index=150, role="Window", name="Save as", automation_id=None, bbox=(0, 0, 9, 9),
                     value=None, secure=False, interactive=False)
    after = Outline(root=root, elements=[target, *new, dialog], taken_at=1.0)
    built: list = []
    monkeypatch.setattr(trace, "generate_locators", lambda d, r, el: (built.append(el), [{"uia": {"name": el.name}}])[1])
    candidates = trace._expect_candidates(None, root, target, before, after)
    assert built == [dialog]
    assert {"present": {"uia": {"name": "Save as"}}} in candidates
