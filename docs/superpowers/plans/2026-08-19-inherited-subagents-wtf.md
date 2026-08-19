# Inherited Subagents and `/wtf` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make live DAGI subagents inherit the parent's cache-compatible request prefix and add a
TUI `/wtf [description]` command that saves an isolated diagnostic report under `.dagi/errors`.

**Architecture:** A loop-owned context provider captures either the exact request that spawned a
typed subagent or a stable idle/paused surface for `/wtf`. The subprocess retains the inherited
model, messages, and tool schemas, appends one child task, enforces preset access through
schema-preserving dispatch adapters, and writes validated final assistant text as its handoff.

**Tech Stack:** Python 3.11+, OpenAI-compatible Chat Completions, append-only `SessionLog`, typed
subprocess subagents, Textual TUI, pytest, PyYAML.

**Spec:** `docs/superpowers/specs/2026-08-19-inherited-subagents-wtf-design.md`

## Global Constraints

- Use `conda run -n dagi python` for every Python or pytest command.
- Never invoke `benchmarks/dagi_eval` with its default `agent` solver or any real model.
- Use TDD: add a focused failing test, observe the intended failure, implement minimally, rerun.
- Keep functions at or below 100 lines, cyclomatic complexity at or below 8, lines at or below
  100 characters, and new files at or below 500 lines.
- The inherited child request must add no provider-visible tool schema and must retain inherited
  schema order.
- Tool access is enforced by dispatch; prompt instructions are not a security boundary.
- `/wtf` is TUI-only in this plan and must never apply its suggested fix automatically.
- Existing parent message dictionaries are immutable; only the successful `/wtf` command reference
  may be appended.
- Standalone `run_subagent()` calls without a live context provider retain fresh-mode behavior.
- Compact's version-1 inherited single-call behavior remains backward compatible.
- Remain on `dagi/wtf-inherited-subagents`; do not merge, switch away, or delete the branch.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `agent/parent_context.py` | Immutable parent-fork types and version-2 context serialization. |
| `agent/inherited_registry.py` | Preserve inherited schemas while delegating or blocking calls. |
| `agent/wtf_report.py` | Validate and parse the three-section `/wtf` report. |
| `agent/wtf.py` | Orchestrate diagnosis, atomic acceptance, and command-reference append. |
| `agent/loop.py` | Capture request identity and expose safe spawn/stable fork checkpoints. |
| `agent/tools.py` | Thread the parent context provider into loop-owned tool instances. |
| `agent/subagent_tools.py` | Build allowed implementations and discover context-aware wrappers. |
| `agent/registry.py` | Expose exact-name lookup needed by inherited schema adapters. |
| `tools/subagent_api.py` | Select inherited/fresh execution and manage fork-context handoff. |
| `tools/subagent_main.py` | Run generic inherited children and write final-response handoffs. |
| `tools/_subagent_runner.py` | Preserve context files across timeout and clean terminal paths. |
| `.dagi/subagents/*/main.py` | Forward the parent context provider from every typed spawn tool. |
| `.dagi/subagents/wtf/` | Define diagnostic prompt, read-only access, and report contract. |
| `tui/app.py`, `tui/commands.py`, `tui/utils.py` | Intercept, run, and render `/wtf`. |

---

### Task 1: Define the version-2 parent-fork contract

**Files:**
- Create: `agent/parent_context.py`
- Create: `tests/test_parent_context.py`
- Modify: `tools/subagent_api.py:47-104`

**Interfaces:**
- Produces: `ForkMode = Literal["spawn", "stable"]`.
- Produces: `ParentFork(branch_id, parent_cut_seq, parent_surface_generation, request)`.
- Produces: `ParentContextProvider(capture_fork, get_surface_generation)`.
- Produces: `build_fork_context_v2(fork, child_type, allowed_tools) -> dict[str, Any]`.
- Preserves: existing `build_fork_context()` version-1 output for compact.

- [ ] **Step 1: Write failing contract tests**

```python
def test_v2_context_keeps_request_identity_and_child_policy():
    request = {
        "model": "provider/model",
        "messages": [{"role": "system", "content": "rules"}],
        "tools": [{"type": "function", "function": {"name": "read"}}],
        "parallel_tool_calls": False,
        "extra_body": {"cache_prompt": True},
        "base_url": "https://provider.test/v1",
    }
    fork = ParentFork("worker_ab12", 12, 3, request)
    result = build_fork_context_v2(fork, "worker", ["read"])
    assert result["version"] == 2
    assert result["request"] == request
    assert result["child"] == {"type": "worker", "allowed_tools": ["read"]}


def test_v2_context_excludes_credentials():
    request = {"model": "m", "messages": [], "tools": [], "api_key": "secret"}
    fork = ParentFork("worker_ab12", 1, 0, request)
    with pytest.raises(ValueError, match="credential field"):
        build_fork_context_v2(fork, "worker", [])
```

