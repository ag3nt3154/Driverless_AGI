"""tests/test_ui_tools.py — the four computer-use tools, with FakeDriver injected
into UiSession so nothing here touches real UIA or Firefox.
"""
from __future__ import annotations

import copy

import pytest

from agent.loop import AgentLoop
from agent.protocol import SideEffect, ToolResult
from rpa.drivers.fake import FakeDriver
from rpa.lock import DesktopLock
from rpa.model import Root
from tools.ui import (
    ComputerUseInspectWindowTool,
    ComputerUseInteractWithWindowTool,
    ComputerUseListWindowsTool,
    ComputerUseWaitForWindowStateTool,
    UiSession,
)

_ROOT = Root(id="r1", kind="window", title="MyApp", pid=1, url=None, app="app.exe")

# >=5 interactive leaves so an outline-only observe does not auto-attach a screenshot.
_BIG_TREE = [
    {"role": "Button", "name": "OK", "automation_id": "btnOK", "bbox": (0, 0, 50, 20)},
    {"role": "Button", "name": "Send", "automation_id": "btnSend", "bbox": (0, 30, 50, 50)},
    {"role": "Edit", "name": "Password", "automation_id": "pwd", "secure": True, "bbox": (0, 60, 50, 80)},
    {"role": "Edit", "name": "Note", "automation_id": "note", "bbox": (0, 90, 50, 110)},
    {"role": "Button", "name": "Cancel", "automation_id": "btnCancel", "bbox": (0, 120, 50, 140)},
    {"role": "Button", "name": "Help", "automation_id": "btnHelp", "bbox": (0, 150, 50, 170)},
]

# A small tree (<5 elements) so observe auto-attaches a screenshot even in outline mode.
_SMALL_TREE = [
    {"role": "Button", "name": "OK", "automation_id": "btnOK", "bbox": (0, 0, 50, 20)},
]


class _Cfg:
    def __init__(self, autonomous: bool = False) -> None:
        self.autonomous = autonomous
        self.display_name = "dagi"
        self.model = "test-model"
        self.project_path = None


class _AskSpy:
    """on_ask_user spy: answers by matching a substring of the question."""

    def __init__(self, answers: dict[str, str] | None = None) -> None:
        self.calls: list[tuple[str, list[dict], "float | None"]] = []
        self._answers = answers or {"Allow dagi to control": "Allow", "Confirm:": "Allow once"}

    def on_ask_user(self, question: str, options: list[dict], timeout: "float | None") -> str:
        self.calls.append((question, options, timeout))
        for substr, label in self._answers.items():
            if substr in question:
                return label
        return options[0]["label"] if options else ""


def _make_session(tree, *, autonomous: bool = False, ask_spy: "_AskSpy | None" = None, lock_actions=None):
    driver = FakeDriver({"r1": _ROOT}, {"r1": copy.deepcopy(tree)}, lock_actions=lock_actions or set())
    callbacks = ask_spy if ask_spy is not None else _AskSpy()
    session = UiSession(_Cfg(autonomous=autonomous), callbacks, uia_driver=driver)
    return session, driver, callbacks


def _observed_root_id(session: UiSession) -> str:
    """Launch the fake app so "w:r1" is a dagi-opened, cached root, as with a real
    computer_use_list_windows(launch=...)."""
    ComputerUseListWindowsTool(session).run(launch="r1")
    return "w:r1"


# ── computer_use_list_windows ──────────────────────────────────────────────────────────────


def test_ui_roots_lists_a_launched_window_with_prefixed_id():
    session, _driver, _ = _make_session(_BIG_TREE)
    out = ComputerUseListWindowsTool(session).run(launch="r1")
    assert "w:r1 | window | app.exe | MyApp" in out


def test_ui_roots_hides_windows_dagi_did_not_open():
    """Privacy: titles of the user's own windows never reach the model."""
    session, _driver, _ = _make_session(_BIG_TREE)
    out = ComputerUseListWindowsTool(session).run()
    assert "MyApp" not in out and "1 other windows not opened by dagi are hidden" in out
    observed = ComputerUseInspectWindowTool(session).run(root="w:r1")
    assert (observed.output if isinstance(observed, ToolResult) else observed).startswith("Error")


