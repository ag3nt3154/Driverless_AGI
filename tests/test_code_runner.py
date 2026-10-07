"""tests/test_code_runner.py — child-side runner and stub generator of the code tool."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from tools.code import _runner
from tools.code._runner import format_error, render_return, wrap_script
from tools.code._stubs import tool_stub


def _run(src: str):
    namespace: dict = {}
    exec(wrap_script(src), namespace)
    return namespace["__dagi_main__"]()


def test_top_level_return():
    assert _run("x = 2\nreturn x * 3") == 6


def test_empty_script_returns_none():
    assert _run("") is None


def test_multiline_string_kept_exact():
    assert _run('s = """a\n  b\n"""\nreturn s') == "a\n  b\n"


def test_syntax_error_names_script():
    with pytest.raises(SyntaxError) as info:
        wrap_script("x = 1\ndef (:")
    assert info.value.filename == "<script>"
    assert info.value.lineno == 2


def test_format_error_only_script_frames_with_lines():
    with pytest.raises(ValueError) as info:
        _run("def f():\n    raise ValueError('boom')\nf()")
    text = format_error(info.value)
    assert "ValueError: boom" in text
    assert 'File "<script>", line 2' in text
    assert "raise ValueError('boom')" in text
    assert "_runner.py" not in text and "test_code_runner" not in text


def test_render_return():
    assert render_return(None) is None
    assert render_return("x") == "x"
    assert render_return({"a": 1}) == '{\n  "a": 1\n}'
    assert render_return([1, "é"]) == '[\n  1,\n  "é"\n]'
    assert render_return(object()).startswith("<object")


def _schema(name: str, props: dict, required: list[str]) -> dict:
    return {"function": {"name": name, "parameters": {
        "type": "object", "properties": props, "required": required,
    }}}


def test_stub_required_then_optional():
    schema = _schema(
        "read", {"offset": {"type": "integer"}, "path": {"type": "string"}}, ["path"],
    )
    assert tool_stub(schema) == "tools.read(path: str, offset: int = None) -> str"


def test_stub_bash_returns_dict():
    schema = _schema("bash", {"command": {"type": "string"}}, ["command"])
    stub = tool_stub(schema)
    assert stub.startswith("tools.bash(command: str) -> dict")
    assert "exit_code" in stub


def test_runner_round_trip_over_pipes():
    """Real child process: one proxied call with non-ASCII text, then done."""
    proc = subprocess.Popen(
        [sys.executable, "-u", _runner.__file__],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        encoding="utf-8",
    )
    script = "print('hi ✓')\nreturn tools.echo(x='héllo ✓')"
    proc.stdin.write(json.dumps({"script": script}) + "\n")
    proc.stdin.flush()
    call = json.loads(proc.stdout.readline())
    assert call == {"type": "call", "name": "echo", "args": {"x": "héllo ✓"}}
    proc.stdin.write(json.dumps({"ok": True, "result": call["args"]["x"]}) + "\n")
    proc.stdin.flush()
    done = json.loads(proc.stdout.readline())
    proc.communicate(timeout=10)
    assert done == {"type": "done", "output": "hi ✓\n", "return": "héllo ✓", "error": None}
