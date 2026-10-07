# Code Mode v1 — Implementation Plan

**Goal:** Add a `code` tool that runs one model-written Python script whose `tools.<name>(...)`
calls are proxied back to the parent `ToolRegistry`, behind a global `code_mode` switch.

**Architecture:**
- `CodeTool` (parent, agent-loop thread) spawns `tools/code/_runner.py` with `sys.executable`
  and serves newline-delimited JSON RPC: the child sends `call` messages, the parent dispatches
  them through the registry and replies, the child finishes with one `done` message.
- The child keeps a private dup of its stdout for RPC and redirects fd 1 to fd 2, so stray
  grandchild output can never corrupt the protocol.
- Registered right after `bash` only when `config.code_mode` is true; nothing changes when off.

**Tech Stack:** Python 3 (conda env `dagi`), stdlib only (`ast`, `json`, `subprocess`,
`threading`, `queue`), pytest.

**Spec:** `wiki/tasks/2026-10-07_code-mode/spec.md`

## Global Constraints
- Test command:
  `C:\Users\alexr\anaconda3\envs\dagi\python.exe -u -m pytest -q -p no:pytest-qt -p no:cacheprovider`.
  Baseline at `c5c4759` (two runs): 1586 passed, 3 skipped, 2–3 failed. Pre-existing failures:
  `tests/test_workflow_plan_template.py::test_marker_round_trip_preserves_subtask_bodies`,
  `::test_rendered_template_composes_real_worker_assignment`, plus one flaky test. Do not fix
  them in this task; do not add new failures.
- Functions ≤100 lines; cyclomatic complexity ≤8; ≤5 positional parameters; lines ≤100
  characters; files ≤500 lines.
- No new dependencies.
- Callable tools are exactly `("read", "grep", "find", "write", "edit", "copy", "bash")`.
- Error-prefixes that raise `ToolError`: `("Error", "Access denied", "[paused]")`.
- Default script timeout: 300 seconds.
- Never edit the historical paths: `.superpowers/`, `snapshots/`, `_todo/`, `.dagi/plans/`.
- Never stage or commit the user's unrelated working-tree changes (the `docs/superpowers/`
  deletions and `.dagi/emotes/memes/are_you_there.jpg`). Never `git stash`.
- Registration order with `code_mode` off must stay byte-identical (warm-cache prefix).

## Review Focus
1. **Protocol corruption.** A script that runs `os.system("echo hi")` or prints to
   `sys.__stdout__` must not break RPC. Expected: text lands under `[stray output]`. Subtask 3.
2. **Multi-line strings in scripts.** `x = """a\n  b"""` must keep its exact content after
   wrapping. Expected: AST-level wrapping, no re-indentation. Subtask 2.
3. **Half-applied work.** A script that edits two files then raises must list both edits under
   `[already applied]`. Subtask 3.
4. **MagicMock configs.** `tests/test_tool_registry_contract.py::_config` returns a MagicMock,
   whose missing attributes are truthy. `code_mode` must be set to `False` there explicitly, or
   every contract test silently gains `code`. Subtask 4.
5. **Windows encoding.** Non-ASCII text (`"héllo ✓"`) round-trips through a tool call and print.
   Subtask 3.
6. **Kill paths.** Timeout and `force_kill` kill the whole tree and never hang on the reader
   threads. Subtask 3.

---

### Subtask 1: `code_mode` config and structured bash result
**Goal:** Add the config switch and give `BashTool` a structured result the script can use.

**Requirements:** spec R1, R4 (bash part).

**Acceptance Criteria:**
- `AgentConfig().code_mode is False`; a loaded config without the key has `code_mode is True`;
  `code_mode: false` in YAML gives `False`.
- `BashTool.run_structured(command, timeout)` returns
  `{"output": str, "exit_code": int | None, "timed_out": bool, "killed": bool}`
  (`killed` = ESC force-kill).
- `BashTool.run` output is unchanged for every existing test (it now formats from
  `run_structured`).

**Files:**
- Modify: `agent/_loop_config.py` (add field after `sandbox_mode`, ~line 93)
- Modify: `agent/config_loader.py:304-360` (read the key; pass it to `AgentConfig`)
- Modify: `config.example.yaml` (Tools section, after `sandbox_mode`)
- Modify: `tools/bash/_bash.py:84-139`
- Test: `tests/test_config_loader.py`, `tests/test_bash_tools.py`

