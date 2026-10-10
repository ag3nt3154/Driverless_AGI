from __future__ import annotations

import threading
from types import SimpleNamespace

from PySide6.QtWidgets import QMainWindow

from agent.board_client import BoardError
from pyside_gui.board_controller import BoardController
from pyside_gui.bridge import AgentBridge
from pyside_gui.sidebars.message_board import MessageBoardView


class FakeClient:
    def __init__(self, posts=()):
        self._posts = list(posts)
        self.closed = threading.Event()

    def posts(self, limit=50):
        return self._posts

    def close(self):
        self.closed.set()


def _window(qtbot):
    window = QMainWindow()
    qtbot.addWidget(window)
    window._bridge = AgentBridge()
    window._config = SimpleNamespace(services={})
    window._board_runtime = None
    window._board_session = None
    window._board_listener = None
    window._conversation = SimpleNamespace(append_emote=lambda *_args: None)
    view = MessageBoardView()
    window._left_sidebar = SimpleNamespace(
        board_view=view, open_file=lambda *_args: None,
    )
    return window


def test_late_readiness_after_close_only_closes_client(qtbot):
    window = _window(qtbot)
    controller = BoardController(window)
    client = FakeClient()
    class Temp:
        closed = 0
        def close(self):
            self.closed += 1
    temp = Temp()
    runtime = SimpleNamespace(client=client, session=object(), temp=temp)
    controller.close()
    window._bridge.board_ready.emit(runtime)
    qtbot.waitUntil(client.closed.is_set)
    qtbot.waitUntil(lambda: temp.closed == 1)
    assert window._board_runtime is None
    assert window._board_listener is None


def test_snapshot_starts_stream_after_maximum_id(qtbot, monkeypatch):
    window = _window(qtbot)
    controller = BoardController(window)
    def post(post_id):
        return {
            "id": post_id, "author": "main_12345678", "text": "x", "meme": None,
            "reply_to": None, "attachments": [], "created_at": "2026-10-09T00:00:00Z",
        }

    client = FakeClient([post(5), post(8)])
    controller.runtime = SimpleNamespace(
        client=client, session=SimpleNamespace(handle="main_12345678"),
    )
    created = []

    class Listener:
        def __init__(self, client, after, on_post, on_status):
            created.append((client, after, on_post, on_status))

        def start(self):
            pass

        def stop(self):
            pass

        def join(self):
            pass

    monkeypatch.setattr("pyside_gui.board_controller.StreamListener", Listener)
    controller._load_snapshot()
    assert created[0][0] is client
    assert created[0][1] == 8
    controller.close()


def test_close_during_listener_construction_prevents_late_start(qtbot, monkeypatch):
    window = _window(qtbot)
    controller = BoardController(window)
    client = FakeClient([])
    controller.runtime = SimpleNamespace(client=client)
    constructing = threading.Event()
    release = threading.Event()
    started = threading.Event()

    class Listener:
        def __init__(self, *_args):
            constructing.set()
            release.wait(2)

        def start(self):
            started.set()

    monkeypatch.setattr("pyside_gui.board_controller.StreamListener", Listener)
    worker = threading.Thread(target=controller._load_snapshot)
    worker.start()
    assert constructing.wait(1)
    controller.close()
    release.set()
    worker.join(1)
    assert not started.is_set()
    assert controller.listener is None


def test_close_waits_off_thread_for_active_work_before_client_close(qtbot):
    window = _window(qtbot)
    controller = BoardController(window)
    client = FakeClient()
    controller.runtime = SimpleNamespace(client=client)
    entered = threading.Event()
    release = threading.Event()

    def work():
        entered.set()
        release.wait(2)

    controller._run_worker(work, "test-board-work")
    assert entered.wait(1)
    controller.close()
    assert not client.closed.wait(0.05)
    release.set()
    assert client.closed.wait(1)


class _Listener:
    created: list = []

    def __init__(self, client, after, on_post, on_status):
        _Listener.created.append((client, after))

    def start(self):
        pass

    def stop(self):
        pass

    def join(self):
        pass


