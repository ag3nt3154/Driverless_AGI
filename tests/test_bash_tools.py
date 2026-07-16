"""tests/test_bash_tools.py — coexistence of bash and injected bash tools."""
from __future__ import annotations
import sys
import threading
import time
from pathlib import Path
import pytest
from agent.base_tool import BaseTool
from agent.tools import create_tool_registry
from tools.bash import BashTool


class _FakeBashTool(BaseTool):
    name = "tmux_bash"
    description = "Fake tmux bash"
    _parameters: dict = {"type": "object", "properties": {}, "required": []}

    def run(self, **kwargs) -> str:
        return ""


class TestBashCoexistence:
    def test_bash_always_registered(self):
        """BashTool must be registered even when a _bash_tool is injected."""
        reg = create_tool_registry(cwd=Path("."), bash_tool=_FakeBashTool())
        names = {n for n, _ in reg.list_tools()}
        assert "bash" in names

    def test_injected_tool_also_registered(self):
        """Injected bash tool must be registered alongside bash, not replacing it."""
        reg = create_tool_registry(cwd=Path("."), bash_tool=_FakeBashTool())
        names = {n for n, _ in reg.list_tools()}
        assert "tmux_bash" in names

    def test_no_injection_still_registers_bash(self):
        reg = create_tool_registry(cwd=Path("."))
        names = {n for n, _ in reg.list_tools()}
        assert "bash" in names

    def test_harbor_bash_name_is_harbor_bash(self):
        """HarborBashTool.name must be 'harbor_bash', not 'bash'."""
        from benchmarks.harbor.bash_tool import HarborBashTool
        tool = HarborBashTool(exec_fn=lambda c, t: "")
        assert tool.name == "harbor_bash"

    def test_tmux_bash_importable_from_tools(self):
        """tools.tmux_bash.TmuxBashTool must be importable and have name 'tmux_bash'."""
        from tools.tmux_bash import TmuxBashTool
        assert TmuxBashTool.name == "tmux_bash"

    def test_hanging_command_is_bounded_by_default_timeout(self):
        """A command with no explicit timeout must not hang forever.

        Regression test: the review subagent runs bash commands (e.g. test
        suites) without always specifying a timeout. Without a default,
        subprocess.run(timeout=None) blocks forever on a hanging command,
        stalling the parent AgentLoop for up to the 30-minute subagent poll
        timeout (or longer, since the orphaned process is never killed).
        """
        tool = BashTool(cwd=Path("."), default_timeout=0.5)
        command = f'"{sys.executable}" -c "import time; time.sleep(5)"'

        start = time.monotonic()
        result = tool.run(command=command)
        elapsed = time.monotonic() - start

        assert elapsed < 4, f"bash tool did not enforce default timeout, took {elapsed}s"
        assert "timed out" in result.lower()


class TestForceKill:
    def test_force_kill_terminates_running_command_immediately(self):
        """Esc-triggered force_kill() must interrupt a running command without
        waiting for its timeout."""
        tool = BashTool(cwd=Path("."), default_timeout=30.0)
        command = f'"{sys.executable}" -c "import time; time.sleep(10)"'
        result_holder: dict = {}

        def _run():
            result_holder["result"] = tool.run(command=command)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        time.sleep(0.5)  # let the subprocess actually start

        killed = tool.force_kill()
        t.join(timeout=5)

        assert killed is True
        assert not t.is_alive(), "run() did not return promptly after force_kill()"
        assert "[killed by user]" in result_holder["result"]

    def test_force_kill_returns_false_when_nothing_running(self):
        tool = BashTool(cwd=Path("."))
        assert tool.force_kill() is False