#### Tests
- `tests/test_config_loader.py` — `code_mode` defaults to True from file, False when set, False
  on a bare `AgentConfig()`.
- `tests/test_bash_tools.py` — `run_structured` exit 0, non-zero exit, timeout
  (`timed_out=True`, `exit_code=None`); `run` text unchanged.

- [ ] **Step 1: Write the failing tests**

Follow the existing loader-test pattern in `tests/test_config_loader.py` (find how other
top-level keys such as `sandbox_mode` are tested and copy it). Add to `tests/test_bash_tools.py`:

```python
class TestBashStructured:
    def test_success(self, tmp_path):
        r = BashTool(cwd=tmp_path).run_structured("echo hi")
        assert r["exit_code"] == 0 and "hi" in r["output"] and r["timed_out"] is False

    def test_nonzero_exit_is_data_not_error(self, tmp_path):
        r = BashTool(cwd=tmp_path).run_structured("exit 3")
        assert r["exit_code"] == 3 and r["timed_out"] is False

    def test_timeout(self, tmp_path):
        cmd = f'"{sys.executable}" -c "import time; time.sleep(5)"'
        r = BashTool(cwd=tmp_path).run_structured(cmd, timeout=1)
        assert r["timed_out"] is True and r["exit_code"] is None and r["killed"] is False
```

- [ ] **Step 2: Run them to verify they fail**

Run: `<test command> tests/test_bash_tools.py tests/test_config_loader.py -k "Structured or code_mode"`
Expected: FAIL (`AttributeError: run_structured`, missing `code_mode`).

- [ ] **Step 3: Implement**

`agent/_loop_config.py`:
```python
    # Code mode: register the `code` tool (scripts chaining tools). The loader defaults
    # the config-file value to True; the dataclass default keeps tests/benchmarks unchanged.
    code_mode: bool = False
```
`agent/config_loader.py`: `code_mode = bool(raw.get("code_mode", True))` next to
`sandbox_mode`, and `code_mode=code_mode` in the `AgentConfig(...)` call. Global only — do not
read it from the model entry.

`config.example.yaml`:
```yaml
code_mode: true      # true  = add the `code` tool: the agent can run one Python script that
                     #         chains read/grep/find/write/edit/copy/bash calls.
                     # false = normal tools only.
```

`tools/bash/_bash.py`: move the body of `run` into `run_structured`, returning the dict; keep
the user-kill and timeout cases distinct:
```python
    def run(self, command: str, timeout: int | None = None) -> str:
        r = self.run_structured(command, timeout)
        if r["timed_out"]:
            return r["output"]          # already the "[timed out after …]" message
        if r["killed"]:
            out = r["output"]
            return f"{out}\n[killed by user]" if out else "[killed by user]"
        return _format_result(r["output"], r["exit_code"], command)
```
On timeout, `output` holds the existing `[timed out after …]` message. The `code` tool
(Subtask 3) passes the dict to the script unchanged.

- [ ] **Step 4: Run the tests — all of `tests/test_bash_tools.py` and the loader tests pass**

- [ ] **Step 5: Return for review**

---

### Subtask 2: Child runner and tool stubs
**Goal:** The child-side runner (`_runner.py`) and the stub generator (`_stubs.py`), both
testable without the parent.

**Requirements:** spec R5, R8, design "Protocol" and "Wrapping".

**Acceptance Criteria:**
- `wrap_script(src)` returns a code object defining `__dagi_main__`; a top-level `return 5`
  works; a multi-line string literal keeps its exact content; a `SyntaxError` names
  `<script>` and the line.
- `render_return(None) is None`; strings pass through; dicts/lists become indented JSON;
  unserialisable objects fall back to `repr`.
- `format_error(exc)` contains only `<script>` frames, with source lines shown.
- `tool_stub(schema)` renders `tools.read(path: str, offset: int = None) -> str`; `bash`
  renders `-> dict` with the key list.

**Files:**
- Create: `tools/code/__init__.py` (re-export `CodeTool` in Subtask 3; empty docstring now)
- Create: `tools/code/_runner.py`
- Create: `tools/code/_stubs.py`
- Test: `tests/test_code_runner.py`

#### Tests
`tests/test_code_runner.py` — `wrap_script`, `render_return`, `format_error`, `tool_stub`
unit tests; one end-to-end test that runs `_runner.py` as a subprocess with a hand-written
parent loop (send script, answer one `call`, read `done`).