def test_new_window_of_a_launched_process_is_listed_but_its_older_windows_are_not():
    from rpa.drivers.fake import FakeDriver
    from rpa.model import Root
    mine = Root(id="r1", kind="window", title="Mine", pid=7, url=None, app="np.exe")
    users = Root(id="r0", kind="window", title="User doc", pid=7, url=None, app="np.exe")
    roots = {"r0": users, "r1": mine}
    driver = FakeDriver(roots, {"r0": [], "r1": []})
    session = UiSession(_Cfg(), _AskSpy(), uia_driver=driver)
    ComputerUseListWindowsTool(session).run(launch="r1")
    driver._roots["r2"] = Root(id="r2", kind="window", title="Mine 2", pid=7, url=None, app="np.exe")
    out = ComputerUseListWindowsTool(session).run()
    assert "w:r1 |" in out and "w:r2 |" in out and "User doc" not in out


# ── computer_use_inspect_window ────────────────────────────────────────────────────────────


def test_ui_observe_returns_obs_id_and_outline_text():
    session, _driver, _ = _make_session(_BIG_TREE)
    root_id = _observed_root_id(session)

    result = ComputerUseInspectWindowTool(session).run(root=root_id)

    assert isinstance(result, ToolResult)
    assert result.side_effect is None
    assert result.output.startswith("obs_1\n")
    assert 'Button "OK"' in result.output
    assert 'Button "Send"' in result.output


def test_ui_observe_mode_screenshot_attaches_png_at_or_under_1280px():
    session, _driver, _ = _make_session(_BIG_TREE)
    root_id = _observed_root_id(session)

    result = ComputerUseInspectWindowTool(session).run(root=root_id, mode="screenshot")

    assert result.side_effect is SideEffect.ATTACH_IMAGE
    data = result.side_effect_data
    assert data["path"] == "computer_use_inspect_window obs_1"
    image = data["image"]
    assert image.mime_type == "image/png"
    assert image.width <= 1280
    assert image.name == "obs_1.png"


def test_ui_observe_auto_attaches_screenshot_for_few_interactive_elements():
    session, _driver, _ = _make_session(_SMALL_TREE)
    root_id = _observed_root_id(session)

    result = ComputerUseInspectWindowTool(session).run(root=root_id, mode="outline")

    assert result.side_effect is SideEffect.ATTACH_IMAGE


def test_ui_observe_never_shows_a_raw_value_for_a_secure_element():
    session, _driver, _ = _make_session(_BIG_TREE)
    root_id = _observed_root_id(session)

    result = ComputerUseInspectWindowTool(session).run(root=root_id)

    assert 'value="[secure]"' in result.output
    assert "Password" in result.output


def test_ui_observe_unknown_root_is_an_error():
    session, _driver, _ = _make_session(_BIG_TREE)
    result = ComputerUseInspectWindowTool(session).run(root="w:does-not-exist")
    assert result == "Error (NotFound): unknown root 'w:does-not-exist'; call computer_use_list_windows first"


# ── computer_use_interact_with_window ─────────────────────────────────────────────────────────────


def _observe(session, root_id, **kwargs) -> str:
    result = ComputerUseInspectWindowTool(session).run(root=root_id, **kwargs)
    output = result.output if isinstance(result, ToolResult) else result
    return output.splitlines()[0]


def test_ui_act_click_ok_button_succeeds_and_returns_new_obs_id():
    session, driver, _ = _make_session(_BIG_TREE)
    root_id = _observed_root_id(session)
    obs_id = _observe(session, root_id)

    result = ComputerUseInteractWithWindowTool(session).run(root=root_id, target=0, action="click", obs=obs_id)

    assert result.startswith('ok: click [0] Button "OK"')
    assert result.splitlines()[-1].startswith("obs_")
    assert driver.acts == [("r1", 0, "click", None)]


def test_ui_act_stale_target_rebinds_or_errors_without_a_wrong_act():
    session, driver, _ = _make_session(_BIG_TREE)
    root_id = _observed_root_id(session)
    obs_id = _observe(session, root_id)

    # The UI changes underneath the observation: the "OK" button is removed.
    driver._trees["r1"] = [n for n in driver._trees["r1"] if n["name"] != "OK"]

    result = ComputerUseInteractWithWindowTool(session).run(root=root_id, target=0, action="click", obs=obs_id)

    assert result.startswith("Error (StaleTarget):")
    assert driver.acts == []


def test_ui_act_autonomous_config_denies_and_records_no_act():
    session, driver, ask_spy = _make_session(_BIG_TREE, autonomous=True)
    root_id = _observed_root_id(session)
    obs_id = _observe(session, root_id)

    result = ComputerUseInteractWithWindowTool(session).run(root=root_id, target=0, action="click", obs=obs_id)

    assert result.startswith("Error (SafetyDenied):")
    assert driver.acts == []
    assert ask_spy.calls == []  # autonomous denies without ever asking


