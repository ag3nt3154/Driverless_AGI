# Subagent Handoff Enforcement & Parent-Authored Briefing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the subagent handoff a structurally enforced contract rather than a prose request, and replace the ad-hoc `custom_instructions` parameter with a universal parent-authored `briefing` + `handoff_spec` pair available to every subagent type. Today the handoff path is only mentioned in prose, two types (`explore_files`, `web_research`) hold no `write` tool and so *structurally cannot* comply, four of seven types are never told the path at all, and `subagent_main.py` silently scrapes the last assistant message into a file the parent cannot distinguish from a deliberate report.

**Architecture:** A new `WriteHandoffTool` mirrors `EscalateIssueTool` — the destination path is baked in at construction, so the model never sees or invents a path. It is auto-injected by `agent/tools.py` whenever `handoff_path is not None`, *regardless of the config `tools:` list*, which fixes the two toolless types without granting them a general `write`. `run(content)` writes the file verbatim (no section validation — the subagent owns its formatting) and returns a termination sentinel handled by the existing dispatch block in `loop.py`, so the child stops immediately instead of burning a continuation round-trip. If the file is still absent after `loop.run()`, the child re-enters `loop.run()` once with a corrective prompt (`AgentLoop.run` is re-entrant — `_messages` lives on the instance). If still absent, it scrapes as before but also drops an out-of-band `<stem>_unverified.flag` sidecar, which the runner turns into status `ok_unverified` and the parent renders as a warning banner above the content.

Change 2 keeps the per-type Python branches that build a body (worker's plan subtask, review's worker-handoff path) but wraps *every* type in the same envelope: `## Instructions {briefing}` / `## Output {handoff_spec}`. `custom_instructions` is renamed to `briefing` everywhere it lives, and each `subagent_config.yaml` gains a `default_handoff_spec` used when the parent omits one.

**Tech Stack:** Python 3.14, pytest, YAML subagent configs. Run tests with `conda run -n dagi python -m pytest`. No live model calls at any point.

---

## Design Decisions (confirmed 2026-07-25)

| # | Decision |
|---|---|
| 1 | Handoff path is parent-only. `handoff_file` **removed** from the `explore_files` schema. |
| 2 | Unverified signal is out-of-band: child writes `<stem>_unverified.flag`; runner returns `ok_unverified`. |
| 3 | Missing handoff → **always one retry**, unconditionally. |
| 4 | **No required sections.** `run(content)` writes without validating. |
| 5 | Parent's output expectation is a separate free-text `handoff_spec` param, unvalidated. |
| 6 | `custom_instructions` **renamed** to `briefing` (5 live files; `docs/superpowers/` history untouched). |
| 7 | `briefing` and `handoff_spec` both optional; each config carries `default_handoff_spec`. |
| 8 | Composition = per-type body + universal envelope. |
| 9 | `write_handoff` **hard-terminates** via a sentinel in `loop.py`'s existing dispatch block. |
| 10 | Unverified handoffs render as a warning banner, then the content. |
| 11 | Scope = 7 registered types **plus** the `custom`/cli dynamic path. |
| 12 | Staged rollout: Change 1, verify, then Change 2. |

**Out of scope (log, do not fix):** subagent prompts never teach `<<END_OF_RESPONSE>>`; `plan/` and `cli/` prompt dirs are vestigial (no `subagent_config.yaml`); `escalate_issue`'s docstring is stale; `_poll_until`'s "exited without writing handoff" branch stays dead by design.

---

## File Structure

### Files to Create
- `tools/write_handoff/__init__.py` — exports `WriteHandoffTool`
- `tools/write_handoff/_write_handoff.py` — the tool (mirrors `tools/escalate_issue/_escalate_issue.py`)
- `tests/test_write_handoff_tool.py` — unit tests for the tool
- `tests/test_spawn_subagent_composition.py` — Stage 2 composition tests, split out because `tests/test_spawn_subagent_tool.py` is 494/500 lines