- [ ] **Step 1: Write the failing tests**

```python
from tools.code._runner import wrap_script, render_return, format_error
from tools.code._stubs import tool_stub

def _run(src):
    ns = {}
    exec(wrap_script(src), ns)
    return ns["__dagi_main__"]()

def test_top_level_return():
    assert _run("x = 2\nreturn x * 3") == 6

def test_multiline_string_kept_exact():
    assert _run('s = """a\n  b\n"""\nreturn s') == "a\n  b\n"

def test_syntax_error_names_script():
    with pytest.raises(SyntaxError) as e:
        wrap_script("def (:")
    assert e.value.filename == "<script>"

def test_format_error_only_script_frames():
    try:
        _run("def f():\n    raise ValueError('boom')\nf()")
    except ValueError as exc:
        text = format_error(exc)
    assert "boom" in text and "<script>" in text and "_runner.py" not in text

def test_render_return():
    assert render_return(None) is None
    assert render_return("x") == "x"
    assert render_return({"a": 1}) == '{\n  "a": 1\n}'
    assert render_return(object()).startswith("<object")

def test_stub():
    schema = {"function": {"name": "read", "parameters": {"type": "object",
        "properties": {"path": {"type": "string"}, "offset": {"type": "integer"}},
        "required": ["path"]}}}
    assert tool_stub(schema) == "tools.read(path: str, offset: int = None) -> str"
```
Plus the subprocess round trip (send `{"script": "return tools.echo(x='héllo ✓')"}`, reply
`{"ok": true, "result": "héllo ✓"}`, expect `done.return == "héllo ✓"`). Open the pipes with
`encoding="utf-8"`.

- [ ] **Step 2: Run to verify they fail** (`ModuleNotFoundError: tools.code`)

- [ ] **Step 3: Implement `_runner.py`**

```python
"""tools/code/_runner.py — child process of the `code` tool.

Runs one model-written script; every tools.<name>(**args) call is sent to the parent.
Protocol, one JSON object per line, UTF-8:
  parent → stdin   {"script": str}                         (first line)
  child  → rpc     {"type": "call", "name": str, "args": dict}
  parent → stdin   {"ok": bool, "result": any, "error": str | None}
  child  → rpc     {"type": "done", "output": str, "return": str | None, "error": str | None}
The rpc channel is a private dup of the original stdout; fd 1 then points at stderr so
output from child processes cannot corrupt the protocol.
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
    """Compile *src* as the body of __dagi_main__ (AST-level: string literals stay exact)."""
    body = ast.parse(src, filename=_FILENAME).body
    module = ast.parse(_TEMPLATE)
    module.body[0].body = body or [ast.Pass()]
    ast.fix_missing_locations(module)
    lines = src.splitlines(keepends=True)
    linecache.cache[_FILENAME] = (len(src), None, lines, _FILENAME)
    return compile(module, _FILENAME, "exec")
```
Note: the template's `def` line is line 1 and the moved body keeps its original line numbers,
so tracebacks point at the model's own lines. Verify this in the `format_error` test.

```python
def render_return(value) -> str | None:
    if value is None or isinstance(value, str):
        return value
    try:
        return json.dumps(value, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(value)


def format_error(exc: BaseException) -> str:
    """Traceback limited to frames from the script itself."""
    te = traceback.TracebackException.from_exception(exc)
    te.stack = traceback.StackSummary.from_list(
        [f for f in te.stack if f.filename == _FILENAME]
    )
    return "".join(te.format()).rstrip()


class _Tools:
    """`tools` object in the script namespace: attribute access → RPC call."""

    def __init__(self, rpc_out, rpc_in):
        self._out, self._in = rpc_out, rpc_in

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
    namespace = {"tools": tools, "ToolError": ToolError, "__name__": "__dagi_script__"}
    try:
        exec(wrap_script(src), namespace)
        return render_return(namespace["__dagi_main__"]()), None
    except BaseException as exc:  # noqa: BLE001 - SystemExit/KeyboardInterrupt are script errors too
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
```
Caveat to check during implementation: after `sys.stdout = captured`, a script writing to
`sys.__stdout__` writes to fd 1, which is now stderr — that is the intended "stray" path.

- [ ] **Step 4: Implement `_stubs.py`**

