"""tests/rpa/test_observe.py — observation store, outline formatting, diff, rebind (Subtask 4)."""
from __future__ import annotations

import pytest

from rpa import RpaError
from rpa.drivers.fake import FakeDriver
from rpa.model import Root
from rpa.observe import ObservationStore, StaleTarget, diff, format_outline, rebind


def _secure_root_and_driver():
    roots = {"w": Root(id="w", kind="window", title="Fixture", pid=1, url=None, app="a.exe")}
    trees = {
        "w": [
            {"role": "Edit", "name": "Password", "value": "secret", "secure": True},
            {"role": "Button", "name": "Login", "automation_id": "login"},
        ]
    }
    driver = FakeDriver(roots, trees)
    return driver, driver.roots()[0]


# -- ObservationStore ---------------------------------------------------------


def test_observation_store_ids_are_monotonic_per_store():
    driver, root = _secure_root_and_driver()
    store = ObservationStore()
    outline1 = driver.outline(root)
    outline2 = driver.outline(root)
    assert store.record(outline1) == "obs_1"
    assert store.record(outline2) == "obs_2"


def test_observation_store_get_round_trips():
    driver, root = _secure_root_and_driver()
    store = ObservationStore()
    outline = driver.outline(root)
    obs_id = store.record(outline)
    assert store.get(obs_id) is outline


def test_observation_store_get_unknown_id_raises_rpa_error():
    store = ObservationStore()
    with pytest.raises(RpaError):
        store.get("obs_999")


def test_observation_store_evicts_after_ten_per_root():
    driver, root = _secure_root_and_driver()
    store = ObservationStore()
    ids = [store.record(driver.outline(root)) for _ in range(12)]
    with pytest.raises(RpaError):
        store.get(ids[0])
    with pytest.raises(RpaError):
        store.get(ids[1])
    assert store.get(ids[-1]) is not None


def test_observation_store_latest_returns_most_recent_for_root():
    driver, root = _secure_root_and_driver()
    store = ObservationStore()
    store.record(driver.outline(root))
    second = driver.outline(root)
    store.record(second)
    assert store.latest(root.id) is second


def test_observation_store_latest_unknown_root_returns_none():
    store = ObservationStore()
    assert store.latest("nope") is None


# -- format_outline ------------------------------------------------------------


def test_format_outline_never_includes_secure_value_canary():
    driver, root = _secure_root_and_driver()
    outline = driver.outline(root)
    text = format_outline(outline)
    assert "secret" not in text
    assert "[secure]" in text


def test_format_outline_includes_name_role_and_id():
    driver, root = _secure_root_and_driver()
    outline = driver.outline(root)
    text = format_outline(outline)
    login = next(e for e in outline.elements if e.name == "Login")
    assert f'[{login.index}] Button "Login"' in text
    assert "id=login" in text


def test_format_outline_omits_non_interactive_unnamed_elements():
    roots = {"w": Root(id="w", kind="window", title="T", pid=1, url=None, app="a.exe")}
    trees = {
        "w": [
            {"role": "Pane", "name": "", "interactive": False},
            {"role": "Button", "name": "OK"},
        ]
    }
    driver = FakeDriver(roots, trees)
    root = driver.roots()[0]
    outline = driver.outline(root)
    text = format_outline(outline)
    assert "Pane" not in text
    assert "OK" in text


def test_format_outline_truncates_and_reports_remaining():
    roots = {"w": Root(id="w", kind="window", title="T", pid=1, url=None, app="a.exe")}
    trees = {"w": [{"role": "Button", "name": f"B{i}"} for i in range(10)]}
    driver = FakeDriver(roots, trees)
    root = driver.roots()[0]
    outline = driver.outline(root)
    text = format_outline(outline, max_lines=3)
    lines = text.splitlines()
    assert len(lines) == 4
    assert "more elements" in lines[-1]
    assert "7" in lines[-1]


# -- diff -----------------------------------------------------------------------


def test_diff_reports_appeared_and_disappeared():
    roots = {"w": Root(id="w", kind="window", title="T", pid=1, url=None, app="a.exe")}
    tree = [{"role": "Button", "name": "OK"}]
    driver = FakeDriver(roots, {"w": tree})
    root = driver.roots()[0]
    before = driver.outline(root)

    tree.clear()
    tree.append({"role": "Button", "name": "Cancel"})
    after = driver.outline(root)

    lines = diff(before, after)
    assert any(line.startswith("-") and "OK" in line for line in lines)
    assert any(line.startswith("+") and "Cancel" in line for line in lines)


def test_diff_reports_value_change():
    roots = {"w": Root(id="w", kind="window", title="T", pid=1, url=None, app="a.exe")}
    tree = [{"role": "Edit", "name": "Search", "value": "foo"}]
    driver = FakeDriver(roots, {"w": tree})
    root = driver.roots()[0]
    before = driver.outline(root)

    tree[0]["value"] = "bar"
    after = driver.outline(root)

    lines = diff(before, after)
    assert any(line.startswith("~") and '"foo"' in line and '"bar"' in line for line in lines)


