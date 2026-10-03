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


class TestBashPlatformDescription:
    """The schema must name the OS and the shell Popen(shell=True) really launches;
    a description that says 'bash' on Windows sent the model down Unix paths."""

    def _describe(self, monkeypatch, plat, version, comspec=None):
        from tools.bash import _bash
        monkeypatch.setattr(_bash.sys, "platform", plat)
        monkeypatch.setattr(_bash.platform, "version", lambda: version)
        if comspec is None:
            monkeypatch.delenv("COMSPEC", raising=False)
        else:
            monkeypatch.setenv("COMSPEC", comspec)
        return BashTool().schema()["function"]["description"]

    def test_windows_11_names_cmd_from_comspec(self, monkeypatch):
        desc = self._describe(
            monkeypatch, "win32", "10.0.26200", r"C:\WINDOWS\system32\cmd.exe")
        assert "Windows 11" in desc
        assert "10.0.26200" in desc
        assert r"C:\WINDOWS\system32\cmd.exe" in desc
        assert "not bash" in desc

    def test_windows_10_build_is_not_reported_as_11(self, monkeypatch):
        desc = self._describe(monkeypatch, "win32", "10.0.19045", "cmd.exe")
        assert "Windows 10" in desc
        assert "Windows 11" not in desc

    def test_posix_names_bin_sh(self, monkeypatch):
        desc = self._describe(monkeypatch, "linux", "#1 SMP")
        assert "/bin/sh" in desc

    def test_description_does_not_leak_into_class(self, monkeypatch):
        self._describe(monkeypatch, "linux", "#1 SMP")
        assert "/bin/sh" not in BashTool.description

    def test_described_shell_is_the_shell_that_runs(self):
        """Ask the real shell for its own path; the description must name it."""
        cmd = "echo %COMSPEC%" if sys.platform == "win32" else "echo $0"
        tool = BashTool()
        shell = tool.run(command=cmd).strip()
        assert shell and shell in tool.schema()["function"]["description"]


class TestBashPipeStatus:
    """A pipe reports only the last command's exit status, so `pytest | findstr` hid a real
    test failure. The tool must say so up front and flag it on every piped result."""

    def test_description_discourages_pipe_filters(self):
        desc = BashTool().schema()["function"]["description"]
        assert "already cut to its first and last" in desc
        assert "last command" in desc

    def test_piped_command_result_carries_status_note(self):
        out = BashTool().run(command="echo hi | sort")
        assert "hi" in out
        assert "exit status is from the last command" in out

    def test_failing_silent_pipe_still_carries_note(self):
        """The first stage fails but sort exits 0: the note is the only warning left."""
        out = BashTool().run(command="exit 3 | sort")
        assert "exit status is from the last command" in out
        assert out != "[no output]"

    @pytest.mark.parametrize("command", [
        "echo hi",
        "echo a || echo b",
        'echo "a|b"',
        "echo a ^| b" if sys.platform == "win32" else r"echo a \| b",
    ])
    def test_non_pipes_get_no_note(self, command):
        assert "exit status is from the last command" not in BashTool().run(command=command)

    @pytest.mark.parametrize("command, piped", [
        ("pytest -q | findstr FAILED", True),
        ("a|b", True),
        ("a || b", False),
        ('findstr "x|y" f.txt', False),
        # cmd.exe has no single-quote quoting, so this really pipes there.
        ("grep 'x|y' f.txt", sys.platform == "win32"),
        ("echo don't | sort", True),
        ("echo a ^| b", False),
        (r"echo a \| b", False),
    ])
    def test_has_pipe_detection(self, command, piped):
        from tools.bash._bash import _has_pipe
        assert _has_pipe(command) is piped