- [ ] **Step 2: Run the tests and confirm the contract is absent**

Run: `conda run -n dagi python -m pytest tests/test_parent_context.py -v`

Expected: FAIL during collection because `agent.parent_context` does not exist.

- [ ] **Step 3: Implement immutable types and strict serialization**

```python
ForkMode = Literal["spawn", "stable"]


@dataclass(frozen=True, slots=True)
class ParentFork:
    branch_id: str
    parent_cut_seq: int
    parent_surface_generation: int
    request: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ParentContextProvider:
    capture_fork: Callable[[str, ForkMode], ParentFork]
    get_surface_generation: Callable[[], int]


def build_fork_context_v2(
    fork: ParentFork,
    child_type: str,
    allowed_tools: list[str],
) -> dict[str, Any]:
    forbidden = {"api_key", "authorization", "credentials"} & set(fork.request)
    if forbidden:
        raise ValueError(f"credential field forbidden in fork context: {sorted(forbidden)}")
    return {
        "version": 2,
        "branch": {
            "id": fork.branch_id,
            "parent_cut_seq": fork.parent_cut_seq,
            "parent_surface_generation": fork.parent_surface_generation,
        },
        "request": copy.deepcopy(fork.request),
        "child": {
            "type": child_type,
            "allowed_tools": list(allowed_tools),
        },
    }
```

- [ ] **Step 4: Run focused and existing version-1 tests**

Run: `conda run -n dagi python -m pytest tests/test_parent_context.py tests/test_subagent_api.py -v`

Expected: PASS, including existing version-1 compact structure tests.

- [ ] **Step 5: Commit the contract**

```bash
git add agent/parent_context.py tools/subagent_api.py tests/test_parent_context.py
git commit -m "feat: define inherited subagent context contract"
```

---

### Task 2: Build a schema-preserving access-controlled registry

**Files:**
- Create: `agent/inherited_registry.py`
- Create: `tests/test_inherited_registry.py`
- Modify: `agent/registry.py:1-38`

**Interfaces:**
- Consumes: inherited OpenAI tool schemas and an allowed `ToolRegistry`.
- Produces: `build_inherited_registry(schemas, allowed_registry, allowed_names,
  subagent_type) -> ToolRegistry`.
- Produces: `ToolRegistry.get(name: str) -> BaseTool | None`.

- [ ] **Step 1: Write failing identity and denial tests**

```python
def test_inherited_registry_preserves_schema_order_and_content():
    schemas = [_schema("write"), _schema("read")]
    allowed = ToolRegistry()
    allowed.register(EchoTool("read"))
    result = build_inherited_registry(schemas, allowed, {"read"}, "memory-query")
    assert result.get_openai_tools_list() == schemas


def test_disallowed_and_missing_tools_return_blocked_error():
    schemas = [_schema("write"), _schema("read")]
    result = build_inherited_registry(schemas, ToolRegistry(), {"read"}, "wtf")
    assert result.dispatch("write", {}) == (
        "Error: Access blocked for tool 'write' in subagent 'wtf'. "
        "Allowed tools: read"
    )
    assert result.dispatch("read", {}).startswith("Error: Access blocked")
```

- [ ] **Step 2: Run tests and observe the missing builder**

Run: `conda run -n dagi python -m pytest tests/test_inherited_registry.py -v`

Expected: FAIL during collection because `agent.inherited_registry` does not exist.

- [ ] **Step 3: Implement schema-bound delegation**

```python
class InheritedSchemaTool(BaseTool):
    def __init__(self, schema_data, delegate, allowed_names, subagent_type):
        self._schema_data = copy.deepcopy(schema_data)
        self.name = schema_data["function"]["name"]
        self.description = schema_data["function"].get("description", "")
        self._parameters = schema_data["function"].get("parameters", {})
        self._delegate = delegate
        self._allowed_names = set(allowed_names)
        self._subagent_type = subagent_type

    def schema(self) -> dict:
        return copy.deepcopy(self._schema_data)

    def run(self, **kwargs) -> str | list:
        target = self._delegate.get(self.name)
        if self.name not in self._allowed_names or target is None:
            names = ", ".join(sorted(self._allowed_names)) or "none"
            return (
                f"Error: Access blocked for tool '{self.name}' in subagent "
                f"'{self._subagent_type}'. Allowed tools: {names}"
            )
        return target.run(**kwargs)
```

Register one adapter per inherited schema without filtering or reordering.

- [ ] **Step 4: Run registry tests**

Run: `conda run -n dagi python -m pytest tests/test_inherited_registry.py tests/test_registry.py -v`