class FlakyClient(FakeClient):
    def __init__(self, failures):
        super().__init__([])
        self.failures = failures
        self.calls = 0
        self.called = threading.Event()

    def posts(self, limit=50):
        self.calls += 1
        self.called.set()
        if self.calls <= self.failures:
            raise BoardError("UNAVAILABLE", "service starting")
        return self._posts


def test_snapshot_failure_is_retried_with_backoff(qtbot, monkeypatch):
    window = _window(qtbot)
    controller = BoardController(window)
    client = FlakyClient(failures=1)
    controller.runtime = SimpleNamespace(client=client)
    monkeypatch.setattr("pyside_gui.board_controller._BACKOFF", (0.01,))
    _Listener.created = []
    monkeypatch.setattr("pyside_gui.board_controller.StreamListener", _Listener)
    statuses = []
    window._bridge.board_status.connect(statuses.append)
    controller._load_snapshot()
    assert client.calls == 2
    assert _Listener.created == [(client, 0)]
    assert any("service starting" in status for status in statuses)
    controller.close()


def test_close_during_snapshot_backoff_stops_retry(qtbot, monkeypatch):
    window = _window(qtbot)
    controller = BoardController(window)
    client = FlakyClient(failures=100)
    controller.runtime = SimpleNamespace(client=client)
    monkeypatch.setattr("pyside_gui.board_controller._BACKOFF", (30.0,))
    _Listener.created = []
    monkeypatch.setattr("pyside_gui.board_controller.StreamListener", _Listener)
    view = window._left_sidebar.board_view
    worker = threading.Thread(target=controller._load_snapshot)
    worker.start()
    assert client.called.wait(1)
    qtbot.waitUntil(lambda: "service starting" in view._status.text())
    controller.close()
    worker.join(1)
    assert not worker.is_alive()
    assert client.calls == 1
    assert _Listener.created == []
    assert controller.listener is None


def _snapshot_post(post_id):
    return {
        "id": post_id, "author": "main_12345678", "text": "x", "meme": None,
        "reply_to": None, "attachments": [], "created_at": "2026-10-09T00:00:00Z",
    }


def test_malformed_snapshot_items_are_skipped(qtbot, monkeypatch):
    window = _window(qtbot)
    controller = BoardController(window)
    client = FakeClient(["x", {"id": "7"}, {"id": True}, _snapshot_post(8)])
    controller.runtime = SimpleNamespace(
        client=client, session=SimpleNamespace(handle="main_12345678"),
    )
    _Listener.created = []
    monkeypatch.setattr("pyside_gui.board_controller.StreamListener", _Listener)
    emitted = []
    window._bridge.board_post.connect(emitted.append)
    controller._load_snapshot()
    assert [post["id"] for post in emitted] == [8]
    assert _Listener.created == [(client, 8)]
    controller.close()


def test_non_list_snapshot_is_empty_with_status(qtbot, monkeypatch):
    window = _window(qtbot)
    controller = BoardController(window)
    client = FakeClient()
    client._posts = {"posts": []}
    controller.runtime = SimpleNamespace(client=client)
    _Listener.created = []
    monkeypatch.setattr("pyside_gui.board_controller.StreamListener", _Listener)
    controller._load_snapshot()
    assert _Listener.created == [(client, 0)]
    assert "snapshot" in window._left_sidebar.board_view._status.text()
    controller.close()


def test_non_dict_post_signal_is_ignored(qtbot):
    window = _window(qtbot)
    emotes = []
    window._conversation = SimpleNamespace(append_emote=lambda *args: emotes.append(args))
    controller = BoardController(window)
    controller.runtime = SimpleNamespace(session=SimpleNamespace(handle="main_12345678"))
    controller._on_post("not a post")
    controller._on_post(None)
    assert emotes == []
    assert window._left_sidebar.board_view._cards == {}


