"""Tests for tools/subagent_api.py — the unified subagent function."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import json

import pytest

from agent import session_events as sev
from agent.parent_context import ParentContextProvider, ParentFork
from agent.session_log import SessionLog
from tools.subagent_api import SubagentResult, resume_subagent_by_pid, run_subagent


class TestSubagentResult:
    def test_dataclass_fields(self):
        r = SubagentResult(
            status="ok",
            handoff_text="done",
            handoff_path=Path("/tmp/h.md"),
            session_log_path=Path("/tmp/log"),
            pid=None,
        )
        assert r.status == "ok"
        assert r.handoff_text == "done"
        assert r.pid is None

    def test_is_ok_property(self):
        r = SubagentResult(
            status="ok", handoff_text="done",
            handoff_path=Path("/tmp/h.md"),
            session_log_path=Path("/tmp/log"),
            pid=None,
        )
        assert r.is_ok is True

    def test_is_ok_false_for_error(self):
        r = SubagentResult(
            status="error", handoff_text="",
            handoff_path=Path("/tmp/h.md"),
            session_log_path=Path("/tmp/log"),
            pid=None,
        )
        assert r.is_ok is False


class TestRunSubagent:
    def test_preset_loads_config_and_prompt(self, tmp_path):
        """run_subagent(preset=...) loads prompt.md and subagent_config.yaml."""
        preset_dir = tmp_path / ".dagi" / "subagents" / "explore_files"
        preset_dir.mkdir(parents=True)
        (preset_dir / "prompt.md").write_text("You are an explorer.", encoding="utf-8")
        (preset_dir / "subagent_config.yaml").write_text(
            "tools: [read, grep, find]\nmodel_tier: worker\n"
            "default_handoff_spec: structured report\n"
            "agents_md: [cwd]\n",
            encoding="utf-8",
        )
        handoff_file = tmp_path / ".dagi" / "handoffs" / "explore_files_abc.md"
        handoff_file.parent.mkdir(parents=True, exist_ok=True)
        handoff_file.write_text("# Handoff\nFound stuff.", encoding="utf-8")

        raw_result = {"status": "ok", "handoff": str(handoff_file)}
        with patch("tools.subagent_api._runner.run_subagent", return_value=raw_result):
            result = run_subagent(
                task="Map the auth module",
                preset="explore_files",
                project_path=tmp_path,
            )

        assert result.status == "ok"
        assert "Found stuff." in result.handoff_text

    def test_custom_prompt_and_tools_without_preset(self, tmp_path):
        """run_subagent() works without a preset when prompt + tools are explicit."""
        handoff_file = tmp_path / ".dagi" / "handoffs" / "custom_abc.md"
        handoff_file.parent.mkdir(parents=True, exist_ok=True)
        handoff_file.write_text("# Handoff\nCustom result.", encoding="utf-8")

        raw_result = {"status": "ok", "handoff": str(handoff_file)}
        with patch("tools.subagent_api._runner.run_subagent", return_value=raw_result):
            result = run_subagent(
                task="Analyze security",
                prompt="You are a security auditor.",
                tools=["read", "grep"],
                project_path=tmp_path,
            )

        assert result.status == "ok"
        assert "Custom result." in result.handoff_text

    def _make_preset(self, tmp_path: Path, name: str) -> None:
        """Create a minimal local preset so tests don't fall back to _DAGI_ROOT."""
        preset_dir = tmp_path / ".dagi" / "subagents" / name
        preset_dir.mkdir(parents=True, exist_ok=True)
        (preset_dir / "prompt.md").write_text(f"You are a {name} agent.", encoding="utf-8")
        (preset_dir / "subagent_config.yaml").write_text(
            "tools: [read]\nmodel_tier: worker\n"
            "default_handoff_spec: report\nagents_md: []\n",
            encoding="utf-8",
        )

    def test_error_status_returns_empty_handoff_text(self, tmp_path):
        self._make_preset(tmp_path, "explore_files")
        raw_result = {"status": "error", "message": "exited code 1"}
        with patch("tools.subagent_api._runner.run_subagent", return_value=raw_result):
            result = run_subagent(
                task="Fail", preset="explore_files", project_path=tmp_path,
            )

        assert result.status == "error"
        assert result.handoff_text == ""

    def test_timeout_returns_pid(self, tmp_path):
        self._make_preset(tmp_path, "worker")
        raw_result = {"status": "timeout", "pid": 9999}
        with patch("tools.subagent_api._runner.run_subagent", return_value=raw_result):
            result = run_subagent(
                task="Slow", preset="worker", project_path=tmp_path,
            )

        assert result.status == "timeout"
        assert result.pid == 9999

    def test_requires_preset_or_prompt(self, tmp_path):
        with pytest.raises(ValueError, match="preset.*prompt"):
            run_subagent(task="Do something", project_path=tmp_path)

    def test_explicit_tools_override_preset(self, tmp_path):
        """When both preset and explicit tools are given, explicit wins."""
        preset_dir = tmp_path / ".dagi" / "subagents" / "explore_files"
        preset_dir.mkdir(parents=True)
        (preset_dir / "prompt.md").write_text("Explorer.", encoding="utf-8")
        (preset_dir / "subagent_config.yaml").write_text(
            "tools: [read, grep, find]\nmodel_tier: worker\n"
            "default_handoff_spec: report\nagents_md: [cwd]\n",
            encoding="utf-8",
        )
        handoff_file = tmp_path / ".dagi" / "handoffs" / "test.md"
        handoff_file.parent.mkdir(parents=True, exist_ok=True)
        handoff_file.write_text("done", encoding="utf-8")

        raw_result = {"status": "ok", "handoff": str(handoff_file)}
        with patch("tools.subagent_api._runner.run_subagent", return_value=raw_result) as mock:
            run_subagent(
                task="Do it",
                preset="explore_files",
                tools=["read", "grep", "bash"],
                project_path=tmp_path,
            )

        call_kwargs = mock.call_args.kwargs
        # The --tools arg should contain the explicit override
        extra = call_kwargs.get("extra_argv", [])
        assert "--tools" in extra
        tools_idx = extra.index("--tools")
        assert "read,grep,bash" in extra[tools_idx + 1]

    def test_prompt_forwarded_via_system_prompt_file(self, tmp_path):
        """eff_prompt is written to a temp file and passed as --system-prompt-file."""
        preset_dir = tmp_path / ".dagi" / "subagents" / "explore_files"
        preset_dir.mkdir(parents=True)
        (preset_dir / "prompt.md").write_text("Preset prompt.", encoding="utf-8")
        (preset_dir / "subagent_config.yaml").write_text(
            "tools: [read]\nmodel_tier: worker\n"
            "default_handoff_spec: report\nagents_md: []\n",
            encoding="utf-8",
        )
        handoff_file = tmp_path / ".dagi" / "handoffs" / "test.md"
        handoff_file.parent.mkdir(parents=True, exist_ok=True)
        handoff_file.write_text("done", encoding="utf-8")

        raw_result = {"status": "ok", "handoff": str(handoff_file)}
        captured_prompt_content: list[str] = []

        def capture_and_return(*_args, **kwargs):
            extra = kwargs.get("extra_argv") or []
            if "--system-prompt-file" in extra:
                idx = extra.index("--system-prompt-file")
                captured_prompt_content.append(
                    Path(extra[idx + 1]).read_text(encoding="utf-8")
                )
            return raw_result

        with patch("tools.subagent_api._runner.run_subagent", side_effect=capture_and_return):
            run_subagent(
                task="Do it",
                preset="explore_files",
                prompt="Override prompt text.",
                project_path=tmp_path,
            )

        assert len(captured_prompt_content) == 1, "--system-prompt-file was not passed"
        assert "Override prompt text." in captured_prompt_content[0]

    def test_custom_prompt_forwarded_without_preset(self, tmp_path):
        """When no preset, caller's prompt is forwarded via --system-prompt-file."""
        handoff_file = tmp_path / ".dagi" / "handoffs" / "test.md"
        handoff_file.parent.mkdir(parents=True, exist_ok=True)
        handoff_file.write_text("done", encoding="utf-8")

        raw_result = {"status": "ok", "handoff": str(handoff_file)}
        captured: list[str] = []

        def capture_and_return(*_args, **kwargs):
            extra = kwargs.get("extra_argv") or []
            if "--system-prompt-file" in extra:
                idx = extra.index("--system-prompt-file")
                captured.append(Path(extra[idx + 1]).read_text(encoding="utf-8"))
            return raw_result

        with patch("tools.subagent_api._runner.run_subagent", side_effect=capture_and_return):
            run_subagent(
                task="Audit",
                prompt="You are a security auditor.",
                project_path=tmp_path,
            )

        assert len(captured) == 1
        assert "security auditor" in captured[0]

    def test_extra_argv_forwarded_with_preset(self, tmp_path):
        """Caller-supplied extra_argv is merged into runner's extra_argv alongside internal args."""
        preset_dir = tmp_path / ".dagi" / "subagents" / "compact"
        preset_dir.mkdir(parents=True)
        (preset_dir / "prompt.md").write_text("You are compact.", encoding="utf-8")
        (preset_dir / "subagent_config.yaml").write_text(
            "model_tier: inherit\ntools: []\n", encoding="utf-8"
        )
        handoff_file = tmp_path / ".dagi" / "handoffs" / "compact.md"
        handoff_file.parent.mkdir(parents=True, exist_ok=True)
        handoff_file.write_text("done", encoding="utf-8")

        raw_result = {"status": "ok", "handoff": str(handoff_file)}
        captured_extra: list[list[str]] = []

        def capture(*_args, **kwargs):
            captured_extra.append(list(kwargs.get("extra_argv") or []))
            return raw_result

        with patch("tools.subagent_api._runner.run_subagent", side_effect=capture):
            run_subagent(
                task="compact this",
                preset="compact",
                project_path=tmp_path,
                extra_argv=["--fork-context", "/tmp/fc.json"],
            )

        assert len(captured_extra) == 1
        argv = captured_extra[0]
        assert "--fork-context" in argv
        assert argv[argv.index("--fork-context") + 1] == "/tmp/fc.json"
        assert "--system-prompt-file" in argv  # internal arg still present

    def test_fork_context_path_forwarded_as_argv(self, tmp_path):
        """run_subagent(fork_context_path=...) injects --fork-context into runner's argv."""
        preset_dir = tmp_path / ".dagi" / "subagents" / "compact"
        preset_dir.mkdir(parents=True)
        (preset_dir / "prompt.md").write_text("summarise", encoding="utf-8")
        (preset_dir / "subagent_config.yaml").write_text(
            "tools: []\nmodel_tier: inherit\ndefault_handoff_spec: summary\nagents_md: []\n",
            encoding="utf-8",
        )
        fc_path = tmp_path / "fork_ctx.json"
        fc_path.write_text('{"version":1}', encoding="utf-8")

        captured: list[list[str]] = []

        def capture(*_args, **kwargs):
            captured.append(list(kwargs.get("extra_argv") or []))
            return {"status": "ok", "handoff": ""}

        with patch("tools.subagent_api._runner.run_subagent", side_effect=capture):
            run_subagent(
                task="",
                preset="compact",
                project_path=tmp_path,
                fork_context_path=str(fc_path),
            )

        assert len(captured) == 1
        argv = captured[0]
        assert "--fork-context" in argv
        assert argv[argv.index("--fork-context") + 1] == str(fc_path)
        assert "--system-prompt-file" in argv  # internal arg still present