Expected: PASS.

- [ ] **Step 5: Commit access enforcement**

```bash
git add agent/inherited_registry.py agent/registry.py tests/test_inherited_registry.py
git commit -m "feat: enforce subagent access without changing schemas"
```

---

### Task 3: Capture spawn and stable forks in `AgentLoop`

**Files:**
- Modify: `agent/loop.py:300-430, 900-930`
- Modify: `agent/parent_context.py`
- Test: `tests/test_agent_loop.py`
- Test: `tests/test_parent_context.py`

**Interfaces:**
- Consumes: `ParentFork` and `ForkMode` from Task 1.
- Produces: `AgentLoop.capture_parent_fork(branch_id, mode) -> ParentFork`.
- Produces: `AgentLoop.parent_context_provider -> ParentContextProvider`.
- Produces: `AgentLoop.wait_for_pause_checkpoint(timeout: float) -> bool`.
- Adds snapshot metadata: `parent_cut_seq` and `parent_surface_generation`.

- [ ] **Step 1: Write failing spawn-boundary tests**

```python
def test_spawn_fork_uses_request_before_assistant_tool_call(loop):
    loop._last_request_snapshot = {
        **REQUEST_SNAPSHOT,
        "messages": [{"role": "user", "content": "parent task"}],
        "parent_cut_seq": 7,
        "parent_surface_generation": 2,
    }
    fork = loop.capture_parent_fork("worker_ab12", "spawn")
    assert fork.request["messages"] == [{"role": "user", "content": "parent task"}]
    assert all("tool_calls" not in message for message in fork.request["messages"])
    assert loop.log.branch_event("worker_ab12").data["parent_cut_seq"] == 7


def test_stable_fork_rejects_unsettled_paused_loop(loop):
    loop.pause()
    loop._pause_checkpoint.clear()
    assert loop.wait_for_pause_checkpoint(0.01) is False
```

- [ ] **Step 2: Verify the tests fail on missing loop interfaces**

Run: `conda run -n dagi python -m pytest tests/test_agent_loop.py tests/test_parent_context.py -v`

Expected: FAIL because the capture and checkpoint methods are absent.

- [ ] **Step 3: Extract one request-snapshot helper and record the fork cutoff**

```python
def _snapshot_request(self, messages: list[dict]) -> dict:
    return {
        "model": self.config.model,
        "messages": copy.deepcopy(messages),
        "tools": copy.deepcopy(self.registry.get_openai_tools_list()),
        "parallel_tool_calls": False,
        "extra_body": copy.deepcopy(self._extra_body),
        "base_url": self.config.base_url or "",
        "parent_cut_seq": self.log.surface.nodes[-1] if self.log.surface.nodes else 0,
        "parent_surface_generation": self.log.surface.generation,
    }
```

Use this helper at the existing provider-call site. Keep the compact serializer limited to its
existing request fields so internal cutoff metadata does not leak into provider kwargs.

- [ ] **Step 4: Add a pause checkpoint around the existing blocking wait**

```python
self._pause_checkpoint = threading.Event()

self._pause_checkpoint.set()
try:
    self._pause_event.wait()
finally:
    self._pause_checkpoint.clear()
```

`capture_parent_fork(..., "stable")` requires a set checkpoint for a live paused worker, rebuilds
messages from the stable surface, and records a non-surface `BRANCH_START`. Spawn mode copies the
frozen triggering request and its recorded cutoff.

- [ ] **Step 5: Run loop, context, and compact tests**

Run:

```powershell
conda run -n dagi python -m pytest `
  tests/test_agent_loop.py tests/test_parent_context.py `
  tests/test_compact_subagent.py tests/test_compact_integration.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit stable parent capture**

```bash
git add agent/loop.py agent/parent_context.py tests/test_agent_loop.py tests/test_parent_context.py
git commit -m "feat: capture stable parent forks for subagents"
```

---

### Task 4: Make `run_subagent()` select inherited execution

**Files:**
- Modify: `tools/subagent_api.py:120-224`
- Modify: `tools/_subagent_runner.py:20-235`
- Test: `tests/test_subagent_api.py`
- Test: `tests/test_subagent_runner.py`

**Interfaces:**
- Consumes: `ParentContextProvider` and `ForkMode`.
- Extends: `run_subagent(..., parent_context=None, fork_mode="spawn", handoff_dir=None)`.
- Preserves: explicit `fork_context_path` for compact version 1.

- [ ] **Step 1: Write failing inherited-selection tests**

```python
def test_live_parent_provider_creates_v2_context_and_forwards_it(tmp_path, monkeypatch):
    fork = ParentFork("worker_ab12", 9, 2, REQUEST_SNAPSHOT)
    provider = ParentContextProvider(
        capture_fork=Mock(return_value=fork),
        get_surface_generation=Mock(return_value=2),
    )
    captured = _capture_runner(monkeypatch, tmp_path)
    run_subagent(
        task="inspect",
        preset="worker",
        project_path=tmp_path,
        parent_context=provider,
    )
    provider.capture_fork.assert_called_once_with(
        "worker_" + captured.id_suffix,
        "spawn",
    )
    assert "--fork-context" in captured.extra_argv
    assert captured.fork_context["version"] == 2