def test_main_agent_meme_uses_view_meme_map_without_rescanning(qtbot, monkeypatch, tmp_path):
    window = _window(qtbot)
    emotes = []
    window._conversation = SimpleNamespace(append_emote=lambda *args: emotes.append(args))
    controller = BoardController(window)
    meme = tmp_path / "wave.png"
    window._left_sidebar.board_view._memes = {"wave": meme}

    def no_scan(_root):
        raise AssertionError("memes rescanned per post")

    monkeypatch.setattr("pyside_gui.board_controller._scan_memes", no_scan, raising=False)
    monkeypatch.setattr("pyside_gui.sidebars.message_board._scan_memes", no_scan)
    monkeypatch.setattr("tools.board._board._scan_memes", no_scan)
    controller.runtime = SimpleNamespace(session=SimpleNamespace(handle="main_12345678"))
    controller._on_post({
        "id": 1, "author": "main_12345678", "text": "hey", "meme": "wave",
        "reply_to": None, "attachments": [], "created_at": "2026-10-09T00:00:00Z",
    })
    assert emotes == [("wave", str(meme), "hey", "2026-10-09T00:00:00Z")]


class SwitchClient:
    """Fake BoardClient for a board the controller switches to."""
    instances = []

    def __init__(self, url, token=None, timeout=10.0, health=None, posts=()):
        self.url, self.token, self.timeout = url, token, timeout
        self.health_result = health if health is not None else {"version": 1}
        self._posts = list(posts)
        self.registered = []
        self.closed = threading.Event()
        SwitchClient.instances.append(self)

    def health(self):
        if isinstance(self.health_result, BaseException):
            raise self.health_result
        return self.health_result

    def register(self, handle, kind, display_name=None, host=None):
        self.registered.append((handle, kind))

    def posts(self, limit=50, **_kwargs):
        return self._posts

    def close(self):
        self.closed.set()


def _post(post_id):
    return {"id": post_id, "author": "main_12345678", "text": f"p{post_id}", "meme": None,
            "reply_to": None, "attachments": [], "created_at": "2026-10-09T00:00:00Z"}


def _switchable(qtbot, monkeypatch, tmp_path, client_factory):
    from agent.board_client import BoardSession

    monkeypatch.setattr("pyside_gui.board_controller.STATE_DIR", tmp_path)
    monkeypatch.setattr("pyside_gui.board_controller.BoardClient", client_factory)
    listeners = []

    class Listener:
        def __init__(self, client, after, on_post, on_status):
            self.client, self.after = client, after
            self.stopped = False
            self.joined = False
            listeners.append(self)

        def start(self):
            pass

        def stop(self):
            self.stopped = True

        def join(self):
            self.joined = True

    monkeypatch.setattr("pyside_gui.board_controller.StreamListener", Listener)
    window = _window(qtbot)
    controller = BoardController(window)
    old = FakeClient()
    main, helper = BoardSession(old, "main_12345678"), BoardSession(old, "helper_abcdef12")
    controller.sessions = [main, helper]
    controller.runtime = SimpleNamespace(client=old, session=main, url="http://127.0.0.1:8765",
                                         central_url="http://central:8765")
    old_listener = Listener(old, 0, None, None)
    controller.listener = old_listener
    window._left_sidebar.board_view.add_post(_post(99))
    return window, controller, old, old_listener, listeners


def test_switch_repoints_every_session_listener_and_view(qtbot, monkeypatch, tmp_path):
    SwitchClient.instances = []
    factory = lambda url, token=None, timeout=10.0: SwitchClient(url, token, timeout,
                                                                 posts=[_post(1)])
    window, controller, old, old_listener, listeners = _switchable(
        qtbot, monkeypatch, tmp_path, factory)
    view = window._left_sidebar.board_view
    controller.switch("http://central:8765")
    qtbot.waitUntil(lambda: controller.runtime.url == "http://central:8765")
    new = SwitchClient.instances[0]
    assert [session.client for session in controller.sessions] == [new, new]
    assert controller.runtime.session is controller.sessions[0]
    assert window._board_session is controller.sessions[0]
    assert ("helper_abcdef12", "agent") in new.registered
    assert old_listener.stopped
    qtbot.waitUntil(old.closed.is_set)
    qtbot.waitUntil(lambda: bool(listeners[1:]))
    assert listeners[-1].client is new and listeners[-1].after == 1
    qtbot.waitUntil(lambda: 1 in view._seen)
    assert 99 not in view._seen
    assert view._url_label.text() == "http://central:8765" and view._fallback.isHidden()
    assert not controller._central_timer.isActive()


