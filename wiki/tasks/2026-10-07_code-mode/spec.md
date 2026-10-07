# Spec — Code Mode v1 (`code` tool)

## 1. Document status
| Field | Value |
|---|---|
| Owner | Admiral; drafted by Claude |
| Version | v1, 2026-10-07 |
| Status | **Draft — in review** |
| Branch | `task/code-mode` from `main@c5c4759` (not yet created) |
| Related | Prior art: pi codemode (https://pi.dev/docs/latest/codemode) |

## 2. Summary and problem
Today every dagi tool call is one model step: the model emits a call, the harness runs it, the
full result enters the context, and the model is called again. Multi-step mechanical work
(grep → read each hit → count something; apply one edit to ten files; run tests → pick out the
failures) costs one request per call, and every intermediate result is paid for in context
tokens even when the model only needs a summary.

`bash: python -c ...` does not solve this. A plain subprocess bypasses everything the registry
adds: the `_path_guard` sandbox roots, the read tool's chunking/Office/image handling, the
output filter, ESC force-kill, and dagi's own tool semantics.

**Outcome:** a `code` tool. The model writes one Python script; the script calls dagi tools as
`tools.<name>(**args)`; each call is proxied back to the parent's `ToolRegistry`, so it runs
exactly as a direct call would. Only what the script prints or returns enters the context.

## 3. Goals, scope, non-goals
**Goals**
- G1: The model can chain `read`, `grep`, `find`, `write`, `edit`, `copy` and `bash` calls in
  one `code` call, with the same path guard and behaviour as direct calls.
- G2: Only the script's printed output and return value come back, through the existing
  output filter (truncation + spill to `.dagi/hash_cache/tool_output`).
- G3: A failing script reports its partial output, the traceback, and every mutating call that
  already ran (real calls are never rolled back).
- G4: ESC interrupt and a timeout both kill the script's process tree.
- G5: One global config switch, `code_mode: true|false`. The file default is `true`
  ("ship as on": `code` sits alongside the normal tools, which stay available).

**Non-goals (v1)**
- No sandbox. The script is ordinary Python and can call `open()`/`subprocess` directly; this
  matches the existing `bash` tool's posture. The description steers it to `tools.*`.
- No `only` mode (normal tools hidden). No per-model switch.
- No parallel tool calls inside a script; calls run one at a time.
- No state persisted between scripts (use files).
- No nested tool cards in the GUI/TUI and no new session event types: the transcript shows one
  `code` call and one result. Nested calls appear only in the result's summary lines.
- No `code` tool in subagent registries.

## 4. Requirements
- **R1 Config.** `AgentConfig.code_mode: bool = False` (dataclass default keeps tests and
  benchmarks unchanged). `config_loader` reads top-level `code_mode`, default `True`.
  `config.example.yaml` documents it.
- **R2 Registration.** When `config is not None and config.code_mode`, `create_tool_registry`
  registers `CodeTool` immediately after `bash`. It is subject to `tools` / `disabled_tools`
  like any tool. With `code_mode` off, the tool list and order are byte-identical to today
  (pinned by `tests/test_tool_registry_contract.py`).
- **R3 Callable tools.** Exactly `read, grep, find, write, edit, copy, bash`, minus any not
  registered or denied in the current registry. Any other name raises `ToolError` in the
  script naming the available tools. `code` itself is never callable (no recursion).
- **R4 Results in the script.**
  - `bash` returns a dict `{"output": str, "exit_code": int | None, "timed_out": bool, "killed": bool}`.
    A non-zero exit is **not** an error.
  - Every other tool returns its string result (a list result arrives as a JSON list).
  - A result starting with `Error`, `Access denied` or `[paused]` raises `ToolError(<text>)`.
  - A `ToolResult` with any `side_effect` (e.g. `read` on an image → `ATTACH_IMAGE`) raises
    `ToolError` telling the model to make that call directly.
- **R5 Script semantics.** Runs with dagi's interpreter (`sys.executable`) in the project
  cwd. Top-level `return <value>` is allowed. `print` (stdout and stderr) is captured. Output
  written to file descriptor 1 by child processes is captured separately as stray output.
  `ToolError` is in the script namespace so it can be caught.
- **R6 Result format.** One string, in this order, empty sections omitted:
  `[code: completed in 1.2s]` (or `failed` / `timed out after Ns` / `killed by user` /
  `runner crashed`), captured output, `[return]` + value, `[error]` + traceback limited to
  script frames, `[stray output]`, and on any non-success
  `[already applied] edit(path=a.py), bash(command=pytest -q)`.
  A dict/list return value is rendered as indented JSON.
- **R7 Timeout and kill.** `timeout` parameter (seconds, default 300). On expiry the process
  tree is killed. `AgentLoop.interrupt()` force-kills a running `code` tool after `bash`.
- **R8 Tool description.** Generated at access time from the live registry: usage rules plus
  one Python-style stub per callable tool, e.g.
  `tools.read(path: str, offset: int = None, limit: int = None) -> str`.
- **R9 Encoding.** UTF-8 on every pipe regardless of the Windows code page.

## 5. Design
```
model ──code(script)──▶ CodeTool.run  (agent loop thread)
                         │ Popen([sys.executable, "-u", tools/code/_runner.py])
                         │ stdin  ◀── {"script"} then one reply per call
                         │ rpc fd ──▶ {"type":"call",name,args} … {"type":"done",…}
                         │ stderr ──▶ stray output (fd 1 is redirected to fd 2 in the child)
                         ▼
             registry checks → tool.run / BashTool.run_structured → reply
```
- **Protocol:** newline-delimited JSON. The child duplicates its original stdout as a private
  RPC channel, then points fd 1 at fd 2 so nothing a grandchild prints can corrupt the protocol.
- **Wrapping:** the script is parsed with `ast.parse` and its body moved into
  `def __dagi_main__():` at AST level. No textual re-indentation, so multi-line strings stay
  intact. A consequence: top-level names are function locals (`global` statements are not
  supported).
- **Threads:** two reader threads (RPC lines → queue; stderr → buffer). The loop thread serves
  calls and enforces the deadline between messages. A long nested call (e.g. `bash` with its
  own timeout) can overrun the deadline; the deadline is checked when it returns.
- **Files:** `tools/code/{__init__,_code,_runner,_stubs}.py`.

## 6. Risks
| Risk | Mitigation |
|---|---|
| Model writes scripts that bypass `tools.*` | Description rule; same exposure as `bash` today |
| Half-applied edits after an exception | `[already applied]` ledger (R6) |
| Small models write broken scripts | `code_mode: false`; normal tools remain available |
| Tool order change invalidates warm cache | Only when enabled; position pinned by contract test |
| Inherited subagents see the `code` schema | `InheritedSchemaTool` blocks it (not in child's allowed set) |

## 7. Acceptance
- A1: All new tests pass; the full suite is at or above the baseline count.
- A2: With `code_mode: false`, the registry contract tests pass unchanged.
- A3: Manual GUI run: a two-step task (grep + read) completes in one `code` call; ESC during
  `time.sleep(60)` in a script returns `[code: killed by user]` promptly.