def test_handoff_dir_places_report_under_errors(tmp_path, monkeypatch):
    result = run_subagent(
        task="diagnose",
        preset="worker",
        project_path=tmp_path,
        handoff_dir=tmp_path / ".dagi" / "errors",
        prompt="diagnose",
        tools=["read"],
    )
    assert result.handoff_path.parent == tmp_path / ".dagi" / "errors"
```

- [ ] **Step 2: Run focused API and runner tests**

Run:

```powershell
conda run -n dagi python -m pytest `
  tests/test_subagent_api.py tests/test_subagent_runner.py -v
```

Expected: FAIL because the new keyword parameters are unsupported.

- [ ] **Step 3: Implement inherited context creation and ownership**

Generate the branch id before asking the provider for a fork. Write version-2 JSON to a temporary
file, pass `--fork-context`, and transfer cleanup ownership to `_SubagentState`. Delete the file in
the API only when spawning raises before the runner registers it. Keep the file on timeout and
delete it on success, escalation, error exit, or forced terminal cleanup.

```python
if parent_context is not None:
    fork = parent_context.capture_fork(branch_id, fork_mode)
    fork_data = build_fork_context_v2(fork, subagent_type, eff_tools)
    fork_context_path = _write_fork_context(fork_data)
```

After a successful subprocess result, compare
`parent_context.get_surface_generation()` with `fork.parent_surface_generation`. Return a stale
error without handoff content when they differ.

- [ ] **Step 4: Run API and runner tests**

Run:

```powershell
conda run -n dagi python -m pytest `
  tests/test_subagent_api.py tests/test_subagent_runner.py -v
```

Expected: PASS, including timeout retention and terminal cleanup.

- [ ] **Step 5: Commit inherited API routing**

```bash
git add tools/subagent_api.py tools/_subagent_runner.py \
  tests/test_subagent_api.py tests/test_subagent_runner.py
git commit -m "feat: route live subagents through inherited contexts"
```

---

### Task 5: Run generic inherited children and write final-response handoffs

**Files:**
- Modify: `tools/subagent_main.py:120-430`
- Modify: `agent/subagent_tools.py:160-235`
- Modify: `agent/loop.py:300-390`
- Test: `tests/test_subagent_main.py`
- Test: `tests/test_inherited_registry.py`

**Interfaces:**
- Consumes: `build_inherited_registry()` from Task 2 and version-2 context from Task 1.
- Produces: `run_forked_subagent_mode(fork_context_path, task_file, handoff_path,
  project_path) -> None`.
- Produces: `_validate_final_handoff(text, required_sections) -> tuple[bool, str]`.
- Extends: `AgentLoop(..., _system_prompt_override: str | None = None)`.

- [ ] **Step 1: Write failing first-request and handoff tests**

```python
def test_generic_fork_first_request_is_prefix_plus_child_task(tmp_path, monkeypatch):
    inherited = [
        {"role": "system", "content": "parent rules"},
        {"role": "user", "content": "parent task"},
    ]
    captured = _run_generic_fork(tmp_path, monkeypatch, messages=inherited)
    assert captured.messages[:-1] == inherited
    assert "## Tool access" in captured.messages[-1]["content"]
    assert captured.tools == PARENT_TOOL_SCHEMAS


def test_generic_fork_writes_valid_final_text_without_write_handoff(tmp_path, monkeypatch):
    handoff, captured = _run_generic_fork(
        tmp_path,
        monkeypatch,
        assistant_text="## Description\nWrong path\n\n## Error Report\nEvidence\n\n"
        "## Suggested Fix\nStop",
        required_sections=["Description", "Error Report", "Suggested Fix"],
    )
    assert handoff.read_text(encoding="utf-8").startswith("## Description")
    assert all(schema["function"]["name"] != "write_handoff" for schema in captured.tools)