```python
"""tools/code/_stubs.py — Python-style signatures for tools callable from a script."""
from __future__ import annotations

_PY_TYPES = {"string": "str", "integer": "int", "number": "float", "boolean": "bool",
             "array": "list", "object": "dict"}
BASH_RETURN = "dict  # {output: str, exit_code: int | None, timed_out: bool, killed: bool}"


def tool_stub(schema: dict) -> str:
    fn = schema["function"]
    params = fn.get("parameters", {})
    required = set(params.get("required", []))
    props = params.get("properties", {})
    parts = [f"{n}: {_PY_TYPES.get(p.get('type'), 'object')}" for n, p in props.items()
             if n in required]
    parts += [f"{n}: {_PY_TYPES.get(p.get('type'), 'object')} = None"
              for n, p in props.items() if n not in required]
    returns = BASH_RETURN if fn["name"] == "bash" else "str"
    return f"tools.{fn['name']}({', '.join(parts)}) -> {returns}"
```

- [ ] **Step 5: Run `tests/test_code_runner.py` — all pass**

- [ ] **Step 6: Return for review**

---

### Subtask 3: `CodeTool` (parent side)
**Goal:** Spawn the runner, serve calls through the registry, enforce timeout/kill, format the
result.

**Requirements:** spec R3, R4, R6, R7, R8, R9.

**Acceptance Criteria:** every test below passes; `_code.py` ≤500 lines, each function within
the global limits.

**Files:**
- Create: `tools/code/_code.py`
- Modify: `tools/code/__init__.py` (`from tools.code._code import CodeTool`)
- Modify: `agent/registry.py` (add `is_available(name) -> bool`: registered and not denied)
- Test: `tests/test_code_tool.py`

#### Tests
Build a real `ToolRegistry` in `tmp_path` with `ReadTool`, `WriteTool`, `EditTool`, `BashTool`
(same constructors as `agent/tools.py:_register_file_tools`), then `CodeTool(registry=reg,
cwd=tmp_path)`. One test each:
- `print` output and `return` value appear; header is `[code: completed in …]`.
- grep-free round trip: `write` then `read` the same file inside one script.
- `edit` failure (`oldText` not found) raises `ToolError`; catching it lets the script continue.
- Unknown / disallowed tool (`tools.ask_user(...)`, `tools.code(...)`) → `ToolError` listing
  the available tools.
- Denied tool (`reg.deny({"bash"})`) → `ToolError`.
- Side-effect result: register a fake tool named `read` returning
  `ToolResult("img", side_effect=SideEffect.ATTACH_IMAGE)` → `ToolError` mentioning a direct call.
- `bash` returns the dict; `exit 3` gives `exit_code == 3` with no error.
- Exception after two `write` calls → `[code: failed …]`, traceback, and
  `[already applied] write(path=a.txt), write(path=b.txt)`.
- `SyntaxError` → `[code: failed …]` with the line number.
- Timeout: `while True: pass` with `timeout=2` → `[code: timed out after 2s]` within ~5s.
- `force_kill()` from a `threading.Timer(1, tool.force_kill)` during `time.sleep(30)` →
  `[code: killed by user]` within ~5s.
- Stray output: `import os; os.system("echo stray")` → `[stray output]` contains `stray`;
  the script still completes.
- Unicode: `write` + `read` + `print` of `"héllo ✓"` round-trips.
- Description contains a stub line for each available tool and none for denied ones.

- [ ] **Step 1: Write the failing tests** (as listed; keep each under ~15 lines)

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Implement**