### Files to Modify
**Stage 1**
- `agent/loop.py:28-29, 651-663` — add `WRITE_HANDOFF_SENTINEL`, handle it in the existing sentinel dispatch block
- `agent/tools.py` — auto-inject `write_handoff` whenever `handoff_path is not None`, in both the config branch and the `custom` branch
- `tools/subagent_main.py:195-215` — one corrective retry, then scrape + `<stem>_unverified.flag`
- `tools/_subagent_runner.py:100-115` — detect the flag, return `ok_unverified`
- `tools/spawn_subagent/_spawn_subagent.py` — handle `ok_unverified`, render warning banner
- `.dagi/subagents/explore_files/subagent_config.yaml` — drop `handoff_file` from `parameters`
- `.dagi/subagents/*/prompt.md` (7 files) — replace prose path instructions with "call `write_handoff`"

**Stage 2**
- `tools/spawn_subagent/_spawn_subagent.py` — rename `custom_instructions` → `briefing`; add `handoff_spec`; envelope in `_compose_task()`
- `tools/cli_subagent/_cli_subagent.py` — add `briefing` / `handoff_spec` passthrough
- `.dagi/subagents/*/subagent_config.yaml` (7 files) — add `briefing`, `handoff_spec`, `default_handoff_spec`
- `.dagi/skills/dagi-execute/SKILL.md` — rename `custom_instructions` → `briefing`
- `tests/test_spawn_subagent_tool.py` — rename in existing assertions

**Post-implementation**
- `AGENTS.md`, `README.md`, `TODO.md`

### Files to Delete
None.

---

# Stage 1 — Enforce the Handoff

### Task 1: [ ] `WriteHandoffTool`

**Files:**
- Create: `tools/write_handoff/_write_handoff.py`, `tools/write_handoff/__init__.py`
- Test: `tests/test_write_handoff_tool.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_writes_content_verbatim(tmp_path):
    path = tmp_path / "worker_ab12.md"
    out = WriteHandoffTool(handoff_path=path).run(content="# Anything\n\nfree form")
    assert path.read_text(encoding="utf-8") == "# Anything\n\nfree form"
    assert WRITE_HANDOFF_SENTINEL in out

def test_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "deep" / "h.md"
    WriteHandoffTool(handoff_path=path).run(content="x")
    assert path.exists()

def test_schema_has_only_content(tmp_path):
    schema = WriteHandoffTool(handoff_path=tmp_path / "h.md").schema()
    props = schema["function"]["parameters"]["properties"]
    assert set(props) == {"content"}   # path is never model-visible

def test_overwrite_replaces(tmp_path):
    path = tmp_path / "h.md"
    tool = WriteHandoffTool(handoff_path=path)
    tool.run(content="first")
    tool.run(content="second")
    assert path.read_text(encoding="utf-8") == "second"
```

- [ ] **Step 2: Run tests, verify they fail (ImportError)**

```
conda run -n dagi python -m pytest tests/test_write_handoff_tool.py
```

- [ ] **Step 3: Implement, modelled on `tools/escalate_issue/_escalate_issue.py`** — `name = "write_handoff"`, `_parameters` with a single required `content` string, `__init__(self, handoff_path: Path)`, `run(self, content: str) -> str` that mkdirs, writes UTF-8, and returns a message ending in the sentinel.

- [ ] **Step 4: Run tests, verify they pass**

---

### Task 2: [ ] Sentinel termination in `loop.py`

**Files:**
- Modify: `agent/loop.py:28-29` (constant), `agent/loop.py:651-663` (dispatch block)
- Test: `tests/test_loop_sentinels.py` (extend if present, else create)

- [ ] **Step 1: Write the failing test** — a fake registry whose `dispatch` returns a string containing `WRITE_HANDOFF_SENTINEL`; assert `loop.run(task)` returns immediately without a further model call.

- [ ] **Step 2: Run test, verify it fails**

- [ ] **Step 3: Implement** — define `WRITE_HANDOFF_SENTINEL = "<<HANDOFF_WRITTEN>>"` beside `TASK_END_FLAG`; in the existing sentinel block, on match append the tool result to `_messages` (so the transcript stays well-formed) then `return` the cleaned text. Keep the branch inside the existing `if`-chain to respect complexity ≤ 8.

- [ ] **Step 4: Run test, verify it passes**