```

- [ ] **Step 2: Run generic fork tests and confirm main dispatch is compact-only**

Run: `conda run -n dagi python -m pytest tests/test_subagent_main.py -v`

Expected: FAIL because version 2 is routed into `run_forked_compact_mode()`.

- [ ] **Step 3: Preserve the inherited system header in `AgentLoop`**

Add `_system_prompt_override` as an internal keyword. Continue assembling normal system parts for
loop bookkeeping, then use the override as the emitted header only for inherited subprocesses.

```python
assembled_system = self._assemble_system_string(dagi_root)
system = _system_prompt_override if _system_prompt_override is not None else assembled_system
```

- [ ] **Step 4: Implement version-based subprocess dispatch**

```python
fork_context = json.loads(Path(args.fork_context).read_text(encoding="utf-8"))
if fork_context.get("version") == 1:
    run_forked_compact_mode(args.fork_context, args.handoff, args.subagent_type, args.project)
elif fork_context.get("version") == 2:
    run_forked_subagent_mode(
        args.fork_context,
        args.task_file,
        args.handoff,
        args.project,
    )
else:
    raise ValueError(f"Unsupported fork-context version: {fork_context.get('version')}")
```

Build the allowed implementation registry without a handoff path, wrap it with inherited schemas,
append the child task, run the loop, validate the returned clean text, retry once with the exact
validation error, and write only verified text.

- [ ] **Step 5: Run subprocess, registry, and compact tests**

Run:

```powershell
conda run -n dagi python -m pytest `
  tests/test_subagent_main.py tests/test_inherited_registry.py `
  tests/test_compact_subagent.py -v
```

Expected: PASS for both version-1 compact and version-2 generic paths.

- [ ] **Step 6: Commit generic inherited execution**

```bash
git add tools/subagent_main.py agent/subagent_tools.py agent/loop.py \
  tests/test_subagent_main.py tests/test_inherited_registry.py
git commit -m "feat: execute inherited subagents with guarded tools"
```

---

### Task 6: Thread parent context through every live subagent spawner

**Files:**
- Modify: `agent/tools.py:90-235`
- Modify: `agent/subagent_tools.py:100-160`
- Modify: `tools/read/_read.py:110-235`
- Modify: `.dagi/subagents/cli/main.py`
- Modify: `.dagi/subagents/explore_files/main.py`
- Modify: `.dagi/subagents/memory-add/main.py`
- Modify: `.dagi/subagents/memory-query/main.py`
- Modify: `.dagi/subagents/memory-refresh/main.py`
- Modify: `.dagi/subagents/plan/main.py`
- Modify: `.dagi/subagents/read-large-text/main.py`
- Modify: `.dagi/subagents/review/main.py`
- Modify: `.dagi/subagents/web_research/main.py`
- Modify: `.dagi/subagents/worker/main.py`
- Test: `tests/test_subagent_tools_new.py`
- Test: `tests/test_subagent_configs.py`
- Test: `tests/test_read_tool.py`

**Interfaces:**
- Consumes: `ParentContextProvider` from Task 1.
- Extends all typed constructors with `parent_context=None` and stores `_parent_context`.
- Extends `create_tool_registry(..., parent_context=None)` and `_discover_subagent_tools(...)`.

- [ ] **Step 1: Write failing constructor and forwarding tests**

```python
@pytest.mark.parametrize("type_name", BUILTIN_SUBAGENT_TYPES)
def test_typed_subagent_accepts_and_forwards_parent_context(type_name, monkeypatch):
    provider = ParentContextProvider(Mock(), Mock(return_value=0))
    tool = _construct_type(type_name, parent_context=provider)
    _mock_successful_subagent(monkeypatch)
    _invoke_minimal_run(tool)
    assert mocked_run_subagent.call_args.kwargs["parent_context"] is provider


def test_read_large_text_forwards_live_parent_context(read_tool, monkeypatch):
    read_tool._parent_context = Mock()
    _invoke_large_text_fallback(read_tool, monkeypatch)
    assert mocked_run_subagent.call_args.kwargs["parent_context"] is read_tool._parent_context
```

- [ ] **Step 2: Run constructor and read tests**

Run:

```powershell
conda run -n dagi python -m pytest `
  tests/test_subagent_tools_new.py tests/test_subagent_configs.py `
  tests/test_read_tool.py -v
```

Expected: FAIL because constructors and discovery do not accept `parent_context`.

- [ ] **Step 3: Thread one explicit provider through registry construction**

Pass `self.parent_context_provider` from all normal and plan-mode `AgentLoop` registry builds.
Forward it through `create_tool_registry()`, `_discover_subagent_tools()`, `ReadTool`, and each
typed wrapper.
Each wrapper call becomes:

```python
result = _subagent_api.run_subagent(
    task=task,
    preset="explore_files",
    project_path=self._config.project_path,
    parent_log=self._session_log,
    parent_context=self._parent_context,
)
```

Retain `parent_log` during migration because it remains the fallback branch logger for fresh calls.

- [ ] **Step 4: Run all typed-wrapper and discovery tests**

Run:

```powershell
conda run -n dagi python -m pytest `
  tests/test_subagent_tools_new.py tests/test_subagent_configs.py `
  tests/test_branch_start_integration.py tests/test_read_tool.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit live-provider wiring**

