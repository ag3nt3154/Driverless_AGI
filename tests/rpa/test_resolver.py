"""tests/rpa/test_resolver.py — locator resolution and generation (Subtask 3)."""
from __future__ import annotations

import pytest

from rpa.drivers.fake import FakeDriver
from rpa.model import Root
from rpa.resolver import Ambiguous, NotFound, is_unstable_id, generate_locators, resolve


def _two_ok_buttons_root():
    roots = {"win1": Root(id="win1", kind="window", title="Fixture", pid=1, url=None, app="fixture.exe")}
    trees = {
        "win1": [
            {"role": "Button", "name": "OK", "automation_id": "ok1"},
            {"role": "Button", "name": "OK", "automation_id": "ok2"},
        ]
    }
    driver = FakeDriver(roots, trees)
    root = driver.roots()[0]
    return driver, root


def _two_ok_buttons_in_different_panels():
    roots = {"win1": Root(id="win1", kind="window", title="Fixture", pid=1, url=None, app="fixture.exe")}
    trees = {
        "win1": [
            {
                "role": "Group",
                "name": "Left",
                "children": [{"role": "Button", "name": "OK"}],
            },
            {
                "role": "Group",
                "name": "Right",
                "children": [{"role": "Button", "name": "OK"}],
            },
        ]
    }
    driver = FakeDriver(roots, trees)
    root = driver.roots()[0]
    return driver, root


# -- resolve() ---------------------------------------------------------------


def test_resolve_ambiguous_halts_and_records_no_act():
    driver, root = _two_ok_buttons_root()
    locators = [{"uia": {"role": "Button", "name": "OK"}}]
    with pytest.raises(Ambiguous):
        resolve(driver, root, locators)
    assert driver.acts == []


def test_resolve_falls_through_zero_match_rung_to_next():
    driver, root = _two_ok_buttons_in_different_panels()
    locators = [
        {"uia": {"automation_id": "does-not-exist"}},
        {"uia": {"role": "Button", "name": "OK", "within": "Group:Left"}},
    ]
    resolution = resolve(driver, root, locators)
    assert resolution.rung_index == 1
    assert resolution.element.name == "OK"


def test_resolve_not_found_when_all_rungs_miss():
    driver, root = _two_ok_buttons_root()
    locators = [{"uia": {"automation_id": "nope"}}]
    with pytest.raises(NotFound):
        resolve(driver, root, locators)


def test_resolve_skips_ocr_and_image_rungs():
    driver, root = _two_ok_buttons_root()
    locators = [{"ocr": {"text": "OK"}}, {"image": None}]
    with pytest.raises(NotFound):
        resolve(driver, root, locators)


def test_resolve_skips_coords_unless_allowed():
    roots = {"win1": Root(id="win1", kind="window", title="Fixture", pid=1, url=None, app="fixture.exe")}
    trees = {"win1": [{"role": "Button", "name": "OK", "bbox": (0, 0, 10, 10)}]}
    driver = FakeDriver(roots, trees)
    root = driver.roots()[0]
    locators = [{"coords": {"x": 5, "y": 5}}]

    with pytest.raises(NotFound):
        resolve(driver, root, locators)

    resolution = resolve(driver, root, locators, allow_coords=True)
    assert resolution.rung_index == 0
    assert resolution.element.name == "OK"


# -- generate_locators() -----------------------------------------------------


def test_generate_locators_omits_non_unique_bare_role_name_but_adds_within():
    driver, root = _two_ok_buttons_in_different_panels()
    outline = driver.outline(root).elements
    left_ok = next(e for e in outline if e.path == ("Group:Left",))

    locators = generate_locators(driver, root, left_ok)

    bare_uia = [
        loc
        for loc in locators
        if "uia" in loc and "within" not in loc["uia"] and loc["uia"].get("role") == "Button"
    ]
    assert bare_uia == []

    within_locators = [loc for loc in locators if "uia" in loc and "within" in loc["uia"]]
    assert len(within_locators) == 1
    assert within_locators[0]["uia"]["within"] == ["Group:Left"]

    # The within-scoped locator must actually resolve uniquely to this element.
    resolution = resolve(driver, root, [within_locators[0]])
    assert resolution.element.index == left_ok.index


def test_generate_locators_never_emits_guid_automation_id():
    roots = {"win1": Root(id="win1", kind="window", title="Fixture", pid=1, url=None, app="fixture.exe")}
    trees = {"win1": [{"role": "Button", "name": "Submit", "automation_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"}]}
    driver = FakeDriver(roots, trees)
    root = driver.roots()[0]
    [element] = driver.outline(root).elements

    locators = generate_locators(driver, root, element)

    for loc in locators:
        if "uia" in loc:
            assert "automation_id" not in loc["uia"]


def test_generate_locators_rung1_id_for_stable_automation_id():
    driver, root = _two_ok_buttons_root()
    outline = driver.outline(root).elements
    first_ok = outline[0]

    locators = generate_locators(driver, root, first_ok)

    assert locators[0] == {"uia": {"automation_id": "ok1"}}


def test_generate_locators_always_ends_with_ocr_image_coords():
    driver, root = _two_ok_buttons_root()
    outline = driver.outline(root).elements
    element = outline[0]

    locators = generate_locators(driver, root, element)

    assert locators[-3] == {"ocr": {"text": "OK"}}
    assert locators[-2] == {"image": None}
    assert "coords" in locators[-1]


def test_generate_locators_omits_ocr_when_name_empty():
    roots = {"win1": Root(id="win1", kind="window", title="Fixture", pid=1, url=None, app="fixture.exe")}
    trees = {"win1": [{"role": "Pane", "name": "", "automation_id": None}]}
    driver = FakeDriver(roots, trees)
    root = driver.roots()[0]
    [element] = driver.outline(root).elements

    locators = generate_locators(driver, root, element)

    assert not any("ocr" in loc for loc in locators)


# -- is_unstable_id() ---------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "{3fa85f64-5717-4562-b3fc-2c963f66afa6}",
        "a1b2c3d4e5f6",  # 12 hex chars
        "item_1043",
        "row-2048",
    ],
)
def test_is_unstable_id_true_cases(value):
    assert is_unstable_id(value) is True


@pytest.mark.parametrize(
    "value",
    ["1001", "btnExport", "MemPlus", "CloseButton", "1", None, ""],
)
def test_is_unstable_id_false_cases(value):
    assert is_unstable_id(value) is False


@pytest.mark.parametrize("value", ["0x7ffa12bc34de", "0X00007FFA12BC34DE"])
def test_hex_ids_with_0x_prefix_are_unstable(value):
    assert is_unstable_id(value)


def test_browser_rung1_emits_the_driver_css_token_and_checks_its_raw_value():
    roots = {"tab": Root(id="tab", kind="browser", title="T", pid=None, url="http://x/", app="http://x")}
    driver = FakeDriver(roots, {"tab": [
        {"role": "button", "name": "Export", "automation_id": '[data-testid="export-btn"]'},
        {"role": "button", "name": "Go", "automation_id": "#a1b2c3d4-0000-1111-2222-333344445555"},
    ]})
    root = driver.roots()[0]
    export, go = driver.outline(root).elements
    assert generate_locators(driver, root, export)[0] == {"css": '[data-testid="export-btn"]'}
    assert all("css" not in loc for loc in generate_locators(driver, root, go))