**Note:** this is what removes the extra `CONTINUE_PROMPT` round-trip on the handoff path — cost-relevant.

---

### Task 3: [ ] Auto-inject `write_handoff` in `agent/tools.py`

**Files:**
- Modify: `agent/tools.py` (both the config branch and the `custom` branch)
- Test: `tests/test_tools_registry.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_injected_even_when_not_in_tool_list(tmp_path):
    reg = build_subagent_registry(cfg={"tools": ["read", "grep", "find"]},
                                  handoff_path=tmp_path / "h.md", ...)
    assert "write_handoff" in reg

def test_absent_without_handoff_path(...):
    assert "write_handoff" not in build_subagent_registry(cfg=..., handoff_path=None, ...)

def test_custom_branch_gets_it(...):
    # custom still has no escalate_issue — that exclusion is deliberate and unchanged
```

- [ ] **Step 2: Run tests, verify they fail**

- [ ] **Step 3: Implement** beside the existing `EscalateIssueTool` injection:
```python
if handoff_path is not None:
    registry_map["escalate_issue"] = EscalateIssueTool(handoff_path=handoff_path)
    registry_map["write_handoff"] = WriteHandoffTool(handoff_path=handoff_path)
```
and mirror the `write_handoff` line into the `custom` branch.

- [ ] **Step 4: Run tests, verify they pass**

---

### Task 4: [ ] Retry + unverified flag in `subagent_main.py`

**Files:**
- Modify: `tools/subagent_main.py:195-215`
- Test: `tests/test_subagent_main.py`

- [ ] **Step 1: Write the failing tests** — with a stub loop: (a) handoff present after first `run` → no retry, no flag; (b) absent then written on retry → exactly two `run` calls, no flag; (c) absent both times → scrape written **and** `<stem>_unverified.flag` exists; (d) absent both times with empty transcript → flag exists and body is the empty-output marker.

- [ ] **Step 2: Run tests, verify they fail**

- [ ] **Step 3: Implement** — extract a helper (keeps `main` under 100 lines):
```python
def _ensure_handoff(loop, handoff_path: Path) -> None:
    if handoff_path.exists():
        return
    loop.run(_HANDOFF_RETRY_PROMPT)     # re-entrant: _messages persists
    if handoff_path.exists():
        return
    final_text = _extract_final_assistant_text(loop._messages)
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.write_text(f"# Handoff\n\n{final_text or _EMPTY_MARKER}", encoding="utf-8")
    handoff_path.with_name(f"{handoff_path.stem}_unverified.flag").write_text("1", encoding="utf-8")
```
`_HANDOFF_RETRY_PROMPT` names the tool explicitly: *"You ended without calling `write_handoff`. Call it now with your complete report."*

- [ ] **Step 4: Run tests, verify they pass**

---

### Task 5: [ ] `ok_unverified` status in the runner

**Files:**
- Modify: `tools/_subagent_runner.py:100-115`
- Test: `tests/test_subagent_runner.py`

- [ ] **Step 1: Write the failing tests** — handoff + flag → `{"status": "ok_unverified", ...}`; handoff without flag → `"ok"`; the escalation branch is unaffected.

- [ ] **Step 2: Run tests, verify they fail**

- [ ] **Step 3: Implement** in the exit branch, checking the sidecar before returning. Leave the existing dead `"error"` branch as-is (documented above as intentional).

- [ ] **Step 4: Run tests, verify they pass**

---

### Task 6: [ ] Warning banner in the spawn tool

**Files:**
- Modify: `tools/spawn_subagent/_spawn_subagent.py` (status branching + `_format_ok_result`)
- Test: `tests/test_spawn_subagent_tool.py`

- [ ] **Step 1: Write the failing tests** — `ok_unverified` result renders banner-then-content, with the banner *before* the body; `ok` renders unchanged (regression guard on the existing inlining behaviour).

- [ ] **Step 2: Run tests, verify they fail**

- [ ] **Step 3: Implement** — add `if result["status"] == "ok_unverified": return self._format_ok_result(result["handoff"], unverified=True)`; the banner states the subagent never called `write_handoff` and the content below is a scraped closing message, not a deliberate report.

- [ ] **Step 4: Run tests, verify they pass**