def test_ui_act_sensitive_button_asks_with_no_recommended_option():
    session, driver, ask_spy = _make_session(_BIG_TREE)
    root_id = _observed_root_id(session)
    obs_id = _observe(session, root_id)

    # "Send" is element index 1 in _BIG_TREE.
    result = ComputerUseInteractWithWindowTool(session).run(root=root_id, target=1, action="click", obs=obs_id)

    assert result.startswith('ok: click [1] Button "Send"')
    confirm_calls = [c for c in ask_spy.calls if c[0].startswith("Confirm:")]
    assert len(confirm_calls) == 1
    for option in confirm_calls[0][1]:
        assert "recommended" not in option


def test_ui_act_refuses_a_literal_value_for_a_password_field():
    session, driver, _ = _make_session(_BIG_TREE)
    root_id = _observed_root_id(session)
    obs_id = _observe(session, root_id)

    result = ComputerUseInteractWithWindowTool(session).run(
        root=root_id, target=2, action="set_value", obs=obs_id, value="s3cr3t-canary"
    )

    assert result.startswith("Error")
    assert "s3cr3t-canary" not in result
    assert driver.acts == []


def test_ui_act_reads_an_env_reference_for_a_password_field(monkeypatch):
    monkeypatch.setenv("DAGI_TEST_PW", "s3cr3t-canary")
    session, driver, _ = _make_session(_BIG_TREE)
    root_id = _observed_root_id(session)
    obs_id = _observe(session, root_id)
    typed: list = []
    real_act = driver.act
    monkeypatch.setattr(driver, "act", lambda root, el, action, value=None: (typed.append(value), real_act(root, el, action, value)))

    result = ComputerUseInteractWithWindowTool(session).run(
        root=root_id, target=2, action="set_value", obs=obs_id, value="${env:DAGI_TEST_PW}"
    )

    assert result.startswith("ok:") and "s3cr3t-canary" not in result
    assert typed == ["s3cr3t-canary"]


def test_ui_act_missing_env_reference_is_an_error_and_acts_nothing():
    session, driver, _ = _make_session(_BIG_TREE)
    root_id = _observed_root_id(session)
    obs_id = _observe(session, root_id)
    result = ComputerUseInteractWithWindowTool(session).run(
        root=root_id, target=2, action="set_value", obs=obs_id, value="${env:DAGI_TEST_UNSET_VAR}"
    )
    assert result.startswith("Error") and driver.acts == []


def test_ui_act_closing_the_root_itself_reports_ok(monkeypatch):
    from rpa import RpaError
    session, driver, _ = _make_session(_BIG_TREE)
    root_id = _observed_root_id(session)
    obs_id = _observe(session, root_id)
    real_act = driver.act

    def act_then_vanish(root, el, action, value=None):
        real_act(root, el, action, value)
        monkeypatch.setattr(driver, "outline", lambda *a, **k: (_ for _ in ()).throw(RpaError("window gone")))

    monkeypatch.setattr(driver, "act", act_then_vanish)
    result = ComputerUseInteractWithWindowTool(session).run(root=root_id, target=0, action="close_window", obs=obs_id)
    assert result.startswith("ok: close_window") and "can no longer be observed" in result


def test_ui_act_locked_action_acquires_lock_and_release_lock_frees_it(tmp_path):
    lock = DesktopLock(tmp_path / "desktop.lock")
    driver = FakeDriver({"r1": _ROOT}, {"r1": copy.deepcopy(_BIG_TREE)}, lock_actions={"click"})
    session = UiSession(_Cfg(), _AskSpy(), uia_driver=driver, lock=lock)
    root_id = _observed_root_id(session)
    obs_id = _observe(session, root_id)

    ComputerUseInteractWithWindowTool(session).run(root=root_id, target=0, action="click", obs=obs_id)
    assert lock.holder() is not None
    assert lock.holder()["agent"] == session.agent_name

    ComputerUseInteractWithWindowTool(session).release_lock()
    assert lock.holder() is None


def test_agent_loop_release_ui_lock_calls_ui_act_release_lock(tmp_path):
    """AgentLoop._release_ui_lock (used by interrupt() and the turn-close path)
    looks computer_use_interact_with_window up by name and releases its lock, same pattern as bash.force_kill."""
    lock = DesktopLock(tmp_path / "desktop.lock")
    driver = FakeDriver({"r1": _ROOT}, {"r1": copy.deepcopy(_BIG_TREE)}, lock_actions={"click"})
    session = UiSession(_Cfg(), _AskSpy(), uia_driver=driver, lock=lock)
    root_id = _observed_root_id(session)
    obs_id = _observe(session, root_id)
    ComputerUseInteractWithWindowTool(session).run(root=root_id, target=0, action="click", obs=obs_id)
    assert lock.holder() is not None

    class _FakeRegistry:
        _tools = {"computer_use_interact_with_window": ComputerUseInteractWithWindowTool(session)}

    fake_self = type("FakeLoop", (), {"registry": _FakeRegistry()})()
    AgentLoop._release_ui_lock(fake_self)

    assert lock.holder() is None


