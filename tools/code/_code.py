"""tools/code/_code.py — the `code` tool: run one script that chains dagi tool calls.

The script runs in a child process (``_runner.py``, dagi's own interpreter). Each
``tools.<name>(**args)`` call comes back here over JSON lines and runs through the parent
ToolRegistry, so path guards and tool behaviour match a direct call. Only the script's
printed output and return value are returned to the model.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from agent._process_kill import kill_process_tree
from agent.base_tool import BaseTool
from agent.protocol import ToolResult
from agent.registry import ToolRegistry
from tools.bash._bash import _process_group_kwargs
from tools.code._stubs import tool_stub

CODE_TOOLS = ("read", "grep", "find", "write", "edit", "copy", "bash")
MUTATING = frozenset({"write", "edit", "copy", "bash"})
ERROR_PREFIXES = ("Error", "Access denied", "[paused]")
_RUNNER = Path(__file__).with_name("_runner.py")
_KEY_ARGS = ("path", "command", "pattern", "src")
_REAP_GRACE = 5.0

_DESCRIPTION = (
    "Run a Python script that chains dagi tools in one call. Use it for several mechanical "
    "steps whose intermediate results you do not need to read (search then read the matches, "
    "the same edit across files, run tests and extract the failures). Only what the script "
    "prints or returns comes back, so filter large results inside the script. Call tools as "
    "tools.<name>(**args); a failed call raises ToolError (catch it to continue). Calls are "
    "real and are not undone if the script fails later. Use tools.* for files and commands, "
    "not open()/subprocess. No input(). Top-level `return` is allowed. Runs in the project "
    "directory with dagi's Python. Available:"
)


@dataclass
class _Run:
    """State of one script execution."""
    ledger: list[str] = field(default_factory=list)   # mutating calls that succeeded
    stray: list[str] = field(default_factory=list)    # stderr lines from the child
    done: dict | None = None
    status: str = "completed"   # completed | failed | timed out | killed | crashed


def _ledger_entry(name: str, args: dict) -> str:
    key = next((k for k in _KEY_ARGS if k in args), None)
    if key is None:
        return f"{name}()"
    return f"{name}({key}={str(args[key])[:60]})"


def _start_readers(proc: subprocess.Popen, run: _Run) -> tuple[queue.Queue, list]:
    """Daemon readers: rpc lines into a queue (None at EOF), stderr lines into run.stray."""
    lines: queue.Queue = queue.Queue()

    def read_rpc() -> None:
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    def read_stray() -> None:
        for line in proc.stderr:
            run.stray.append(line)

    threads = [threading.Thread(target=t, daemon=True) for t in (read_rpc, read_stray)]
    for thread in threads:
        thread.start()
    return lines, threads


def _header(status: str, elapsed: float, limit: float) -> str:
    if status == "timed out":
        return f"[code: timed out after {limit:g}s]"
    if status == "killed":
        return "[code: killed by user]"
    return f"[code: {status} in {elapsed:.1f}s]"


def _format(run: _Run, elapsed: float, limit: float) -> str:
    """The single result string: header, output, return, error, stray output, ledger."""
    header = _header(run.status, elapsed, limit)
    done = run.done or {}
    sections = [done.get("output", "").rstrip("\n")]
    if done.get("return") is not None:
        sections.append(f"[return]\n{done['return']}")
    if done.get("error"):
        sections.append(f"[error]\n{done['error']}")
    stray = "".join(run.stray).rstrip("\n")
    if stray:
        sections.append(f"[stray output]\n{stray}")
    if run.status != "completed" and run.ledger:
        sections.append(f"[already applied] {', '.join(run.ledger)}")
    body = "\n".join(s for s in sections if s)
    return f"{header}\n{body or '[no output]'}"


class CodeTool(BaseTool):
    name = "code"
    _parameters = {
        "type": "object",
        "properties": {
            "script": {
                "type": "string",
                "description": "Python source; may use top-level return",
            },
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 300)"},
        },
        "required": ["script"],
    }

    DEFAULT_TIMEOUT = 300.0

    def __init__(self, registry: ToolRegistry, cwd: Path = Path(".")):
        self._registry = registry
        self.cwd = cwd
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._killed = False

    @property
    def description(self) -> str:
        """Usage rules plus one stub per tool callable right now (never stale)."""
        stubs = [
            f"  {tool_stub(self._registry.get(n).schema())}"
            for n in CODE_TOOLS if self._registry.is_available(n)
        ]
        return "\n".join([_DESCRIPTION, *stubs])

    def run(self, script: str, timeout: int | None = None) -> str:
        limit = float(timeout) if timeout is not None else self.DEFAULT_TIMEOUT
        started = time.monotonic()
        run = _Run()
        proc = self._spawn()
        with self._lock:
            self._proc = proc
            self._killed = False
        lines, threads = _start_readers(proc, run)
        try:
            self._send(proc, {"script": script})
            self._serve(proc, lines, run, started + limit)
        finally:
            self._reap(proc, threads)
        return _format(run, time.monotonic() - started, limit)

    def force_kill(self) -> bool:
        """Kill the running script's process tree. Returns whether anything was killed."""
        with self._lock:
            proc = self._proc
            if proc is None:
                return False
            self._killed = True
        kill_process_tree(proc)
        return True

    # ── process plumbing ────────────────────────────────────────────────

    def _spawn(self) -> subprocess.Popen:
        return subprocess.Popen(
            [sys.executable, "-u", str(_RUNNER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.cwd),
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            **_process_group_kwargs(),
        )

    @staticmethod
    def _send(proc: subprocess.Popen, message: dict) -> bool:
        """Write one JSON line to the child; False when the pipe is already gone."""
        try:
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    def _serve(
        self, proc: subprocess.Popen, lines: queue.Queue, run: _Run, deadline: float,
    ) -> None:
        """Answer the child's calls until it reports done, dies, or the deadline passes."""
        while True:
            try:
                line = lines.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                run.status = "timed out"
                return
            if line is None:
                run.status = "killed" if self._killed else "crashed"
                return
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                run.stray.append(line)
                run.status = "crashed"
                return
            if message["type"] == "done":
                run.done = message
                run.status = "failed" if message["error"] else "completed"
                return
            reply = self._dispatch(message["name"], message["args"], run)
            if not self._send(proc, reply):
                run.status = "killed" if self._killed else "crashed"
                return

    def _reap(self, proc: subprocess.Popen, threads: list[threading.Thread]) -> None:
        """Kill the child if still running, then collect what the readers saw."""
        if proc.poll() is None:
            kill_process_tree(proc)
        try:
            proc.wait(timeout=_REAP_GRACE)
        except subprocess.TimeoutExpired:
            pass
        # Grandchildren can keep the pipes open after a kill, so the join is bounded.
        for thread in threads:
            thread.join(timeout=_REAP_GRACE)
        with self._lock:
            self._proc = None

    # ── tool calls ──────────────────────────────────────────────────────

    def _dispatch(self, name: str, args: dict, run: _Run) -> dict:
        """Run one proxied call; returns the reply sent back to the script."""
        if name not in CODE_TOOLS or not self._registry.is_available(name):
            available = ", ".join(sorted(
                n for n in CODE_TOOLS if self._registry.is_available(n)
            ))
            return {"ok": False, "error": (
                f"tool {name!r} is not available in code mode; available: {available}"
            )}
        error, result = self._call(name, args)
        if error is not None:
            return {"ok": False, "error": error}
        if name in MUTATING:
            run.ledger.append(_ledger_entry(name, args))
        return {"ok": True, "result": result}

    def _call(self, name: str, args: dict) -> tuple[str | None, object]:
        """Run the tool; returns (error text, None) on failure, else (None, result)."""
        if name == "bash":
            try:
                result = self._registry.get("bash").run_structured(**args)
            except Exception as exc:  # noqa: BLE001 - mirror ToolRegistry.dispatch
                return f"Error: {exc}", None
            return ("[killed by user]", None) if result["killed"] else (None, result)
        result = self._registry.dispatch(name, args)
        if isinstance(result, ToolResult):
            if result.side_effect is not None:
                return (
                    f"{name} returned a result the script cannot use "
                    f"({result.side_effect.name}); call `{name}` directly instead"
                ), None
            result = result.output
        if isinstance(result, str) and result.startswith(ERROR_PREFIXES):
            return result, None
        return None, result