---

### Task 7: [ ] Config and prompt updates

**Files:**
- Modify: `.dagi/subagents/explore_files/subagent_config.yaml`; 7× `.dagi/subagents/*/prompt.md`

- [ ] **Step 1: Write the failing test** — assert no registered subagent schema exposes a `handoff_file` / path-like parameter.

- [ ] **Step 2: Run test, verify it fails** (explore_files still declares it)

- [ ] **Step 3: Implement** — remove `handoff_file` from `properties` and `required`; in every `prompt.md`, replace path prose with "When your task is complete, call `write_handoff` with your full report. This ends your run."

- [ ] **Step 4: Run the full suite**

```
conda run -n dagi python -m pytest
```

**Stage 1 gate:** full suite green before starting Stage 2.

---

# Stage 2 — Parent-Authored Briefing

### Task 8: [ ] Rename `custom_instructions` → `briefing`

**Files:**
- Modify: `tools/spawn_subagent/_spawn_subagent.py`, `.dagi/subagents/worker/subagent_config.yaml`, `.dagi/subagents/review/subagent_config.yaml`, `.dagi/skills/dagi-execute/SKILL.md`, `tests/test_spawn_subagent_tool.py`

- [ ] **Step 1: Update existing tests to use `briefing`; run, verify they fail**
- [ ] **Step 2: Rename across the 5 live files. No back-compat alias** — this is an internal parameter with no external callers, and a shim would violate the project's no-compatibility-hack standard.
- [ ] **Step 3: Grep to confirm `custom_instructions` survives only under `docs/superpowers/` (historical plans, intentionally untouched)**
- [ ] **Step 4: Run tests, verify they pass**

---

### Task 9: [ ] `briefing` + `handoff_spec` on every schema

**Files:**
- Modify: 7× `.dagi/subagents/*/subagent_config.yaml`, `tools/cli_subagent/_cli_subagent.py`, `tools/spawn_subagent/_spawn_subagent.py` (`_FALLBACK_PARAMETERS`)
- Test: `tests/test_spawn_subagent_composition.py`

- [ ] **Step 1: Write the failing test** — every registered spawn tool's schema exposes optional `briefing` and `handoff_spec` strings, and every config declares a non-empty `default_handoff_spec`.
- [ ] **Step 2: Run test, verify it fails**
- [ ] **Step 3: Implement.** `web_research` currently has no `parameters:` block and falls back — give it a real one. `default_handoff_spec` is per-type prose describing what a good report contains for that role.
- [ ] **Step 4: Run test, verify it passes**

---

### Task 10: [ ] Universal envelope in `_compose_task()`

**Files:**
- Modify: `tools/spawn_subagent/_spawn_subagent.py`
- Test: `tests/test_spawn_subagent_composition.py`

- [ ] **Step 1: Write the failing tests** — for all 7 types plus `custom`: the composed task ends with `## Instructions` then `## Output`; `handoff_spec` omitted → the config's `default_handoff_spec` appears; `briefing` omitted → no empty `## Instructions` heading; worker still receives its plan subtask and review still receives the worker handoff path (regression guards on the surviving per-type bodies).

- [ ] **Step 2: Run tests, verify they fail**

- [ ] **Step 3: Implement** — keep the per-type dispatch but have it return only a *body*; a single `_wrap_envelope(body, briefing, handoff_spec)` appends the envelope for every type, so the `return kwargs.get("task", "")` fall-through no longer means "told nothing". Keep `_compose_task` under the complexity ceiling by moving the dispatch to a small dict lookup if the `if`-chain grows.

- [ ] **Step 4: Run tests, verify they pass**

---

### Task 11: [ ] Docs

**Files:**
- Modify: `AGENTS.md`, `README.md`, `TODO.md`

- [ ] **Step 1: `AGENTS.md`** — document the enforced handoff contract, the `write_handoff` sentinel, `ok_unverified`, and the `briefing`/`handoff_spec` envelope; log the four out-of-scope residuals.
- [ ] **Step 2: `README.md` / `TODO.md`** — reflect the delivered state.
- [ ] **Step 3: Run the full suite one final time**

```
conda run -n dagi python -m pytest
```