# ── computer_use_wait_for_window_state ────────────────────────────────────────────────────────────


def test_ui_wait_present_returns_ok_immediately():
    session, _driver, _ = _make_session(_BIG_TREE)
    root_id = _observed_root_id(session)

    result = ComputerUseWaitForWindowStateTool(session).run(
        root=root_id, condition={"present": {"uia": {"role": "Button", "name": "OK"}}}, timeout=1,
    )
    assert result.startswith("ok:")


def test_ui_wait_present_times_out_when_absent():
    session, _driver, _ = _make_session(_BIG_TREE)
    root_id = _observed_root_id(session)

    result = ComputerUseWaitForWindowStateTool(session).run(
        root=root_id, condition={"present": {"uia": {"role": "Button", "name": "Nope"}}}, timeout=0.2,
    )
    assert result.startswith("timeout:")


@pytest.mark.parametrize("target", [1, "1", "[1]", " [1] "])
def test_ui_act_accepts_an_index_with_or_without_brackets(target):
    session, driver, _ = _make_session(_BIG_TREE)
    root_id = _observed_root_id(session)
    obs_id = _observe(session, root_id)
    result = ComputerUseInteractWithWindowTool(session).run(root=root_id, target=target, action="focus", obs=obs_id)
    assert result.startswith("ok: focus [1]")


def test_ui_act_rejects_a_non_index_target_without_acting():
    session, driver, _ = _make_session(_BIG_TREE)
    root_id = _observed_root_id(session)
    obs_id = _observe(session, root_id)
    result = ComputerUseInteractWithWindowTool(session).run(root=root_id, target="[one]", action="focus", obs=obs_id)
    assert result.startswith("Error") and driver.acts == []


@pytest.mark.parametrize("region", [[0], 0, "[0]"])
def test_ui_observe_region_accepts_a_single_index(region):
    session, _, _ = _make_session(_BIG_TREE)
    root_id = _observed_root_id(session)
    result = ComputerUseInspectWindowTool(session).run(root=root_id, mode="screenshot", region=region)
    assert isinstance(result, ToolResult)


def test_ui_observe_bad_region_is_an_error():
    session, _, _ = _make_session(_BIG_TREE)
    root_id = _observed_root_id(session)
    result = ComputerUseInspectWindowTool(session).run(root=root_id, mode="screenshot", region=[1, 2])
    text = result.output if isinstance(result, ToolResult) else result
    assert text.startswith("Error")


def test_real_sessions_share_opened_windows_and_drivers_across_turns():
    """The GUI builds a new registry per turn; dagi's windows and Firefox must survive it."""
    a, b = UiSession(_Cfg(), _AskSpy()), UiSession(_Cfg(), _AskSpy())
    assert a._shared is b._shared
    injected = UiSession(_Cfg(), _AskSpy(), uia_driver=object())
    assert injected._shared is not a._shared


def test_close_window_without_target_closes_the_root_itself():
    session, driver, _ = _make_session(_BIG_TREE)
    root_id = _observed_root_id(session)
    out = ComputerUseInteractWithWindowTool(session).run(root=root_id, action="close_window")
    assert out.startswith("ok: close_window") and ("r1", None, "close_window", None) in driver.acts
    assert session.lookup(root_id) is None


def test_only_close_window_may_omit_the_target():
    session, driver, _ = _make_session(_BIG_TREE)
    root_id = _observed_root_id(session)
    out = ComputerUseInteractWithWindowTool(session).run(root=root_id, action="click")
    assert out.startswith("Error") and driver.acts == []


def test_closing_via_an_element_does_not_outline_a_closed_root(monkeypatch):
    """Outlining a closing window blocked 82 s and ended in a COM error."""
    session, driver, _ = _make_session(_BIG_TREE)
    root_id = _observed_root_id(session)
    obs = _observe(session, root_id)
    real_act = driver.act

    def act_and_close(root, el, action, value=None):
        real_act(root, el, action, value)
        driver._roots.clear()
        monkeypatch.setattr(driver, "outline", lambda *a, **k: pytest.fail("outlined a closed root"))

    monkeypatch.setattr(driver, "act", act_and_close)
    out = ComputerUseInteractWithWindowTool(session).run(root=root_id, target=0, action="close_window", obs=obs)
    assert out.startswith("ok: close_window") and "closed" in out