```bash
git add agent/tools.py agent/subagent_tools.py tools/read/_read.py .dagi/subagents \
  tests/test_subagent_tools_new.py tests/test_subagent_configs.py tests/test_read_tool.py
git commit -m "feat: inherit context in every live typed subagent"
```

---

### Task 7: Prove ordinary subagent cache identity and return compatibility

**Files:**
- Create: `tests/test_inherited_subagent_integration.py`
- Modify: `tests/test_branch_start_integration.py`
- Modify: `tests/test_context_spec.py`

**Interfaces:**
- Consumes the live path completed in Tasks 1-6.
- Proves ordinary wrappers still return full handoff content through the parent tool result.

- [ ] **Step 1: Add a mocked end-to-end spawn test**

```python
def test_typed_spawn_inherits_triggering_request_and_returns_full_handoff(loop, monkeypatch):
    parent_request = _install_mock_provider_that_calls_worker(loop, monkeypatch)
    child_request = _capture_child_provider_request(monkeypatch)
    loop.run("inspect the failure")
    assert child_request["model"] == parent_request["model"]
    assert child_request["messages"][:-1] == parent_request["messages"]
    assert child_request["tools"] == parent_request["tools"]
    tool_results = [message for message in loop._messages if message["role"] == "tool"]
    assert "## Findings" in tool_results[-1]["content"]
```

Also cover a multi-tool assistant response and assert the child prefix excludes that assistant
response, preventing an orphaned tool-call protocol sequence.

- [ ] **Step 2: Run the integration test and observe any wiring gap**

Run: `conda run -n dagi python -m pytest tests/test_inherited_subagent_integration.py -v`

Expected: FAIL at the first incomplete integration seam, while making no network request.

- [ ] **Step 3: Apply the smallest corrections exposed by integration**

Restrict changes to request construction, branch cutoff metadata, wrapper forwarding, or handoff
formatting. Do not alter the approved return contract.

- [ ] **Step 4: Run integration and branch suites**

Run:

```powershell
conda run -n dagi python -m pytest `
  tests/test_inherited_subagent_integration.py `
  tests/test_branch_start_integration.py tests/test_context_spec.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit ordinary-subagent integration**

```bash
git add tests/test_inherited_subagent_integration.py \
  tests/test_branch_start_integration.py tests/test_context_spec.py \
  agent tools .dagi/subagents
git commit -m "test: verify inherited subagent request identity"
```

---

### Task 8: Define and validate the `/wtf` report

**Files:**
- Create: `.dagi/subagents/wtf/prompt.md`
- Create: `.dagi/subagents/wtf/subagent_config.yaml`
- Create: `agent/wtf_report.py`
- Create: `tests/test_wtf_report.py`
- Modify: `tests/test_subagent_configs.py`

**Interfaces:**
- Produces: `WtfReport(description, error_report, suggested_fix)`.
- Produces: `parse_wtf_report(text: str) -> WtfReport`.
- Preset tools: exactly `read`, `grep`, `find`.
- Required headings: `Description`, `Error Report`, `Suggested Fix`.

- [ ] **Step 1: Write failing parser and preset tests**

```python
def test_parse_wtf_report_requires_and_extracts_all_sections():
    report = parse_wtf_report(
        "## Description\nWrong branch\n\n"
        "## Error Report\nThe trace shows X.\n\n"
        "## Suggested Fix\nChange Y.\n"
    )
    assert report.description == "Wrong branch"
    assert report.error_report == "The trace shows X."
    assert report.suggested_fix == "Change Y."


@pytest.mark.parametrize("missing", ["Description", "Error Report", "Suggested Fix"])
def test_parse_wtf_report_rejects_missing_or_empty_section(missing):
    with pytest.raises(ValueError, match=missing):
        parse_wtf_report(_report_without(missing))
```

- [ ] **Step 2: Run tests and confirm preset/parser are absent**

Run: `conda run -n dagi python -m pytest tests/test_wtf_report.py tests/test_subagent_configs.py -v`

Expected: FAIL because the parser and preset do not exist.

- [ ] **Step 3: Implement strict heading parsing and the read-only preset**

```python
@dataclass(frozen=True, slots=True)
class WtfReport:
    description: str
    error_report: str
    suggested_fix: str
```

Use an anchored multiline heading expression that accepts only the three level-2 headings, rejects
duplicates, preserves section body text, and rejects empty bodies. Configure
`required_sections: [Description, Error Report, Suggested Fix]` in the preset. The prompt states
that a missing description must be inferred from inherited context and that no fix may be applied.

- [ ] **Step 4: Run parser and config tests**

Run: `conda run -n dagi python -m pytest tests/test_wtf_report.py tests/test_subagent_configs.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the diagnostic contract**