def test_switch_auth_failure_asks_for_token_and_keeps_board(qtbot, monkeypatch, tmp_path):
    SwitchClient.instances = []
    factory = lambda url, token=None, timeout=10.0: SwitchClient(
        url, token, timeout, health=BoardError("UNAUTHORIZED", "token required"))
    window, controller, old, old_listener, _ = _switchable(qtbot, monkeypatch, tmp_path, factory)
    asked = []
    monkeypatch.setattr(window._left_sidebar.board_view, "ask_token", asked.append)
    controller.switch("http://central:8765")
    qtbot.waitUntil(lambda: asked == ["http://central:8765"])
    assert controller.runtime.client is old and not old_listener.stopped
    assert all(session.client is old for session in controller.sessions)
    qtbot.waitUntil(SwitchClient.instances[0].closed.is_set)


def test_central_back_auto_switches_and_closes_temp(qtbot, monkeypatch, tmp_path):
    SwitchClient.instances = []
    outcomes = [BoardError("UNREACHABLE", "down"), {"version": 1}, {"version": 1}]
    factory = lambda url, token=None, timeout=10.0: SwitchClient(
        url, token, timeout, health=outcomes.pop(0))
    window, controller, old, old_listener, _ = _switchable(
        qtbot, monkeypatch, tmp_path, factory)
    order = []
    class Temp:
        def close(self):
            order.append(("temp-close", old_listener.stopped, old_listener.joined))
    old_runtime = controller.runtime
    old_runtime.temp = Temp()
    old_runtime.central_url = "http://central:8765"
    old_listener = controller.listener
    old_close = old.close
    old.close = lambda: (order.append(("client-close", old_listener.stopped)), old_close())
    monkeypatch.setattr("pyside_gui.board_controller.resolve_token", lambda: "central-token")
    view = window._left_sidebar.board_view
    controller._probe_central()
    qtbot.wait(100)
    assert view._central_back.isHidden()
    controller._probe_central()
    qtbot.waitUntil(lambda: controller.runtime.url == "http://central:8765")
    qtbot.waitUntil(lambda: any(entry[0] == "temp-close" for entry in order))
    assert SwitchClient.instances[-1].token == "central-token"
    assert order == [("client-close", True), ("temp-close", True, True)]
    assert view._status.text() == (
        "Switched to central board http://central:8765; temp board posts were discarded."
    )
    assert old_runtime.temp is not None
    controller.close()


def test_central_auth_failure_asks_token_once_and_keeps_temp(qtbot, monkeypatch, tmp_path):
    SwitchClient.instances = []
    factory = lambda url, token=None, timeout=10.0: SwitchClient(
        url, token, timeout, health=BoardError("UNAUTHORIZED", "token required"))
    window, controller, old, old_listener, _ = _switchable(
        qtbot, monkeypatch, tmp_path, factory)
    asks = []
    monkeypatch.setattr(window._left_sidebar.board_view, "ask_token", asks.append)
    class Temp:
        closed = 0
        def close(self):
            self.closed += 1
    temp = Temp()
    controller.runtime.temp = temp
    monkeypatch.setattr("pyside_gui.board_controller.resolve_token", lambda: None)
    controller._on_central_state(("http://central:8765", True))
    qtbot.waitUntil(lambda: asks == ["http://central:8765"])
    controller._on_central_state(("http://central:8765", True))
    qtbot.wait(50)
    assert len(SwitchClient.instances) == 1
    assert controller.runtime.client is old and not old_listener.stopped
    assert temp.closed == 0
    controller.close()


