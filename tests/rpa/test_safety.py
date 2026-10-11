"""tests/rpa/test_safety.py — per-app permission and sensitive-action confirmation (D5)."""
from __future__ import annotations

import pytest

from rpa.model import Element, Root
from rpa.safety import SafetyDenied, SafetyGate, is_sensitive


def make_root(app: str = "notepad.exe") -> Root:
    return Root(id="r1", kind="window", title="Untitled", pid=123, url=None, app=app)


def make_element(name: str = "OK", role: str = "Button") -> Element:
    return Element(
        index=0,
        role=role,
        name=name,
        automation_id=None,
        bbox=(0, 0, 10, 10),
        value=None,
        secure=False,
        interactive=True,
    )


class AskSpy:
    """Records calls; returns a fixed answer (or raises) on each call."""

    def __init__(self, answer: str | None = None, raises: bool = False):
        self.calls: list[tuple[str, list[dict]]] = []
        self.answer = answer
        self.raises = raises

    def __call__(self, question: str, options: list[dict]) -> str:
        self.calls.append((question, options))
        if self.raises:
            raise RuntimeError("ask failed")
        return self.answer


# --- is_sensitive -----------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Send", True),
        ("Save", False),
        ("Repost", False),
        ("Post comment", True),
        ("Sign  out", True),  # flexible whitespace
        ("Log out", True),
        ("Export CSV", False),
        ("Delete item", True),
        ("Confirm", True),
        ("Purchase now", True),
    ],
)
def test_is_sensitive_word_boundaries(name, expected):
    assert is_sensitive(make_element(name=name)) is expected


# --- autonomous / no-ask denies without calling ask -------------------------


def test_autonomous_denies_app_check_without_calling_ask():
    spy = AskSpy(answer="Allow")
    gate = SafetyGate(ask=spy, autonomous=True)
    with pytest.raises(SafetyDenied):
        gate.check_app(make_root())
    assert spy.calls == []


def test_autonomous_denies_action_check_without_calling_ask():
    spy = AskSpy(answer="Allow once")
    gate = SafetyGate(ask=spy, autonomous=True)
    with pytest.raises(SafetyDenied):
        gate.check_action(make_root(), make_element(name="Send"), "click")
    assert spy.calls == []


def test_ask_none_denies_app_check():
    gate = SafetyGate(ask=None, autonomous=False)
    with pytest.raises(SafetyDenied):
        gate.check_app(make_root())


def test_ask_none_denies_action_check():
    gate = SafetyGate(ask=None, autonomous=False)
    with pytest.raises(SafetyDenied):
        gate.check_action(make_root(), make_element(name="Send"), "click")


# --- check_action: sensitive vs non-sensitive -------------------------------


def test_send_click_asks():
    spy = AskSpy(answer="Allow once")
    gate = SafetyGate(ask=spy, autonomous=False)
    gate.check_action(make_root(), make_element(name="Send"), "click")
    assert len(spy.calls) == 1


def test_save_click_does_not_ask():
    spy = AskSpy(answer="Allow once")
    gate = SafetyGate(ask=spy, autonomous=False)
    gate.check_action(make_root(), make_element(name="Save"), "click")
    assert spy.calls == []


def test_non_gated_action_does_not_ask_even_if_sensitive_name():
    spy = AskSpy(answer="Allow once")
    gate = SafetyGate(ask=spy, autonomous=False)
    gate.check_action(make_root(), make_element(name="Send"), "scroll")
    assert spy.calls == []


def test_sensitive_flag_forces_ask_on_non_sensitive_name():
    spy = AskSpy(answer="Allow once")
    gate = SafetyGate(ask=spy, autonomous=False)
    gate.check_action(make_root(), make_element(name="Save"), "click", sensitive_flag=True)
    assert len(spy.calls) == 1


# --- deny answer and free-text both deny; not remembered -------------------


def test_action_deny_answer_denies():
    spy = AskSpy(answer="Deny")
    gate = SafetyGate(ask=spy, autonomous=False)
    with pytest.raises(SafetyDenied):
        gate.check_action(make_root(), make_element(name="Send"), "click")