class TestBranchStartLogging:
    """run_subagent() logs branch/start on parent_log before spawning."""

    def _make_open_log(self) -> SessionLog:
        """Return a SessionLog with an open turn and step."""
        log = SessionLog()
        log.append(sev.TURN_START, {"turn": 1})
        log.append(sev.STEP_START, {"turn": 1, "step": 1})
        return log

    @patch("tools.subagent_api._runner.run_subagent")
    def test_branch_start_logged_before_spawn(self, mock_runner):
        """branch/start is appended to parent_log before the subprocess."""
        mock_runner.return_value = {
            "status": "ok",
            "handoff": str(Path("fake.md")),
        }
        log = self._make_open_log()
        initial_count = len(log.events)

        with patch("tools.subagent_api.Path.write_text"):
            with patch("tools.subagent_api.Path.read_text", return_value="handoff"):
                run_subagent(
                    task="test",
                    prompt="do stuff",
                    parent_log=log,
                )

        branch_events = [
            e for e in log.events[initial_count:]
            if e.type == sev.BRANCH_START
        ]
        assert len(branch_events) == 1
        evt = branch_events[0]
        assert evt.data["parent_branch"] == "main"
        assert evt.data["turn"] == 1
        assert evt.data["step"] == 1
        assert evt.branch == "main"

    @patch("tools.subagent_api._runner.run_subagent")
    def test_no_parent_log_no_branch_event(self, mock_runner):
        """When parent_log is None, no branch/start is logged."""
        mock_runner.return_value = {
            "status": "ok",
            "handoff": str(Path("fake.md")),
        }
        with patch("tools.subagent_api.Path.write_text"):
            with patch("tools.subagent_api.Path.read_text", return_value="handoff"):
                result = run_subagent(
                    task="test",
                    prompt="do stuff",
                )
        assert result.branch_id is None

    @patch("tools.subagent_api._runner.run_subagent")
    def test_branch_id_on_result(self, mock_runner):
        """SubagentResult.branch_id is set when parent_log is provided."""
        mock_runner.return_value = {
            "status": "ok",
            "handoff": str(Path("fake.md")),
        }
        log = self._make_open_log()

        with patch("tools.subagent_api.Path.write_text"):
            with patch("tools.subagent_api.Path.read_text", return_value="handoff"):
                result = run_subagent(
                    task="test",
                    prompt="do stuff",
                    parent_log=log,
                )
        assert result.branch_id is not None
        assert result.branch_id.startswith("custom_")

    @patch("tools.subagent_api._runner.run_subagent")
    def test_branch_id_uses_subagent_type(self, mock_runner, tmp_path):
        """branch_id is prefixed with the subagent type name."""
        handoff_file = tmp_path / ".dagi" / "handoffs" / "explore_files_abc.md"
        handoff_file.parent.mkdir(parents=True, exist_ok=True)
        handoff_file.write_text("done", encoding="utf-8")
        mock_runner.return_value = {"status": "ok", "handoff": str(handoff_file)}

        preset_dir = tmp_path / ".dagi" / "subagents" / "explore_files"
        preset_dir.mkdir(parents=True)
        (preset_dir / "prompt.md").write_text("Explorer.", encoding="utf-8")
        (preset_dir / "subagent_config.yaml").write_text(
            "tools: [read]\nmodel_tier: worker\n"
            "default_handoff_spec: report\nagents_md: []\n",
            encoding="utf-8",
        )
        log = self._make_open_log()

        with patch("tools.subagent_api.Path.write_text"):
            result = run_subagent(
                task="test",
                preset="explore_files",
                parent_log=log,
                project_path=tmp_path,
            )
        assert result.branch_id.startswith("explore_files_")

    @patch("tools.subagent_api._runner.run_subagent")
    def test_no_branch_when_no_open_turn(self, mock_runner):
        """No branch/start logged if parent_log has no open turn."""
        mock_runner.return_value = {
            "status": "ok",
            "handoff": str(Path("fake.md")),
        }
        log = SessionLog()  # no open turn

        with patch("tools.subagent_api.Path.write_text"):
            with patch("tools.subagent_api.Path.read_text", return_value="handoff"):
                result = run_subagent(
                    task="test",
                    prompt="do stuff",
                    parent_log=log,
                )
        branch_events = [e for e in log.events if e.type == sev.BRANCH_START]
        assert len(branch_events) == 0
        assert result.branch_id is None

    @patch("tools.subagent_api._runner.run_subagent")
    def test_no_branch_when_turn_open_but_no_step(self, mock_runner):
        """No branch/start logged if turn is open but no step has started yet.

        open_step is None in this state; emitting {"step": None} would violate
        the spec that step is int.
        """
        mock_runner.return_value = {
            "status": "ok",
            "handoff": str(Path("fake.md")),
        }
        log = SessionLog()
        log.append(sev.TURN_START, {"turn": 1})  # turn open, no step started

        with patch("tools.subagent_api.Path.write_text"):
            with patch("tools.subagent_api.Path.read_text", return_value="handoff"):
                result = run_subagent(
                    task="test",
                    prompt="do stuff",
                    parent_log=log,
                )
        branch_events = [e for e in log.events if e.type == sev.BRANCH_START]
        assert len(branch_events) == 0
        assert result.branch_id is None


