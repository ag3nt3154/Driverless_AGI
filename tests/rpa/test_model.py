"""tests/rpa/test_model.py — locator validation and the fake driver (Subtask 2)."""
from __future__ import annotations

import pytest

from rpa import RpaError
from rpa.drivers.fake import FakeDriver
from rpa.model import Element, Root, validate_locator


def test_validate_locator_rejects_multiple_keys():
    with pytest.raises(RpaError):
        validate_locator({"uia": {"role": "Button"}, "css": "x"})


def test_validate_locator_rejects_unknown_key():
    with pytest.raises(RpaError):
        validate_locator({"xpath": "//div"})


@pytest.mark.parametrize(
    "locator",
    [
        {"uia": {"role": "Button", "name": "OK"}},
        {"css": "#ok"},
        {"aria": {"role": "button", "name": "OK"}},
        {"ocr": {"text": "OK"}},
        {"image": None},
        {"coords": {"x": 1, "y": 2}},
    ],
)
def test_validate_locator_accepts_each_kind(locator):
    validate_locator(locator)  # must not raise


def _tree():
    return {
        "win1": [
            {
                "role": "Group",
                "name": "Toolbar",
                "children": [
                    {"role": "Button", "name": "OK", "automation_id": "ok1"},
                    {"role": "Button", "name": "OK", "automation_id": "ok2"},
                ],
            },
            {"role": "Edit", "name": "Password", "value": "secret", "secure": True},
        ]
    }


def _roots():
    return {"win1": Root(id="win1", kind="window", title="Fixture", pid=1234, url=None, app="fixture.exe")}


def test_fake_driver_find_counts():
    driver = FakeDriver(_roots(), _tree())
    root = driver.roots()[0]

    outline = driver.outline(root)
    assert len(outline.elements) == 4  # toolbar group + 2 buttons + password edit

    hits = driver.find(root, {"uia": {"role": "Button", "name": "OK"}})
    assert len(hits) == 2

    hits = driver.find(root, {"uia": {"automation_id": "ok1"}})
    assert len(hits) == 1

    hits = driver.find(root, {"uia": {"role": "Button", "name": "Cancel"}})
    assert len(hits) == 0


def test_fake_driver_secure_element_never_exposes_value():
    driver = FakeDriver(_roots(), _tree())
    root = driver.roots()[0]
    outline = driver.outline(root)
    password = next(e for e in outline.elements if e.name == "Password")
    assert password.secure is True
    assert password.value == "[secure]"


def test_fake_driver_records_acts():
    driver = FakeDriver(_roots(), _tree())
    root = driver.roots()[0]
    [ok1] = driver.find(root, {"uia": {"automation_id": "ok1"}})
    driver.act(root, ok1, "click")
    assert driver.acts == [("win1", ok1.index, "click", None)]


def test_fake_driver_element_path_tracks_ancestors():
    driver = FakeDriver(_roots(), _tree())
    root = driver.roots()[0]
    [ok1] = driver.find(root, {"uia": {"automation_id": "ok1"}})
    assert ok1.path == ("Group:Toolbar",)


def test_fake_driver_needs_desktop_lock_configurable():
    driver = FakeDriver(_roots(), _tree(), lock_actions={"type"})
    assert driver.needs_desktop_lock("type") is True
    assert driver.needs_desktop_lock("click") is False


def test_element_is_frozen_dataclass():
    el = Element(
        index=0,
        role="Button",
        name="OK",
        automation_id=None,
        bbox=(0, 0, 1, 1),
        value=None,
        secure=False,
        interactive=True,
        path=(),
    )
    with pytest.raises(Exception):
        el.index = 1  # type: ignore[misc]


def test_fake_driver_redacts_secure_values_in_recorded_acts():
    roots = {"w": Root(id="w", kind="window", title="T", pid=1, url=None, app="a.exe")}
    driver = FakeDriver(roots, {"w": [{"role": "Edit", "name": "Password", "secure": True}]})
    root = driver.roots()[0]
    (pw,) = driver.find(root, {"uia": {"name": "Password"}})
    driver.act(root, pw, "type", "CANARY-s3cret")
    assert "CANARY" not in repr(driver.acts)


def test_within_matches_whole_ancestor_segments_only():
    roots = {"w": Root(id="w", kind="window", title="T", pid=1, url=None, app="a.exe")}
    driver = FakeDriver(roots, {"w": [
        {"role": "Group", "name": "ToolbarX", "children": [{"role": "Button", "name": "OK"}]},
    ]})
    root = driver.roots()[0]
    assert driver.find(root, {"uia": {"name": "OK", "within": "Group:Toolbar"}}) == []
    assert len(driver.find(root, {"uia": {"name": "OK", "within": "Group:ToolbarX"}})) == 1
