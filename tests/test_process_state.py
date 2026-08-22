from __future__ import annotations

from pathlib import Path

from agent.expression_assets import ImageAsset, TextFallback
from agent.process_state import ProcessStateController, ProcessSnapshot


class _FakeLibrary:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.assets = {
            "idle": ImageAsset("idle", Path("idle.gif")),
            "thinking": ImageAsset("thinking", Path("thinking.gif")),
            "tool:read": ImageAsset("tool:read", Path("read.gif")),
            "tool": ImageAsset("tool", Path("tool.gif")),
            "paused": TextFallback(Path("default.md"), "paused fallback", "PAUSED"),
            "error": TextFallback(Path("default.md"), "error fallback", "ERROR"),
        }

    def resolve(self, state: str):
        self.calls.append(state)
        return self.assets.get(state, self.assets["tool"])


def test_process_state_lifecycle_publishes_expected_snapshots() -> None:
    library = _FakeLibrary()
    seen: list[ProcessSnapshot] = []
    controller = ProcessStateController(library, on_change=seen.append)

    idle = controller.idle()
    thinking = controller.thinking()
    working = controller.tool_started("read")
    done = controller.tool_ended()

    assert idle == ProcessSnapshot("idle", ImageAsset("idle", Path("idle.gif")))
    assert thinking == ProcessSnapshot(
        "thinking", ImageAsset("thinking", Path("thinking.gif"))
    )
    assert working == ProcessSnapshot(
        "tool:read", ImageAsset("tool:read", Path("read.gif"))
    )
    assert done == ProcessSnapshot(
        "thinking", ImageAsset("thinking", Path("thinking.gif"))
    )
    assert controller.snapshot == done
    assert library.calls == ["idle", "idle", "thinking", "tool:read", "thinking"]
    assert seen == [
        idle,
        thinking,
        working,
        done,
    ]


def test_process_state_skips_exact_duplicate_snapshots() -> None:
    library = _FakeLibrary()
    seen: list[ProcessSnapshot] = []
    controller = ProcessStateController(library, on_change=seen.append)

    idle = controller.idle()
    repeated_idle = controller.idle()
    tool = controller.tool_started("grep")
    repeated_tool = controller.tool_started("grep")

    assert repeated_idle is idle
    assert repeated_tool is tool
    assert seen == [
        ProcessSnapshot("idle", ImageAsset("idle", Path("idle.gif"))),
        ProcessSnapshot("tool:grep", ImageAsset("tool", Path("tool.gif"))),
    ]
    assert library.calls == ["idle", "idle", "idle", "tool:grep", "tool:grep"]


def test_process_state_preserves_pause_and_error_until_next_transition() -> None:
    library = _FakeLibrary()
    seen: list[ProcessSnapshot] = []
    controller = ProcessStateController(library, on_change=seen.append)

    paused = controller.paused()
    errored = controller.error()
    resumed = controller.thinking()

    assert paused == ProcessSnapshot(
        "paused",
        TextFallback(Path("default.md"), "paused fallback", "PAUSED"),
    )
    assert errored == ProcessSnapshot(
        "error",
        TextFallback(Path("default.md"), "error fallback", "ERROR"),
    )
    assert resumed == ProcessSnapshot(
        "thinking", ImageAsset("thinking", Path("thinking.gif"))
    )
    assert seen == [
        ProcessSnapshot("idle", ImageAsset("idle", Path("idle.gif"))),
        paused,
        errored,
        resumed,
    ]


def test_process_state_uses_generic_tool_asset_for_unknown_tool_names() -> None:
    library = _FakeLibrary()
    controller = ProcessStateController(library)

    snapshot = controller.tool_started("bash")

    assert snapshot == ProcessSnapshot(
        "tool:bash",
        ImageAsset("tool", Path("tool.gif")),
    )


def test_process_state_listener_receives_initial_idle_after_binding() -> None:
    library = _FakeLibrary()
    controller = ProcessStateController(library)
    seen: list[ProcessSnapshot] = []

    assert controller.snapshot == ProcessSnapshot("idle", ImageAsset("idle", Path("idle.gif")))

    controller.set_listener(seen.append)

    assert seen == [ProcessSnapshot("idle", ImageAsset("idle", Path("idle.gif")))]
