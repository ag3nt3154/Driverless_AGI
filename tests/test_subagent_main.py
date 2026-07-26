"""tests/test_subagent_main.py — Unit tests for tools/subagent_main.py."""
from __future__ import annotations

from pathlib import Path

from tools.subagent_main import _ensure_handoff, _HANDOFF_RETRY_PROMPT


class _FakeLoop:
    """Minimal AgentLoop test double: tracks .run() calls, optionally writes handoff.

    ``write_on_call`` is 1-indexed against the *cumulative* ``run_calls`` count for this
    instance (including any call the test makes directly before invoking
    ``_ensure_handoff``), not against calls made through ``_ensure_handoff`` alone. Tests
    that pre-seed a call (e.g. ``loop.run("original task")``) before calling
    ``_ensure_handoff`` must account for that call when choosing ``write_on_call``.
    """

    def __init__(self, handoff_path: Path, write_on_call: int | None = None, messages=None):
        self.handoff_path = handoff_path
        self.write_on_call = write_on_call
        self.run_calls: list[str] = []
        self._messages = messages if messages is not None else []
        self.finish_calls = 0

    def run(self, task: str) -> None:
        self.run_calls.append(task)
        if self.write_on_call is not None and len(self.run_calls) == self.write_on_call:
            self.handoff_path.parent.mkdir(parents=True, exist_ok=True)
            self.handoff_path.write_text("# Handoff\n\nreal report", encoding="utf-8")

    def finish(self) -> None:
        self.finish_calls += 1


def _flag_path(handoff_path: Path) -> Path:
    return handoff_path.with_name(f"{handoff_path.stem}_unverified.flag")


def test_handoff_already_exists_after_first_call_no_retry(tmp_path):
    handoff_path = tmp_path / "worker_abc123.md"
    loop = _FakeLoop(handoff_path, write_on_call=1)

    # Simulate: first loop.run() already happened and wrote the handoff.
    loop.run("original task")
    assert len(loop.run_calls) == 1

    _ensure_handoff(loop, handoff_path)

    assert len(loop.run_calls) == 1  # no retry triggered
    assert not _flag_path(handoff_path).exists()


def test_handoff_absent_then_present_after_retry(tmp_path):
    handoff_path = tmp_path / "worker_abc123.md"
    loop = _FakeLoop(handoff_path, write_on_call=2)

    loop.run("original task")
    assert len(loop.run_calls) == 1
    assert not handoff_path.exists()

    _ensure_handoff(loop, handoff_path)

    assert len(loop.run_calls) == 2
    assert handoff_path.exists()
    assert not _flag_path(handoff_path).exists()
    assert "write_handoff" in loop.run_calls[1]
    assert loop.run_calls[1] == _HANDOFF_RETRY_PROMPT


def test_handoff_absent_after_both_calls_scrapes_and_flags(tmp_path):
    handoff_path = tmp_path / "worker_abc123.md"
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "final report text"},
    ]
    loop = _FakeLoop(handoff_path, write_on_call=None, messages=messages)

    loop.run("original task")
    assert len(loop.run_calls) == 1

    _ensure_handoff(loop, handoff_path)

    assert len(loop.run_calls) == 2
    assert handoff_path.exists()
    content = handoff_path.read_text(encoding="utf-8")
    assert content == "# Handoff\n\nfinal report text"
    assert _flag_path(handoff_path).exists()


def test_handoff_absent_no_usable_text_falls_back(tmp_path):
    handoff_path = tmp_path / "worker_abc123.md"
    loop = _FakeLoop(handoff_path, write_on_call=None, messages=[])

    loop.run("original task")
    _ensure_handoff(loop, handoff_path)

    content = handoff_path.read_text(encoding="utf-8")
    assert content == "# Handoff\n\n(subagent produced no output)"
    assert _flag_path(handoff_path).exists()


def test_retry_call_exception_is_caught_and_emits_error(tmp_path, capsys):
    handoff_path = tmp_path / "worker_abc123.md"

    class _RaisingLoop(_FakeLoop):
        def run(self, task: str) -> None:
            self.run_calls.append(task)
            if len(self.run_calls) == 2:
                raise RuntimeError("boom")

    loop = _RaisingLoop(handoff_path, write_on_call=None, messages=[])
    loop.run("original task")

    _ensure_handoff(loop, handoff_path)

    assert len(loop.run_calls) == 2
    out = capsys.readouterr().out
    assert "error" in out
    assert "boom" in out
    assert "handoff_retry" in out  # phase marker distinguishes retry-path errors
    # Since retry raised, no second successful run wrote the handoff — scrape path still runs.
    assert handoff_path.exists()
    assert _flag_path(handoff_path).exists()


def test_pipe_mode_finish_runs_after_handoff_retry(tmp_path, monkeypatch):
    """loop.finish() must run only after _ensure_handoff's possible retry loop.run().

    Regression test: previously loop.finish() (which snapshots messages/tokens/cost
    for the persisted session record) ran before _ensure_handoff's retry, silently
    dropping the retry's cost/tokens/tool-calls/messages from the session JSONL.
    """
    import tools.subagent_main as subagent_main

    call_order: list[str] = []
    handoff_path = tmp_path / "worker_abc123.md"

    class _OrderedFakeLoop(_FakeLoop):
        def run(self, task: str) -> None:
            call_order.append(f"run:{task}")
            super().run(task)
            # Simulate the subagent forgetting to call write_handoff on the primary
            # run, but succeeding on the retry (write_on_call=2).

        def finish(self) -> None:
            call_order.append("finish")
            super().finish()

    fake_loop = _OrderedFakeLoop(handoff_path, write_on_call=2)

    task_file = tmp_path / "task.txt"
    task_file.write_text("do the thing", encoding="utf-8")

    monkeypatch.setattr(
        subagent_main, "resolve_model_config", lambda model, project_path: subagent_main.AgentConfig()
    )
    monkeypatch.setattr(
        subagent_main, "build_subagent_registry", lambda **kwargs: object()
    )
    monkeypatch.setattr(
        subagent_main, "_build_subagent_system_prompt", lambda subagent_type, project_path: "sys"
    )
    monkeypatch.setattr(subagent_main, "AgentLoop", lambda **kwargs: fake_loop)

    subagent_main.run_subagent_pipe_mode(
        subagent_type="worker",
        task_file=str(task_file),
        handoff=str(handoff_path),
        project=str(tmp_path),
        model=None,
    )

    assert call_order == ["run:do the thing", f"run:{_HANDOFF_RETRY_PROMPT}", "finish"]
    assert handoff_path.exists()