```bash
git add .dagi/subagents/wtf agent/wtf_report.py \
  tests/test_wtf_report.py tests/test_subagent_configs.py
git commit -m "feat: define structured wtf diagnostic reports"
```

---

### Task 9: Orchestrate atomic `/wtf` diagnosis in the parent loop

**Files:**
- Create: `agent/wtf.py`
- Modify: `agent/loop.py:420-440, 680-835`
- Create: `tests/test_wtf.py`
- Modify: `tests/test_session_log.py`

**Interfaces:**
- Produces: `WtfResult(description, report_path, branch_id)`.
- Produces: `run_wtf(loop: AgentLoop, description: str | None) -> WtfResult`.
- Produces: `AgentLoop.run_wtf(description: str | None) -> WtfResult` as a thin delegate.

- [ ] **Step 1: Write failing success and atomicity tests**

```python
def test_success_saves_under_errors_and_appends_only_command_reference(loop, tmp_path, monkeypatch):
    before = copy.deepcopy(loop._messages)
    result = loop.run_wtf("wrong config layer")
    assert result.report_path.parent == tmp_path / ".dagi" / "errors"
    assert loop._messages[:-1] == before
    assert "/wtf wrong config layer" in loop._messages[-1]["content"]
    assert str(result.report_path.relative_to(tmp_path)) in loop._messages[-1]["content"]
    assert "## Error Report" not in loop._messages[-1]["content"]


def test_stale_generation_appends_no_reference(loop, monkeypatch):
    before = copy.deepcopy(loop._messages)
    _make_child_change_surface_generation_before_return(loop, monkeypatch)
    with pytest.raises(RuntimeError, match="stale parent surface"):
        loop.run_wtf(None)
    assert loop._messages == before
```

- [ ] **Step 2: Run focused orchestration tests**

Run: `conda run -n dagi python -m pytest tests/test_wtf.py -v`

Expected: FAIL because `AgentLoop.run_wtf` is absent.

- [ ] **Step 3: Implement isolated orchestration and reference append**

```python
result = run_subagent(
    task=_wtf_task(description),
    preset="wtf",
    project_path=loop.config.project_path,
    parent_context=loop.parent_context_provider,
    fork_mode="stable",
    handoff_dir=loop.config.project_path / ".dagi" / "errors",
)
```

Parse the report, compare the current surface generation with the fork's recorded generation, then
append one role=`user`, source=`wtf` message containing the literal invocation, normalized
project-relative path, and branch id. For idle state, create and close a dedicated command turn.
For paused state, append at the open safe step without setting `_pause_event`.

- [ ] **Step 4: Run orchestration and log invariant tests**

Run:

```powershell
conda run -n dagi python -m pytest `
  tests/test_wtf.py tests/test_session_log.py tests/test_context_spec.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit parent-side `/wtf` orchestration**

```bash
git add agent/wtf.py agent/loop.py tests/test_wtf.py tests/test_session_log.py
git commit -m "feat: add atomic wtf diagnosis orchestration"
```

---

### Task 10: Add the TUI `/wtf` command

**Files:**
- Modify: `tui/app.py:70-145`
- Modify: `tui/commands.py:40-105, 150-190`
- Modify: `tui/utils.py:12-21`
- Create: `tests/test_tui_wtf.py`

**Interfaces:**
- Consumes: `AgentLoop.run_wtf()` and `WtfResult` from Task 9.
- Produces: `_cmd_wtf(description: str | None) -> None`.
- Adds help: `/wtf [description]`.

- [ ] **Step 1: Write failing dispatch and rendering tests**

```python
def test_slash_dispatches_optional_description_without_resuming_paused_loop(app):
    app._active_loop.pause()
    app._handle_slash("/wtf wrong config layer")
    assert app._active_loop.run_wtf.call_args.args == ("wrong config layer",)
    assert app._active_loop._pause_event.is_set() is False


def test_success_renders_description_and_path_but_not_report_body(app):
    app._active_loop.run_wtf.return_value = WtfResult(
        description="Wrong config layer",
        report_path=Path(".dagi/errors/wtf_ab12.md"),
        branch_id="wtf_ab12",
    )
    app._cmd_wtf(None)
    rendered = app.conversation_text()
    assert "Wrong config layer" in rendered
    assert ".dagi/errors/wtf_ab12.md" in rendered
    assert "Suggested Fix" not in rendered
```

- [ ] **Step 2: Run TUI tests and observe unknown-command behavior**

Run: `conda run -n dagi python -m pytest tests/test_tui_wtf.py -v`