class TestInheritedSubagentExecution:
    def _provider(
        self,
        request: dict,
        generation: int = 4,
    ) -> tuple[ParentContextProvider, MagicMock, MagicMock]:
        capture = MagicMock(
            side_effect=lambda branch_id, _mode: ParentFork(
                branch_id=branch_id,
                parent_cut_seq=12,
                parent_surface_generation=generation,
                request=request,
            )
        )
        current_generation = MagicMock(return_value=generation)
        return ParentContextProvider(capture, current_generation), capture, current_generation

    def test_inherited_context_captures_generated_branch_and_v2_payload(self, tmp_path):
        """A provider fork carries the exact request and effective tool allowlist."""
        provider, capture, _generation = self._provider(
            {"model": "parent-model", "messages": [{"role": "user", "content": "hi"}]}
        )
        captured_contexts: list[dict] = []

        def runner(*_args, **kwargs):
            argv = kwargs["extra_argv"]
            fork_path = Path(argv[argv.index("--fork-context") + 1])
            captured_contexts.append(json.loads(fork_path.read_text(encoding="utf-8")))
            fork_path.unlink()
            return {"status": "error", "message": "expected test result"}

        with patch("tools.subagent_api._runner.run_subagent", side_effect=runner):
            result = run_subagent(
                task="Inspect the code",
                prompt="You are an inspector.",
                tools=["read", "grep"],
                project_path=tmp_path,
                parent_context=provider,
            )

        assert result.branch_id is not None
        capture.assert_called_once_with(result.branch_id, "spawn")
        assert captured_contexts == [{
            "version": 2,
            "branch": {
                "id": result.branch_id,
                "parent_cut_seq": 12,
                "parent_surface_generation": 4,
            },
            "request": {
                "model": "parent-model",
                "messages": [{"role": "user", "content": "hi"}],
            },
            "child": {"type": "custom", "allowed_tools": ["read", "grep"]},
        }]

    def test_handoff_dir_controls_handoff_parent(self, tmp_path):
        """A caller-selected handoff parent is passed through to the runner."""
        handoff_dir = tmp_path / "wtf-handoffs"
        observed_paths: list[Path] = []

        def runner(*_args, **kwargs):
            observed_paths.append(kwargs["handoff_path"])
            return {"status": "error", "message": "expected test result"}

        with patch("tools.subagent_api._runner.run_subagent", side_effect=runner):
            run_subagent(
                task="Inspect", prompt="Inspect.", project_path=tmp_path, handoff_dir=handoff_dir,
            )

        assert observed_paths[0].parent == handoff_dir
        assert handoff_dir.is_dir()

    def test_inherited_success_with_changed_generation_is_stale(self, tmp_path):
        """A child response is rejected when its parent surface changed meanwhile."""
        handoff = tmp_path / "handoff.md"
        handoff.write_text("obsolete", encoding="utf-8")
        provider, _capture, generation = self._provider({"model": "parent"})
        generation.return_value = 5

        def successful_runner(*_args, **kwargs):
            argv = kwargs["extra_argv"]
            Path(argv[argv.index("--fork-context") + 1]).unlink()
            return {"status": "ok", "handoff": str(handoff)}

        with patch("tools.subagent_api._runner.run_subagent", side_effect=successful_runner):
            result = run_subagent(
                task="Inspect", prompt="Inspect.", project_path=tmp_path, parent_context=provider,
            )

        assert result.status == "stale"
        assert result.handoff_text == ""
        assert result.is_ok is False

    def test_parent_context_rejects_explicit_fork_context_path(self, tmp_path):
        """A generated v2 context must not silently override a caller's v1 path."""
        provider, _capture, _generation = self._provider({"model": "parent"})

        with pytest.raises(ValueError, match="fork_context_path"):
            run_subagent(
                task="Inspect",
                prompt="Inspect.",
                project_path=tmp_path,
                parent_context=provider,
                fork_context_path=tmp_path / "v1.json",
            )

    def test_parent_context_owns_branch_event_when_parent_log_is_supplied(self, tmp_path):
        """Provider capture records the only branch event for an inherited execution."""
        log = SessionLog()
        log.append(sev.TURN_START, {"turn": 1})
        log.append(sev.STEP_START, {"turn": 1, "step": 1})

        def capture(branch_id, _mode):
            log.append(
                sev.BRANCH_START,
                {
                    "branch": branch_id,
                    "parent_branch": "main",
                    "turn": 1,
                    "step": 1,
                    "parent_cut_seq": 2,
                    "parent_surface_generation": 0,
                },
            )
            return ParentFork(branch_id, 2, 0, {"model": "parent"})

        provider = ParentContextProvider(capture, lambda: 0)

        def runner(*_args, **kwargs):
            argv = kwargs["extra_argv"]
            Path(argv[argv.index("--fork-context") + 1]).unlink()
            return {"status": "error", "message": "expected test result"}

        with patch("tools.subagent_api._runner.run_subagent", side_effect=runner):
            result = run_subagent(
                task="Inspect",
                prompt="Inspect.",
                project_path=tmp_path,
                parent_log=log,
                parent_context=provider,
            )

        branch_events = [event for event in log.events if event.type == sev.BRANCH_START]
        assert len(branch_events) == 1
        assert branch_events[0].data["branch"] == result.branch_id

    def test_duplicate_fork_context_flags_are_rejected_before_spawn(self, tmp_path):
        """Multiple fork paths cannot desynchronise argparse and runner cleanup."""
        with patch("tools.subagent_api._runner.run_subagent") as runner:
            with pytest.raises(ValueError, match="multiple --fork-context"):
                run_subagent(
                    task="Inspect",
                    prompt="Inspect.",
                    project_path=tmp_path,
                    extra_argv=[
                        "--fork-context",
                        "first.json",
                        "--fork-context",
                        "second.json",
                    ],
                )

        runner.assert_not_called()

    def test_fork_context_flag_requires_a_path_before_spawn(self, tmp_path):
        """A trailing flag produces an API error rather than a malformed child command."""
        with patch("tools.subagent_api._runner.run_subagent") as runner:
            with pytest.raises(ValueError, match="requires a path"):
                run_subagent(
                    task="Inspect",
                    prompt="Inspect.",
                    project_path=tmp_path,
                    extra_argv=["--fork-context"],
                )

        runner.assert_not_called()

    def test_registered_runner_retains_its_owned_fork_context_on_error(self, tmp_path):
        """API cleanup does not race a runner that registered the inherited context."""
        from tools import _subagent_runner

        provider, _capture, _generation = self._provider({"model": "parent"})
        registered_paths: list[Path] = []
        registered_states = []

        def registered_runner(*_args, **kwargs):
            argv = kwargs["extra_argv"]
            path = Path(argv[argv.index("--fork-context") + 1])
            task_file = tmp_path / "registered-task.txt"
            task_file.write_text("task", encoding="utf-8")
            proc = MagicMock(pid=9100)
            state = _subagent_runner._SubagentState(
                proc=proc,
                handoff_path=tmp_path / "handoff.md",
                task_file=task_file,
                subagent_type="custom",
                on_event=None,
                fork_context_path=path,
            )
            with _subagent_runner._active_lock:
                _subagent_runner._active[proc.pid] = state
            registered_paths.append(path)
            registered_states.append(state)
            raise RuntimeError("post-registration failure")

        try:
            with patch(
                "tools.subagent_api._runner.run_subagent",
                side_effect=registered_runner,
            ):
                with pytest.raises(RuntimeError, match="post-registration"):
                    run_subagent(
                        task="Inspect",
                        prompt="Inspect.",
                        project_path=tmp_path,
                        parent_context=provider,
                    )
            assert registered_paths[0].exists()
        finally:
            for state in registered_states:
                _subagent_runner._cleanup_terminal_state(state)

    def test_spawn_raise_cleans_api_owned_fork_context(self, tmp_path):
        """A pre-registration spawn failure cannot leak the v2 context file."""
        provider, _capture, _generation = self._provider({"model": "parent"})
        created_paths: list[Path] = []

        def raising_runner(*_args, **kwargs):
            argv = kwargs["extra_argv"]
            created_paths.append(Path(argv[argv.index("--fork-context") + 1]))
            raise OSError("spawn failed")

        with patch("tools.subagent_api._runner.run_subagent", side_effect=raising_runner):
            with pytest.raises(OSError, match="spawn failed"):
                run_subagent(
                    task="Inspect",
                    prompt="Inspect.",
                    project_path=tmp_path,
                    parent_context=provider,
                )

        assert len(created_paths) == 1
        assert not created_paths[0].exists()


