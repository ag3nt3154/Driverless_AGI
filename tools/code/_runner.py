"""tools/code/_runner.py — child process of the `code` tool.

Runs one model-written script; every ``tools.<name>(**args)`` call is sent to the parent,
which runs it through its ToolRegistry and replies. One JSON object per line, UTF-8:

  parent -> stdin   {"script": str}                                    (first line)
  child  -> rpc     {"type": "call", "name": str, "args": dict}
  parent -> stdin   {"ok": bool, "result": any, "error": str | None}
  child  -> rpc     {"type": "done", "output": str, "return": str | None, "error": str | None}

The rpc channel is a private dup of the original stdout. fd 1 is then pointed at stderr, so
output from processes the script starts can never corrupt the protocol.
"""
from __future__ import annotations

import ast
import io
import json
import linecache
import os
import sys
import traceback

_FILENAME = "<script>"
_TEMPLATE = "def __dagi_main__():\n    pass\n"


class ToolError(Exception):
    """A dagi tool call failed; the message is the tool's own error text."""


def wrap_script(src: str):
    """Compile *src* as the body of ``__dagi_main__`` so a top-level ``return`` works.

    The wrap is done on the AST, not by re-indenting text, so string literals stay exact
    and tracebacks keep the script's own line numbers.
    """
    body = ast.parse(src, filename=_FILENAME).body
    module = ast.parse(_TEMPLATE)
    module.body[0].body = body or [ast.Pass()]
    ast.fix_missing_locations(module)
    linecache.cache[_FILENAME] = (len(src), None, src.splitlines(keepends=True), _FILENAME)
    return compile(module, _FILENAME, "exec")


def render_return(value) -> str | None:
    """The script's return value as text: strings as-is, JSON-able values as JSON."""
    if value is None or isinstance(value, str):
        return value
    try:
        return json.dumps(value, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(value)


def format_error(exc: BaseException) -> str:
    """Traceback limited to frames from the script itself (chained exceptions too)."""
    top = traceback.TracebackException.from_exception(exc)
    pending, seen = [top], set()
    while pending:
        te = pending.pop()
        if id(te) in seen:
            continue
        seen.add(id(te))
        te.stack = traceback.StackSummary.from_list(
            [f for f in te.stack if f.filename == _FILENAME]
        )
        pending += [c for c in (te.__cause__, te.__context__) if c is not None]
    return "".join(top.format()).rstrip()


class _Tools:
    """The ``tools`` object in the script namespace: attribute access -> RPC call."""

    def __init__(self, rpc_out, rpc_in):
        self._out = rpc_out
        self._in = rpc_in

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda **args: self._call(name, args)

    def _call(self, name: str, args: dict):
        self._out.write(json.dumps({"type": "call", "name": name, "args": args}) + "\n")
        self._out.flush()
        reply = json.loads(self._in.readline())
        if not reply["ok"]:
            raise ToolError(reply["error"])
        return reply["result"]


def _execute(src: str, tools: _Tools) -> tuple[str | None, str | None]:
    """Run the script; return (rendered return value, formatted error)."""
    namespace = {"tools": tools, "ToolError": ToolError, "__name__": "__dagi_script__"}
    try:
        exec(wrap_script(src), namespace)
        return render_return(namespace["__dagi_main__"]()), None
    except BaseException as exc:  # noqa: BLE001 - SystemExit etc. are script errors too
        return None, format_error(exc)


def main() -> None:
    rpc_out = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    os.dup2(2, 1)
    sys.stdin.reconfigure(encoding="utf-8")
    request = json.loads(sys.stdin.readline())
    captured = io.StringIO()
    sys.stdout = sys.stderr = captured
    ret, err = _execute(request["script"], _Tools(rpc_out, sys.stdin))
    done = {"type": "done", "output": captured.getvalue(), "return": ret, "error": err}
    rpc_out.write(json.dumps(done) + "\n")
    rpc_out.flush()


if __name__ == "__main__":
    main()