Expected: FAIL because `/wtf` is unknown.

- [ ] **Step 3: Intercept `/wtf` before paused message injection**

In `on_prompt_input_submitted`, detect the command before the paused-worker branch and delegate to
`_handle_slash`. `_cmd_wtf` rejects a missing active conversation, prevents concurrent diagnoses,
waits for `wait_for_pause_checkpoint()` when paused, disables input during diagnosis, and runs
`loop.run_wtf()` in a daemon thread. Its completion callback restores the original idle/paused TUI
state and renders only description plus path.

- [ ] **Step 4: Run TUI, pause, and command tests**

Run:

```powershell
conda run -n dagi python -m pytest `
  tests/test_tui_wtf.py tests/test_prompt_input_multiline.py `
  tests/test_agent_loop.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit TUI support**

```bash
git add tui/app.py tui/commands.py tui/utils.py tests/test_tui_wtf.py
git commit -m "feat: add wtf command to the tui"
```

---

### Task 11: Verify end-to-end failures and regressions

**Files:**
- Modify: `tests/test_inherited_subagent_integration.py`
- Modify: `tests/test_wtf.py`
- Modify: `tests/test_tui_wtf.py`
- Modify implementation files only when a new test exposes a defect.

**Interfaces:**
- Verifies the completed public behavior; produces no new production interface.

- [ ] **Step 1: Add explicit failure-matrix tests**

```python
@pytest.mark.parametrize(
    "failure",
    ["fork_error", "timeout", "empty", "truncated", "malformed", "write_error", "stale"],
)
def test_wtf_failure_never_appends_success_reference(loop, failure, monkeypatch):
    before = copy.deepcopy(loop._messages)
    _install_failure(loop, failure, monkeypatch)
    with pytest.raises((RuntimeError, ValueError, OSError)):
        loop.run_wtf("diagnose")
    assert loop._messages == before
```

Add one test where a child first calls blocked `write`, receives the access error, then calls
allowed `read` and returns a valid handoff. Add one paused test proving the loop remains paused
after both success and failure.

- [ ] **Step 2: Run all targeted feature suites**

Run:

```powershell
conda run -n dagi python -m pytest `
  tests/test_parent_context.py tests/test_inherited_registry.py `
  tests/test_subagent_api.py tests/test_subagent_runner.py `
  tests/test_subagent_main.py tests/test_inherited_subagent_integration.py `
  tests/test_wtf_report.py tests/test_wtf.py tests/test_tui_wtf.py -v
```

Expected: PASS with zero network calls.

- [ ] **Step 3: Run compact and session-log regression suites**

Run:

```powershell
conda run -n dagi python -m pytest `
  tests/test_compact_subagent.py tests/test_compact_integration.py `
  tests/test_context_spec.py tests/test_session_log.py `
  tests/test_session_log_shadow.py tests/test_branch_start_integration.py -v
```

Expected: PASS.

- [ ] **Step 4: Run the complete test suite**

Run: `conda run -n dagi python -m pytest -q`

Expected: all tests pass; no benchmark command or real provider call occurs.

- [ ] **Step 5: Check code constraints and working-tree scope**

Run: `git diff --check`

Run: `conda run -n dagi python -m compileall agent tools tui .dagi/subagents tests`

Expected: no whitespace or syntax errors. Review changed functions against the limits in Global
Constraints. Existing documented `agent/loop.py` size/complexity debt may remain, but new functions
comply independently.

- [ ] **Step 6: Commit regression fixes and tests**

```bash
git add agent tools tui .dagi/subagents tests
git commit -m "test: cover inherited subagent and wtf failures"
```

If Step 2-5 require no changes, do not create an empty commit.

---

### Task 12: Update project context and perform final verification

**Files:**
- Modify: `AGENTS.md`

**Interfaces:**
- Documents inherited subagent flow, `/wtf`, relevant files, and any verified error discovered
  during implementation.

- [ ] **Step 1: Invoke the `update-project-context` skill**

Update the architecture, process flow, key files, notes, errors log, and last-updated header while
preserving the Behavioral Guidelines section verbatim and respecting all section caps.

- [ ] **Step 2: Verify the context document and final suite**

Run: `git diff --check`

Run: `conda run -n dagi python -m pytest -q`

Expected: no diff errors and all tests pass.

- [ ] **Step 3: Commit project context separately**

```bash
git add AGENTS.md
git commit -m "docs: update project context for inherited subagents"
```

- [ ] **Step 4: Record final branch state**

Run: `git status --short`

Expected: no output.

Run: `git log --oneline --decorate -12`

Expected: the design, plan, implementation, test, and project-context commits are visible on
`dagi/wtf-inherited-subagents`.

Do not merge. Ask the user whether they want to merge the task branch into its previous base.