Shape of `_code.py` (split to stay within complexity limits):
```python
CODE_TOOLS = ("read", "grep", "find", "write", "edit", "copy", "bash")
MUTATING = frozenset({"write", "edit", "copy", "bash"})
ERROR_PREFIXES = ("Error", "Access denied", "[paused]")
_RUNNER = Path(__file__).with_name("_runner.py")
_KEY_ARGS = ("path", "command", "pattern", "source")


@dataclass
class _Run:
    """State of one script execution."""
    ledger: list[str] = field(default_factory=list)   # mutating calls that succeeded
    stray: list[str] = field(default_factory=list)    # stderr lines
    done: dict | None = None
    status: str = "completed"                         # completed|failed|timed out|killed|crashed


class CodeTool(BaseTool):
    name = "code"
    _parameters = {
        "type": "object",
        "properties": {
            "script": {"type": "string", "description": "Python source; may use top-level return"},
            "timeout": {"type": "integer", "description": "Seconds (default 300)"},
        },
        "required": ["script"],
    }
    DEFAULT_TIMEOUT = 300.0

    def __init__(self, registry: ToolRegistry, cwd: Path = Path(".")):
        ...  # registry, cwd, threading.Lock, _proc=None, _killed=False

    @property
    def description(self) -> str:
        """Rules + one stub per tool available right now (computed per access, never stale)."""

    def run(self, script: str, timeout: int | None = None) -> str: ...
    def force_kill(self) -> bool: ...   # mirror BashTool.force_kill
```
Helpers:
- `_spawn()` — `subprocess.Popen([sys.executable, "-u", str(_RUNNER)], stdin/stdout/stderr=PIPE,
  cwd=str(self.cwd), encoding="utf-8", errors="replace",
  env={**os.environ, "PYTHONIOENCODING": "utf-8"}, **_process_group_kwargs())`. Import
  `_process_group_kwargs` from `tools.bash._bash` (rename to a public helper only if review asks).
- `_start_readers(proc, run)` — daemon thread putting each stdout line into a `queue.Queue`
  then `None` at EOF; daemon thread appending stderr lines to `run.stray`.
- `_serve(proc, q, run, deadline)` — loop: `q.get(timeout=max(0, deadline - now))`;
  `queue.Empty` → `status = "timed out"`, return; `None` → `"killed"` if `self._killed` else
  `"crashed"`, return; `call` → write `json.dumps(self._dispatch(...)) + "\n"` to stdin and
  flush (catch `BrokenPipeError`/`OSError` → treat like EOF); `done` → store, set `"failed"`
  if `done["error"]`, return.
- `_dispatch(name, args, run) -> dict` — R3/R4 checks in order: allowed and
  `registry.is_available(name)`; `bash` → `tool.run_structured(**args)`; a `killed` result
  returns `{"ok": False, "error": "[killed by user]"}` (the code process is killed next anyway);
  otherwise `registry.dispatch(name, args)`; reject side effects; unwrap `ToolResult`; list →
  as-is; error-prefix strings → `{"ok": False, "error": text}`. Catch `TypeError` from bad
  kwargs → `{"ok": False, "error": f"Error: {exc}"}`. On success of a `MUTATING` call, append
  `f"{name}({key}={value[:60]})"` to `run.ledger` using the first present key in `_KEY_ARGS`.
- `finally` in `run`: if the process is alive, `kill_process_tree(proc)`; `proc.wait(5)`
  guarded by `TimeoutExpired`; clear `self._proc` under the lock.
- `_format(run, elapsed, limit) -> str` — R6 order; header
  `f"[code: {status} in {elapsed:.1f}s]"`, except `timed out after {limit:g}s`; include
  `[already applied]` only when status ≠ completed and the ledger is non-empty; return
  `"[code: completed in …]\n[no output]"` when every section is empty.

Description text (keep it short — it is in every request):
```
Run a Python script that chains dagi tools in one call. Use it for several mechanical steps
whose intermediate results you do not need to read (search then read matches, the same edit
across files, run tests and extract failures). Only what the script prints or returns comes
back, so filter large results inside the script. Call tools as tools.<name>(**args); a failed
call raises ToolError (catch it to continue). Calls are real and are not undone if the script
fails later. Use tools.* for files and commands, not open()/subprocess. No input().
Runs in the project directory with dagi's Python. Available:
  <one stub per line>
```

- [ ] **Step 4: Run `tests/test_code_tool.py` and `tests/test_code_runner.py` — all pass**

- [ ] **Step 5: Return for review**

---

### Subtask 4: Registration, interrupt and GUI label
**Goal:** Wire `CodeTool` into the main registry behind `code_mode` and into ESC interrupt.

**Requirements:** spec R2, R7.

**Acceptance Criteria:**
- With `code_mode` off, every existing contract test passes unchanged.
- With `code_mode` on, `code` appears immediately after `bash` and nowhere else changes.
- `AgentLoop.interrupt()` calls `force_kill()` on a registered `code` tool, after `bash`.
- `tool_label("code", ...)` returns a label.