class TestBuildForkContext:
    def test_fork_context_structure(self):
        """build_fork_context returns version-1 format with branch and request."""
        from tools.subagent_api import build_fork_context

        ctx = build_fork_context(
            branch_id="compact_abc",
            parent_cut_seq=42,
            parent_surface_generation=0,
            request_snapshot={
                "model": "test/model",
                "messages": [{"role": "system", "content": "hello"}],
                "tools": [],
                "parallel_tool_calls": False,
                "extra_body": {},
                "base_url": "https://api.example.com/v1",
            },
        )
        assert ctx["version"] == 1
        assert ctx["branch"]["id"] == "compact_abc"
        assert ctx["branch"]["parent_cut_seq"] == 42
        assert ctx["branch"]["parent_surface_generation"] == 0
        assert ctx["request"]["model"] == "test/model"
        assert ctx["request"]["messages"] == [{"role": "system", "content": "hello"}]
        assert ctx["request"]["tools"] == []
        assert ctx["request"]["parallel_tool_calls"] is False

    def test_fork_context_excludes_api_key(self):
        """Fork-context must not contain API keys."""
        import json
        from tools.subagent_api import build_fork_context

        ctx = build_fork_context(
            branch_id="compact_abc",
            parent_cut_seq=42,
            parent_surface_generation=0,
            request_snapshot={
                "model": "test/model",
                "messages": [],
                "tools": [],
                "parallel_tool_calls": False,
                "extra_body": {},
                "base_url": "https://api.example.com/v1",
            },
        )
        serialized = json.dumps(ctx)
        assert "api_key" not in serialized
        assert "sk-" not in serialized

    def test_fork_context_file_round_trips(self, tmp_path):
        """The fork-context dict round-trips through JSON serialization."""
        import json
        from tools.subagent_api import build_fork_context

        ctx = build_fork_context(
            branch_id="compact_test",
            parent_cut_seq=10,
            parent_surface_generation=0,
            request_snapshot={
                "model": "m",
                "messages": [{"role": "user", "content": "hi"}],
                "tools": [],
                "parallel_tool_calls": False,
                "extra_body": {},
                "base_url": "",
            },
        )
        path = tmp_path / "fork_ctx.json"
        path.write_text(json.dumps(ctx), encoding="utf-8")
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["version"] == 1
        assert loaded["branch"]["id"] == "compact_test"
        assert loaded["request"]["messages"] == [{"role": "user", "content": "hi"}]

    def test_fork_context_defaults_for_missing_snapshot_fields(self):
        """Missing optional snapshot fields default gracefully."""
        from tools.subagent_api import build_fork_context

        ctx = build_fork_context(
            branch_id="compact_min",
            parent_cut_seq=1,
            parent_surface_generation=0,
            request_snapshot={"model": "m", "messages": []},
        )
        assert ctx["request"]["tools"] == []
        assert ctx["request"]["parallel_tool_calls"] is False
        assert ctx["request"]["extra_body"] == {}
        assert ctx["request"]["base_url"] == ""