def test_action_free_text_answer_denies():
    spy = AskSpy(answer="maybe later")
    gate = SafetyGate(ask=spy, autonomous=False)
    with pytest.raises(SafetyDenied):
        gate.check_action(make_root(), make_element(name="Send"), "click")


def test_action_empty_answer_denies():
    spy = AskSpy(answer="")
    gate = SafetyGate(ask=spy, autonomous=False)
    with pytest.raises(SafetyDenied):
        gate.check_action(make_root(), make_element(name="Send"), "click")


def test_action_exception_from_ask_denies():
    spy = AskSpy(raises=True)
    gate = SafetyGate(ask=spy, autonomous=False)
    with pytest.raises(SafetyDenied):
        gate.check_action(make_root(), make_element(name="Send"), "click")


def test_action_confirmation_not_remembered():
    spy = AskSpy(answer="Allow once")
    gate = SafetyGate(ask=spy, autonomous=False)
    gate.check_action(make_root(), make_element(name="Send"), "click")
    gate.check_action(make_root(), make_element(name="Send"), "click")
    assert len(spy.calls) == 2


# --- check_app: asked once per app per gate, deny not remembered -----------


def test_app_permission_asked_once_per_app():
    spy = AskSpy(answer="Allow")
    gate = SafetyGate(ask=spy, autonomous=False)
    gate.check_app(make_root(app="notepad.exe"))
    gate.check_app(make_root(app="notepad.exe"))
    assert len(spy.calls) == 1


def test_app_permission_asked_separately_per_app():
    spy = AskSpy(answer="Allow")
    gate = SafetyGate(ask=spy, autonomous=False)
    gate.check_app(make_root(app="notepad.exe"))
    gate.check_app(make_root(app="firefox"))
    assert len(spy.calls) == 2


def test_app_permission_deny_answer_denies():
    spy = AskSpy(answer="Deny")
    gate = SafetyGate(ask=spy, autonomous=False)
    with pytest.raises(SafetyDenied):
        gate.check_app(make_root())


def test_app_permission_denial_not_remembered():
    spy = AskSpy(answer="Deny")
    gate = SafetyGate(ask=spy, autonomous=False)
    with pytest.raises(SafetyDenied):
        gate.check_app(make_root())
    with pytest.raises(SafetyDenied):
        gate.check_app(make_root())
    assert len(spy.calls) == 2


def test_app_permission_can_allow_after_prior_denial():
    spy = AskSpy(answer="Deny")
    gate = SafetyGate(ask=spy, autonomous=False)
    with pytest.raises(SafetyDenied):
        gate.check_app(make_root())
    spy.answer = "Allow"
    gate.check_app(make_root())  # does not raise now
    assert len(spy.calls) == 2


# --- options never contain "recommended" ------------------------------------


def test_app_options_never_contain_recommended():
    spy = AskSpy(answer="Allow")
    gate = SafetyGate(ask=spy, autonomous=False)
    gate.check_app(make_root())
    _, options = spy.calls[0]
    assert all("recommended" not in opt for opt in options)
    assert {opt["label"] for opt in options} == {"Allow", "Deny"}


def test_action_options_never_contain_recommended():
    spy = AskSpy(answer="Allow once")
    gate = SafetyGate(ask=spy, autonomous=False)
    gate.check_action(make_root(), make_element(name="Send"), "click")
    _, options = spy.calls[0]
    assert all("recommended" not in opt for opt in options)
    assert {opt["label"] for opt in options} == {"Allow once", "Deny"}


@pytest.mark.parametrize("answer", ["allowed", "Allowed.", "yes", "OK", "approve", " allow once "])
def test_clear_yes_words_count_as_allow(answer):
    gate = SafetyGate(ask=lambda q, o: answer, autonomous=False)
    gate.check_app(Root(id="w", kind="window", title="T", pid=1, url=None, app="a.exe"))


@pytest.mark.parametrize("answer", ["Proceed with your best judgment", "deny", "no", "allow?", "maybe"])
def test_other_free_text_still_denies(answer):
    gate = SafetyGate(ask=lambda q, o: answer, autonomous=False)
    with pytest.raises(SafetyDenied):
        gate.check_app(Root(id="w", kind="window", title="T", pid=1, url=None, app="a.exe"))