**Files:**
- Modify: `agent/tools.py:145-152` (`_register_file_tools` gets the config; register after bash)
- Modify: `agent/loop.py:317-321`
- Modify: `pyside_gui/tool_labels.py` (`"code": ("Ran a script", ())`)
- Test: `tests/test_tool_registry_contract.py`, `tests/test_interrupt.py`,
  the existing tool-label tests (find with `grep -l tool_label tests/`)

#### Tests
- Contract: set `cfg.code_mode = False` in `_config` (Review Focus 4); add
  `test_code_mode_inserts_code_after_bash` using `_config(tmp_path, code_mode=True)` and
  asserting `names[:8] == _FILE_TOOLS + ["code"]` and the rest equals the default case.
- Interrupt: a loop whose registry holds mocks for `bash` and `code`; after `interrupt()`, both
  `force_kill` mocks were called, bash first (use a shared `MagicMock` parent with
  `attach_mock` and check `mock_calls` order). Follow the fixtures already in
  `tests/test_interrupt.py`.

- [ ] **Step 1: Write the failing tests**
- [ ] **Step 2: Run to verify they fail**
- [ ] **Step 3: Implement**

```python
    reg.register(BashTool(cwd=cwd))
    if config is not None and config.code_mode:
        from tools.code import CodeTool
        reg.register(CodeTool(registry=reg, cwd=cwd))
```
`loop.interrupt()` after the bash kill:
```python
        code = self.registry._tools.get("code")
        if code is not None:
            code.force_kill()
```
- [ ] **Step 4: Run the full suite** — only the baseline failures remain.
- [ ] **Step 5: Return for review**

---

### Subtask 5: Docs and end-to-end check
**Goal:** Document code mode and verify it in the real app.

**Requirements:** spec A3; `CLAUDE.local.md` (keep `README.md` and `TODO.md` current).

**Files:**
- Modify: `README.md` (How It Works: a short "Code mode" paragraph — what it is, the config
  switch, callable tools, no sandbox, not undone on failure)
- Modify: `TODO.md` (mark v1 done; add follow-ups: `only` mode, per-model switch, nested tool
  cards/events, read-only parallel calls, benchmark `on` vs `off` in `benchmarks/dagi_eval`)
- Modify: `AGENTS.md` only if it lists tools or config keys (check; do not add otherwise)

- [ ] **Step 1: Write the docs**
- [ ] **Step 2: Manual run (main agent, not a worker)** — launch the GUI with
  `code_mode: true`; ask for "count the `def ` lines in every file under agent/ and show the top
  5". Expect one `code` call. Then run a script with `time.sleep(60)`, press ESC, expect
  `[code: killed by user]` within a few seconds. Record both in Verification.
- [ ] **Step 3: Return for review**

---

## Workspace
- **Branch:** `task/code-mode`
- **Parent:** `main`
- **Starting commit:** `c5c4759`
- **Task folder:** `wiki/tasks/2026-10-07_code-mode/`

## Overall Status
In Progress — Subtask 1 complete.

## Notes
- `ToolRegistry.dispatch` catches every exception into `"Error: …"`, so `ToolError` detection by
  prefix covers both tool-reported and crashed calls.
- Subagent registries are built by `agent/subagent_tools.py:build_subagent_registry`, not
  `create_tool_registry`, so they never get `CodeTool`. Inherited children copy the parent's
  schema list; `InheritedSchemaTool` blocks `code` because it is not in the child's allowed set.
- `config.yaml` is untracked and per-user; only `config.example.yaml` is edited.
- `_announce_call` reads `tool_obj.description`; a property works there.

## Open Issues
(none) — Resolved 2026-10-07: loader default `true` confirmed; only an explicit
`code_mode: false` turns it off, and off means the `code` tool is simply not registered.

## Attempts and Resolutions
- **Subtask 1, attempt 1:** every test errored at setup — the autouse RAM watchdog in
  `tests/conftest.py` trips at 85% system RAM and the machine sat at 84–86% (Chrome, VS Code).
  -> targeted runs use `--noconftest` (the only other autouse fixture isolates the memory root,
  unused by these tests). Under `--noconftest`, two `tests/test_interrupt.py` tests fail on
  `main` too, so they are not regressions. The full suite still runs with the watchdog.

## Verification
- Full suite: only baseline failures remain.
- `tests/test_code_runner.py`, `tests/test_code_tool.py`, contract and interrupt tests pass.
- Manual GUI run per Subtask 5.

## Next Action
Get approval for the spec and plan and for creating `task/code-mode`; then commit both and start
Subtask 1.