def test_diff_never_includes_secure_value_canary():
    roots = {"w": Root(id="w", kind="window", title="T", pid=1, url=None, app="a.exe")}
    tree = [{"role": "Edit", "name": "Password", "value": "CANARY-s3cret", "secure": True}]
    driver = FakeDriver(roots, {"w": tree})
    root = driver.roots()[0]
    before = driver.outline(root)

    tree[0]["value"] = "CANARY-other-secret"
    after = driver.outline(root)

    lines = diff(before, after)
    assert "CANARY" not in "\n".join(lines)


def test_diff_reports_title_change():
    root_a = Root(id="w", kind="window", title="Old Title", pid=1, url=None, app="a.exe")
    root_b = Root(id="w", kind="window", title="New Title", pid=1, url=None, app="a.exe")
    driver = FakeDriver({"w": root_a}, {"w": []})
    before = driver.outline(root_a)
    after = driver.outline(root_b)

    lines = diff(before, after)
    assert any("Old Title" in line and "New Title" in line for line in lines)


def test_diff_caps_at_15_lines():
    roots = {"w": Root(id="w", kind="window", title="T", pid=1, url=None, app="a.exe")}
    tree = [{"role": "Button", "name": f"B{i}"} for i in range(20)]
    driver = FakeDriver(roots, {"w": tree})
    root = driver.roots()[0]
    before = driver.outline(root)

    tree.clear()
    after = driver.outline(root)

    lines = diff(before, after)
    assert len(lines) <= 15


# -- rebind ---------------------------------------------------------------------


def test_rebind_after_reorder_rebinds_by_locator_not_index():
    roots = {"w": Root(id="w", kind="window", title="T", pid=1, url=None, app="a.exe")}
    tree = [
        {"role": "Button", "name": "A", "automation_id": "a"},
        {"role": "Button", "name": "B", "automation_id": "b"},
        {"role": "Button", "name": "C", "automation_id": "c"},
        {"role": "Button", "name": "D", "automation_id": "d"},
        {"role": "Button", "name": "Target", "automation_id": "target"},
    ]
    driver = FakeDriver(roots, {"w": tree})
    root = driver.roots()[0]
    store = ObservationStore()
    outline = driver.outline(root)
    obs_id = store.record(outline)
    target = next(e for e in outline.elements if e.name == "Target")
    assert target.index == 4

    # Reorder: insert a new element at the front so "Target" is no longer at index 4.
    tree.insert(0, {"role": "Button", "name": "Z", "automation_id": "z"})

    element = rebind(store, obs_id, 4, driver, root)
    assert element.name == "Target"
    assert element.automation_id == "target"

    driver.act(root, element, "click")
    assert driver.acts[-1] == ("w", element.index, "click", None)


def test_rebind_removed_target_raises_stale_target_and_no_act_recorded():
    roots = {"w": Root(id="w", kind="window", title="T", pid=1, url=None, app="a.exe")}
    tree = [
        {"role": "Button", "name": "A", "automation_id": "a"},
        {"role": "Button", "name": "Target", "automation_id": "target"},
    ]
    driver = FakeDriver(roots, {"w": tree})
    root = driver.roots()[0]
    store = ObservationStore()
    outline = driver.outline(root)
    obs_id = store.record(outline)
    target = next(e for e in outline.elements if e.name == "Target")

    # Remove the target element entirely.
    tree.pop(1)

    with pytest.raises(StaleTarget):
        rebind(store, obs_id, target.index, driver, root)
    assert driver.acts == []


def test_rebind_unchanged_outline_returns_live_element_at_same_index():
    driver, root = _secure_root_and_driver()
    store = ObservationStore()
    outline = driver.outline(root)
    obs_id = store.record(outline)
    login = next(e for e in outline.elements if e.name == "Login")

    element = rebind(store, obs_id, login.index, driver, root)
    assert element.name == "Login"
    assert element.automation_id == "login"


def test_rebind_unknown_index_raises_stale_target():
    driver, root = _secure_root_and_driver()
    store = ObservationStore()
    obs_id = store.record(driver.outline(root))

    with pytest.raises(StaleTarget):
        rebind(store, obs_id, 999, driver, root)


def test_duplicate_target_does_not_shift_to_its_twin_when_one_is_inserted_above():
    """Two identical OK buttons; a third appears above them. Index 1 must not
    silently become the other OK — the target is ambiguous, so rebind refuses."""
    from rpa.drivers.fake import FakeDriver
    from rpa.model import Root
    roots = {"w": Root(id="w", kind="window", title="T", pid=1, url=None, app="a.exe")}
    tree = {"w": [{"role": "Button", "name": "OK"}, {"role": "Button", "name": "OK"}]}
    driver = FakeDriver(roots, tree)
    root = driver.roots()[0]
    store = ObservationStore()
    obs = store.record(driver.outline(root))
    tree["w"].insert(0, {"role": "Button", "name": "OK"})
    with pytest.raises(StaleTarget):
        rebind(store, obs, 1, driver, root)
    assert driver.acts == []


def test_unchanged_outline_trusts_the_index_even_with_duplicates():
    from rpa.drivers.fake import FakeDriver
    from rpa.model import Root
    roots = {"w": Root(id="w", kind="window", title="T", pid=1, url=None, app="a.exe")}
    driver = FakeDriver(roots, {"w": [{"role": "Button", "name": "OK"}, {"role": "Button", "name": "OK"}]})
    root = driver.roots()[0]
    store = ObservationStore()
    obs = store.record(driver.outline(root))
    assert rebind(store, obs, 1, driver, root).index == 1