class TestResumeSubagentByPid:
    def test_resume_returns_result(self):
        """resume_subagent_by_pid wraps _runner.resume_subagent and builds result."""
        raw = {"status": "ok", "handoff": "/tmp/h.md"}
        with patch("tools.subagent_api._runner.resume_subagent", return_value=raw), \
             patch("tools.subagent_api._auto_read_handoff", return_value="done"):
            result = resume_subagent_by_pid(9999, 120.0)

        assert result.status == "ok"
        assert result.handoff_text == "done"
        assert result.is_ok is True

    def test_resume_unverified_status(self):
        """resume_subagent_by_pid handles ok_unverified status."""
        raw = {"status": "ok_unverified", "handoff": "/tmp/h.md"}
        with patch("tools.subagent_api._runner.resume_subagent", return_value=raw), \
             patch("tools.subagent_api._auto_read_handoff", return_value="scraped"):
            result = resume_subagent_by_pid(9999, 120.0)

        assert result.status == "ok_unverified"
        assert result.handoff_text == "scraped"
        assert result.is_ok is True

    def test_resume_error_status(self):
        """resume_subagent_by_pid handles error status without reading handoff."""
        raw = {"status": "error", "message": "exited with code 1", "pid": 9999}
        with patch("tools.subagent_api._runner.resume_subagent", return_value=raw):
            result = resume_subagent_by_pid(9999, 120.0)

        assert result.status == "error"
        assert result.handoff_text == ""
        assert result.is_ok is False
        assert result.pid == 9999