def test_overlapping_switches_are_serialized_and_manual_retry_still_works(
    qtbot, monkeypatch, tmp_path,
):
    from threading import Event

    SwitchClient.instances = []
    entered, release = Event(), Event()
    checks = []

    class DeferredClient(SwitchClient):
        def health(self):
            checks.append(self)
            if len(SwitchClient.instances) == 1:
                entered.set()
                assert release.wait(2)
                raise BoardError("UNAUTHORIZED", "token required")
            return {"version": 1}

    def factory(url, token=None, timeout=10.0):
        return DeferredClient(url, token, timeout)

    window, controller, old, old_listener, _ = _switchable(
        qtbot, monkeypatch, tmp_path, factory)
    class Temp:
        closed = 0
        def close(self):
            self.closed += 1
    temp = Temp()
    old_runtime = controller.runtime
    old_runtime.temp = temp
    old_runtime.central_url = "http://central:8765"
    asks = []
    monkeypatch.setattr(window._left_sidebar.board_view, "ask_token", asks.append)
    monkeypatch.setattr("pyside_gui.board_controller.resolve_token", lambda: None)

    controller._on_central_state(("http://central:8765", True))
    assert entered.wait(1)
    controller.switch("http://manual:8765", "manual-token")
    controller._on_central_state(("http://central:8765", True))
    assert len(SwitchClient.instances) == 1
    assert checks == [SwitchClient.instances[0]]
    assert controller.runtime is old_runtime

    release.set()
    qtbot.waitUntil(lambda: asks == ["http://central:8765"])
    assert controller.runtime is old_runtime and old_listener.stopped is False
    assert temp.closed == 0

    controller.switch("http://central:8765", "manual-token")
    qtbot.waitUntil(lambda: controller.runtime.client is SwitchClient.instances[1])
    qtbot.waitUntil(lambda: temp.closed == 1)
    assert len(SwitchClient.instances) == 2


def test_close_on_temp_closes_temp_board_after_listener_joins(qtbot):
    window = _window(qtbot)
    controller = BoardController(window)
    order = []
    class Temp:
        def close(self):
            order.append("temp")
    class Listener:
        def stop(self):
            order.append("stop")
        def join(self):
            order.append("join")
    client = FakeClient()
    runtime = SimpleNamespace(client=client, temp=Temp())
    controller.runtime = runtime
    controller.listener = Listener()
    controller.close()
    qtbot.waitUntil(lambda: "temp" in order)
    assert order.index("join") < order.index("temp")


def test_board_url_normalisation():
    from pyside_gui.sidebars.message_board import board_url

    assert board_url("192.168.1.5:8765") == "http://192.168.1.5:8765"
    assert board_url(" https://board.lan/ ") == "https://board.lan"
    assert board_url("http://[::1]:9000") == "http://[::1]:9000"
    for bad in ("", "ftp://x", "http://u:p@h:1", "http://h:1/path", "http://h:1?q=1",
                "http://h:99999"):
        assert board_url(bad) is None, bad


def test_fallback_badge_shows_central_address(qtbot):
    view = MessageBoardView()
    qtbot.addWidget(view)
    view.set_connection("http://127.0.0.1:8765", "http://central:8765")
    assert not view._fallback.isHidden()
    assert "central:8765" in view._url_label.toolTip()
    view.set_connection("http://central:8765", None)
    assert view._fallback.isHidden()


def test_each_agent_meme_renders_in_its_own_conversation(qtbot, tmp_path):
    window = _window(qtbot)
    main_emotes, helper_emotes = [], []
    window._sessions = [
        SimpleNamespace(_board_session=SimpleNamespace(handle="main_12345678"),
                        _conversation=SimpleNamespace(
                            append_emote=lambda *args: main_emotes.append(args))),
        SimpleNamespace(_board_session=SimpleNamespace(handle="helper_abcdef12"),
                        _conversation=SimpleNamespace(
                            append_emote=lambda *args: helper_emotes.append(args))),
    ]
    controller = BoardController(window)
    window._left_sidebar.board_view._memes = {"wave": tmp_path / "wave.png"}
    controller.runtime = SimpleNamespace(session=SimpleNamespace(handle="main_12345678"))
    controller._on_post({
        "id": 1, "author": "helper_abcdef12", "text": "hi", "meme": "wave",
        "reply_to": None, "attachments": [], "created_at": "2026-10-09T00:00:00Z",
    })
    assert main_emotes == [] and [args[0] for args in helper_emotes] == ["wave"]
