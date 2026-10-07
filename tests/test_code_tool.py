"""tests/test_code_tool.py — CodeTool end to end, with a real runner subprocess."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from agent.base_tool import BaseTool
from agent.protocol import SideEffect, ToolResult
from agent.registry import ToolRegistry
from tools.bash import BashTool
from tools.code import CodeTool
from tools.edit import EditTool
from tools.read import ReadTool
from tools.write import WriteTool


def _tool(tmp_path: Path, *, skip: tuple[str, ...] = ()) -> tuple[CodeTool, ToolRegistry]:
    reg = ToolRegistry()
    tools = {
        "read": ReadTool(cwd=tmp_path, allowed_roots=[tmp_path]),
        "write": WriteTool(cwd=tmp_path, allowed_roots=[tmp_path]),
        "edit": EditTool(cwd=tmp_path, allowed_roots=[tmp_path]),
        "bash": BashTool(cwd=tmp_path),
    }
    for name, tool in tools.items():
        if name not in skip:
            reg.register(tool)
    code = CodeTool(registry=reg, cwd=tmp_path)
    reg.register(code)
    return code, reg


class _ImageRead(BaseTool):
    name = "read"
    description = "fake image read"
    _parameters = {"type": "object", "properties": {"path": {"type": "string"}}}

    def run(self, **_kwargs):
        return ToolResult("[Image: x.png]", side_effect=SideEffect.ATTACH_IMAGE)


def test_print_and_return(tmp_path):
    code, _ = _tool(tmp_path)
    out = code.run("print('hello')\nreturn {'n': 2}")
    assert out.startswith("[code: completed in ")
    assert "hello" in out
    assert '[return]\n{\n  "n": 2\n}' in out


def test_empty_script_reports_no_output(tmp_path):
    code, _ = _tool(tmp_path)
    assert code.run("x = 1").endswith("[no output]")


def test_write_then_read_round_trip_unicode(tmp_path):
    code, _ = _tool(tmp_path)
    out = code.run(
        "tools.write(path='a.txt', content='héllo ✓')\n"
        "print('héllo ✓' in tools.read(path='a.txt'))"
    )
    assert "[code: completed" in out and "True" in out
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "héllo ✓"


def test_failed_edit_raises_tool_error_that_can_be_caught(tmp_path):
    (tmp_path / "a.txt").write_text("abc", encoding="utf-8")
    code, _ = _tool(tmp_path)
    out = code.run(
        "try:\n"
        "    tools.edit(path='a.txt', oldText='zzz', newText='y')\n"
        "except ToolError as e:\n"
        "    print('caught', e)\n"
        "return 'went on'"
    )
    assert "caught Error:" in out and "oldText not found" in out
    assert "[return]\nwent on" in out


@pytest.mark.parametrize("name", ["ask_user", "code", "write_handoff"])
def test_disallowed_tools_raise(tmp_path, name):
    code, _ = _tool(tmp_path)
    out = code.run(f"tools.{name}()")
    assert out.startswith("[code: failed")
    assert f"ToolError: tool '{name}' is not available in code mode" in out
    assert "bash, edit, read, write" in out


def test_denied_tool_raises(tmp_path):
    code, reg = _tool(tmp_path)
    reg.deny({"bash"})
    out = code.run("tools.bash(command='echo hi')")
    assert "ToolError: tool 'bash' is not available" in out


def test_unregistered_allowed_tool_raises(tmp_path):
    code, _ = _tool(tmp_path, skip=("edit",))
    assert "ToolError: tool 'edit' is not available" in code.run("tools.edit(path='a')")


def test_side_effect_result_is_refused(tmp_path):
    reg = ToolRegistry()
    reg.register(_ImageRead())
    code = CodeTool(registry=reg, cwd=tmp_path)
    out = code.run("tools.read(path='x.png')")
    assert "ToolError" in out and "call `read` directly" in out


def test_bad_arguments_raise_tool_error(tmp_path):
    code, _ = _tool(tmp_path)
    out = code.run("tools.write(nope=1)")
    assert out.startswith("[code: failed") and "ToolError: Error:" in out


def test_bash_returns_structured_dict(tmp_path):
    code, _ = _tool(tmp_path)
    out = code.run("r = tools.bash(command='exit 3')\nreturn r['exit_code']")
    assert out.startswith("[code: completed") and "[return]\n3" in out


def test_exception_lists_applied_mutations(tmp_path):
    code, _ = _tool(tmp_path)
    out = code.run(
        "tools.write(path='a.txt', content='1')\n"
        "tools.read(path='a.txt')\n"
        "tools.write(path='b.txt', content='2')\n"
        "raise RuntimeError('late failure')"
    )
    assert out.startswith("[code: failed")
    assert "RuntimeError: late failure" in out and 'File "<script>", line 4' in out
    assert "[already applied] write(path=a.txt), write(path=b.txt)" in out


def test_success_does_not_list_applied_calls(tmp_path):
    code, _ = _tool(tmp_path)
    assert "[already applied]" not in code.run("tools.write(path='a.txt', content='1')")


def test_syntax_error(tmp_path):
    code, _ = _tool(tmp_path)
    out = code.run("x = 1\ndef (:")
    assert out.startswith("[code: failed") and "SyntaxError" in out and "line 2" in out


def test_timeout_kills_script(tmp_path):
    code, _ = _tool(tmp_path)
    started = time.monotonic()
    out = code.run("while True:\n    pass", timeout=2)
    assert out.startswith("[code: timed out after 2s]")
    assert time.monotonic() - started < 10


def test_force_kill(tmp_path):
    code, _ = _tool(tmp_path)
    timer = threading.Timer(1.0, code.force_kill)
    timer.start()
    started = time.monotonic()
    out = code.run("import time\ntime.sleep(30)")
    timer.join()
    assert out.startswith("[code: killed by user]")
    assert time.monotonic() - started < 10


def test_force_kill_when_idle_returns_false(tmp_path):
    code, _ = _tool(tmp_path)
    assert code.force_kill() is False


def test_stray_output_does_not_break_protocol(tmp_path):
    code, _ = _tool(tmp_path)
    out = code.run("import os\nos.system('echo stray')\nreturn 'fine'")
    assert out.startswith("[code: completed")
    assert "[stray output]" in out and "stray" in out.split("[stray output]")[1]
    assert "[return]\nfine" in out


def test_description_lists_only_available_tools(tmp_path):
    code, reg = _tool(tmp_path)
    reg.deny({"bash"})
    text = code.description
    assert "tools.read(path: str" in text and "tools.write(" in text
    assert "tools.bash(" not in text and "tools.code(" not in text
