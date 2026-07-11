# Fable Adversarial Code Review — Driverless AGI

**Date:** 2026-07-11
**Reviewer:** Fable 5 (adversarial pass)
**Scope:** `agent/`, `tools/`, `cli.py`, `tui/`, `tg/`, `scheduler/`, `benchmarks/`, entry scripts
**Posture:** Production-readiness gate. I am reviewing this as if it were an intern's PR and I am the last line of defense before it ships. Findings are ranked by blast radius, and every correctness claim below was either reproduced at runtime or traced line-by-line. Verification status is stated per finding.

---

## Executive summary

The architecture is sound and the code is, for the most part, clean and well-commented. But there are **two hard crashes sitting directly on primary user paths**, a **sandbox that silently fails open**, and a **remotely-reachable agent with full shell access and no authentication**. None of these are subtle race conditions — they fire on the first ordinary input. This does not pass a production gate in its current state.

| # | Severity | Finding | Path | Status |
|---|----------|---------|------|--------|
| 1 | 🔴 Critical | Reading any image crashes the whole agent loop | `agent/loop.py:558` | **Reproduced** |
| 2 | 🔴 Critical | `active_loop.plan_mode_exited` — AttributeError after *every* CLI task | `cli.py:1239` | **Reproduced** |
| 3 | 🔴 Critical | Telegram bot has zero authorization + full bash/file tools = remote RCE | `tg/bot.py` | Confirmed by inspection |
| 4 | 🔴 Critical | Memory-subagent wiki sandbox fails open when `memory_root` unset (the default) | `agent/tools.py:438` | Confirmed by inspection |
| 5 | 🟠 High | `UnboundLocalError` in `finally` masks the real exception | `tg/bot.py:163` | Confirmed by inspection |
| 6 | 🟠 High | `_PLAN_SUBAGENT_SYSTEM_PROMPT` referenced but never defined (NameError landmine) | `tools/plan_subagent.py:30` | Confirmed by inspection |
| 7 | 🟠 High | `grep` Python fallback silently returns zero matches under any dotted dir | `tools/grep.py:98` | **Reproduced** |
| 8 | 🟡 Medium | Session summary computes `cost`/`tools` strings then never prints them | `agent/session.py:218` | Confirmed by inspection |
| 9 | 🟡 Medium | Falsy-zero coercion in config (`entry.get(x) or default`) | `agent/config_loader.py:133` | Confirmed by inspection |
| 10 | 🟡 Medium | `AskUserTool` double-timeout race + leaked daemon thread | `tools/ask_user.py:92` | Confirmed by inspection |
| 11 | 🟡 Medium | `explore_files` schema demands `handoff_file`, `run()` ignores it | `tools/spawn_subagent.py` + config | Confirmed by inspection |
| 12 | ⚪ Cleanup | ~5 dead modules/classes never wired in | multiple | Confirmed by grep |
| 13 | ⚪ Infra | Test suite not runnable in the documented `dagi` env; RAM watchdog turns memory pressure into failures | `tests/conftest.py` | Observed |

---

## 🔴 Critical findings

### 1. Reading any image file crashes the entire agent loop

**Location:** `agent/loop.py:544-560`, triggered by `tools/read.py:45-48`

`ReadTool.run()` returns a **list** for image files:

```python
# tools/read.py:46-48
if ext in _IMAGE_EXTS:
    b64 = base64.b64encode(p.read_bytes()).decode()
    return [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]
```

Back in the dispatch handler, the sentinel-detection chain ends in an `else` that assumes a string:

```python
# agent/loop.py:544-560
result = self.registry.dispatch(tc.function.name, args)
if isinstance(result, str) and result.startswith(ENTER_PLAN_MODE_SENTINEL):
    ...
elif result == EXIT_PLAN_MODE_SENTINEL:      # list == str → False, ok
    ...
else:
    _switch_target = parse_switch_sentinel(result)   # ← result is a list here
```

`parse_switch_sentinel` calls `value.startswith(...)` (`tools/switch_model.py:14`). On a list that is an `AttributeError`, which propagates to the outer `except Exception as e: ... raise` at `loop.py:611` and **kills the task**.

**Failure scenario:** User asks the agent to look at a screenshot. Agent calls `read("bug.png")`. Loop dies with `AttributeError: 'list' object has no attribute 'startswith'`. The one non-string tool result in the codebase is the exact input this branch never guarded.

**Reproduced:**
```
$ python -c "from tools.switch_model import parse_switch_sentinel; parse_switch_sentinel([{...}])"
CRASH: AttributeError - 'list' object has no attribute 'startswith'
```

**Fix:** Guard the entire sentinel chain on `isinstance(result, str)` before any `==`/`startswith` comparison. A non-string result can never be a sentinel — skip straight to `filter_tool_output`:

```python
if isinstance(result, str):
    if result.startswith(ENTER_PLAN_MODE_SENTINEL): ...
    elif result == EXIT_PLAN_MODE_SENTINEL: ...
    ...
    else:
        _switch_target = parse_switch_sentinel(result)
        ...
# non-str (image list) falls through untouched
```

---

### 2. `active_loop.plan_mode_exited` — AttributeError after every interactive CLI task

**Location:** `cli.py:1239`

```python
def run_one(t: str) -> None:
    ...
    conversation_msgs, active_loop = _run_task(...)
    if active_loop.plan_mode_exited and active_loop.exited_plan_file:   # ← attribute does not exist
```

`AgentLoop.__init__` sets `self.exited_plan_file` (`loop.py:323`) but **never** `plan_mode_exited`. There is no `__getattr__` on the class. `run_one` is called for the one-shot `if task:` path and for every REPL turn, and the access is **not** wrapped in try/except, so the first task you run tears down the CLI with an unhandled `AttributeError`.

This is a **regression**: `PROJECT_CONTEXT.md:183` records that this field was removed on 2026-05-31, and `_todo/todo_2026-06-07.md` explicitly logs it as a "runtime crash," marked fixed on 2026-06-13. The current tree has it back — presumably reintroduced in one of the recent `fable update` commits. That is exactly the kind of thing a regression test should have caught and didn't.

**Reproduced (static):** grep confirms the only occurrence of `plan_mode_exited` in code is the read at `cli.py:1239`; nothing assigns it.

**Fix:** The intended signal is "did the loop just come out of plan mode." Replace with the attribute that actually exists:

```python
if active_loop.exited_plan_file:
    ...
    active_loop.exited_plan_file = None   # reset so it fires once
```

…and add a smoke test that runs one no-op task through `run_one` so this can never silently regress again.

---

### 3. Telegram bot: no authorization, full bash + filesystem tools — remote code execution

**Location:** `tg/bot.py:102-122` (`_handle_message`), `agent/tools.py:285` (BashTool always registered)

`_handle_message` accepts input from **any** `chat_id` that messages the bot and dispatches it straight into `AgentLoop`, which is built with the full tool registry — including `bash` (`subprocess.run(shell=True)`, no sandbox by design) and unrestricted `write`/`edit`/`copy` within the project roots. There is no allowlist, no owner check, nothing.

**Failure scenario:** The bot token leaks (or someone guesses the bot handle). Any Telegram user sends `run: cat ~/.env` or `run rm -rf ...`. The agent complies and runs it on the host. This is unauthenticated RCE with a Telegram front-end.

**Fix (must-have before this entrypoint ships):**
- Add an allowlist of authorized chat/user IDs (env var, e.g. `TELEGRAM_ALLOWED_CHAT_IDS`) and reject everything else in `_handle_message` before dispatch.
- Consider running the Telegram surface with `config.tools` restricted (the plumbing already exists via `AgentConfig.tools` + `registry.filter_to`) so the remote surface cannot reach `bash` unless explicitly opted in.

---

### 4. Memory-subagent wiki sandbox fails open by default

**Location:** `agent/tools.py:436-443`, interacting with `agent/config_loader.py:142-143`

The memory subagents (`memory-add`, `memory-query`) declare `root: memory_root` in their configs, intending to restrict file tools to the wiki directory only. The enforcement:

```python
# agent/tools.py:437-443
root_override = cfg.get("root")
if root_override == "memory_root" and memory_root is not None:
    cwd_for_tools = memory_root
    effective_roots = [memory_root]
else:
    cwd_for_tools = project_path
    effective_roots = default_roots            # ← full project scope
```

`memory_root` here is `config.memory_root`, which comes from `raw.get("memory_root")` and is **`None` unless explicitly set** — and `config.example.yaml:87` ships it commented out. So in the default configuration, the guard's `and memory_root is not None` is false, and the memory subagent silently receives **read/write access to the entire project** (`write` + `edit` are in its tool list). The one place the effective memory root *is* resolved to a real path (`AgentLoop._effective_memory_root`, `loop.py:254`) is not the value threaded into `build_subagent_registry` — the raw, often-`None` config value is (`cli.py:1116`, `cli.py:974`).

**Failure scenario:** Out-of-the-box install (no `memory_root` in config). Agent spawns `memory-add` to "remember" something. That subagent can now edit `agent/loop.py`, `.env`, anything under the project — the exact containment the `root: memory_root` design was meant to provide is absent.

**Fix:** Resolve the effective memory root once (mirror `loop.py:254-257`) and pass the resolved path into `build_subagent_registry`, or make the fallback in `build_subagent_registry` itself default to `project_path / "dagi-memory"` when `root == "memory_root"` and `memory_root is None`. Do **not** fall through to full project scope on a sandbox request.

---

## 🟠 High findings

### 5. `UnboundLocalError` in the `finally` block masks the real failure

**Location:** `tg/bot.py:132-166`

```python
try:
    config = resolve_model_config(...)   # can raise
    ...
    loop = AgentLoop(...)                 # loop bound only here
    await ...run_in_executor(None, loop.run, task)
except Exception as exc:
    ...
finally:
    if loop:                              # ← NameError if we raised before `loop =`
        session.messages = loop._messages
        loop.finish()
```

If `resolve_model_config`, `build_callbacks`, or `AgentLoop(...)` raises, `loop` was never assigned, and `if loop:` in the `finally` throws `UnboundLocalError`, which **replaces** the original exception. The user gets a misleading traceback and `session.busy` is still reset (good) but the true error is lost. Your own `TODO.md` acknowledges this ("introduces UnboundLocalError risk … tracked separately") — tracking a known landmine is not the same as defusing it.

**Fix:** `loop = None` before the `try`, and guard `if loop is not None:`.

---

### 6. `_PLAN_SUBAGENT_SYSTEM_PROMPT` is used but never defined

**Location:** `tools/plan_subagent.py:30`

```python
return replace(
    base_config,
    ...
    system_prompt=_PLAN_SUBAGENT_SYSTEM_PROMPT,   # ← NameError: not defined anywhere
```

grep across the repo shows exactly one occurrence of this name — the *use* at line 30. There is no definition, no import. `build_plan_agent_config()` will raise `NameError` the instant it is called. It currently isn't called (the whole module is dead — see finding 12), which is the only reason this hasn't blown up. This is a landmine primed for whoever next tries to wire plan sub-agents in.

**Fix:** Either delete the module (preferred — it's unused) or define the prompt constant / load it from `.dagi/prompts/`.

---

### 7. `grep` Python fallback silently drops all matches under dotted directories

**Location:** `tools/grep.py:96-101`

When ripgrep is unavailable, the fallback enumerates files and unconditionally excludes anything with a dot-prefixed path component:

```python
files = sorted(
    p for p in search_path.rglob("*")
    if p.is_file() and not any(part.startswith(".") for part in p.parts)
)
```

`p.parts` includes the *entire* absolute path. When the agent explicitly greps a path **inside** `.dagi/` (e.g. `grep("SKILL", ".dagi/skills")`) — a completely normal thing for this agent to do given the whole system lives under `.dagi/` — every candidate contains the `.dagi` component and is filtered out. Result: `[no matches]`, even though matches exist. ripgrep (tried first) usually masks this, so it will only bite on a machine without `rg` installed and be maddening to diagnose.

**Reproduced (static):**
```
$ python -c "from pathlib import Path; print(any(x.startswith('.') for x in Path('.dagi/skills/gnhf/scripts/init.py').parts))"
True    # → excluded
```

**Fix:** Only apply the hidden-file filter to components *below* `search_path`, not the search root itself:
```python
rel_parts = p.relative_to(search_path).parts
if p.is_file() and not any(part.startswith(".") for part in rel_parts):
```

---

## 🟡 Medium findings

### 8. Session-end summary builds cost/tools strings then throws them away

**Location:** `agent/session.py:218-224`

```python
cost_str = f"  cost=${total_cost:.5f}" if total_cost is not None else ""
tools_str = ""
if tool_call_counts:
    tools_str = "  tools: " + " ".join(f"{name}×{count}" for ...)
print(f"[dagi] session saved → {self._path}", file=sys.stderr)   # cost_str / tools_str never used
```

Both locals are computed and then never referenced. The stderr summary the user actually sees drops the cost and tool-usage breakdown that the code went to the trouble of assembling. Dead code and a lost feature in one.

**Fix:** `print(f"[dagi] session saved → {self._path}{cost_str}{tools_str}", file=sys.stderr)` (or delete the two locals if the omission is intentional — but the totals suggest it isn't).

---

### 9. Falsy-zero coercion in config resolution

**Location:** `agent/config_loader.py:133-135`

```python
context_window = entry.get("context_window") or raw.get("context_window", 128_000)
reserve_tokens = entry.get("reserve_tokens") or raw.get("reserve_tokens", 16_384)
keep_recent_tokens = entry.get("keep_recent_tokens") or raw.get("keep_recent_tokens", 20_000)
```

`X or default` treats a legitimately-configured `0` as "unset." A user who sets `reserve_tokens: 0` to deliberately disable the output filter / compaction (which `output_filter.py:57` and `loop.py:604` explicitly support as "disabled") will instead get `16_384` at the entry level. The two subsystems that honor `0` can never actually see it from a per-model entry.

**Fix:** Use explicit presence checks: `entry["context_window"] if "context_window" in entry else raw.get(...)`, or a small `_first_set(entry.get(k), raw.get(k), default)` helper that tests `is not None`.

### 10. `AskUserTool` double-timeout race and leaked thread

**Location:** `tools/ask_user.py:89-96`

```python
t = threading.Thread(target=_ask, daemon=True)
t.start()
t.join(timeout=effective_timeout)
answer = result[0] if result else self._fallback(options)
```

The callback (`on_ask_user`) already enforces its own timeout (`cli.py:408` join, `tg/callbacks.py:65` `evt.wait`). Wrapping it in a *second* `t.join(timeout=effective_timeout)` means that when the user answers between `effective_timeout` and the callback's `+60s` safety window, this tool has already returned the fallback and the daemon thread is left dangling with a `result` nobody reads. Two independent timers guarding the same wait is a smell that will produce "it picked the default even though I answered" bug reports.

**Fix:** Let the callback own the timeout. Drop the redundant `t.join` timeout (join without timeout, or call `_on_ask_user` synchronously) and rely on the single timeout inside the callback implementations.

### 11. `explore_files` subagent: schema requires a param the code ignores

**Location:** `tools/spawn_subagent.py:150,214-218` + `.dagi/subagents/explore_files/subagent_config.yaml`

The config's `parameters` block marks both `task` **and** `handoff_file` as `required`, and `_load_parameters` surfaces that schema verbatim to the model. But `run()` generates the handoff path internally (`spawn_subagent.py:162`) and `_compose_explore_context` only consumes `task` — the model-supplied `handoff_file` is silently discarded. So the LLM is compelled to invent a path that is thrown away, wasting tokens and inviting confusion.

**Fix:** Drop `handoff_file` from the `explore_files` config's `parameters`/`required` (the caller owns it), matching how `web_research` is defined.

---

## ⚪ Cleanup / maintainability

### 12. Dead code that should be deleted or wired in

grep confirms these are defined and never used in the live paths (only self-references or tests):

- `agent/sub_agent.py` — `SubAgentRunner`: not imported anywhere. The subagent system runs via `tools/_subagent_runner.py` (subprocess) instead. Entire module is dead.
- `tools/web_research.py` — `WebResearchTool`: never registered (the registry uses the auto-discovered `spawn_web_research_subagent`). Dead.
- `tools/plan_subagent.py` — `PlanSubAgent` / `build_plan_agent_config`: unused, and broken (finding 6).
- `tools/tmux_bash.py` — `TmuxBashTool`: referenced only by `tests/test_bash_tools.py`, not by any runtime path.
- `cli.py:77` — `_resolve_option`: defined, never called.

Dead code with latent bugs (finding 6) is worse than no code — it looks like a supported path and misleads the next contributor. Delete it or cover it with a real caller + test.

### 13. Minor correctness/quality nits worth a sweep

- `agent/loop.py:552` — the comment admits a deliberate "intentional double-append" for `RELOAD_SKILLS_SENTINEL` (a system message plus the tool message). Deliberate or not, appending a `system` role message mid-conversation after a tool call is unusual; verify your providers tolerate a `system` turn interleaved with `tool` turns, or switch it to a `user`/`tool` role.
- `tools/bash.py:25` — `subprocess.run(..., timeout=timeout)` with no `TimeoutExpired` handling; on timeout the captured output is lost and the model just sees `Error: Command '...' timed out`. Consider returning partial output.
- `tg/bot.py:147-155` — a fresh `SessionTracker` (and a new `session_*.jsonl`) is created on every turn because `_tracker` isn't threaded through; multi-turn Telegram conversations get fragmented across N log files. Reuse the tracker like the CLI does.

---

## ⚪ Testing & infrastructure observations

### 14. The test suite is not runnable as documented, and the RAM watchdog fails tests instead of skipping

`CLAUDE.local.md` mandates `conda run -n dagi python …`. On this machine `conda run -n dagi python` resolved to a **base Python 3.8** with no `pytest`/`openai` (the `dagi` env directory contains only `conda-meta/`, `etc/`, `.nonadmin` — no interpreter), so I could not execute the suite in the sanctioned environment. Whether that is machine-local breakage or a broken env spec, "the documented way to run the tests doesn't run the tests" is itself a release blocker — CI must be able to reproduce green.

Separately, `tests/conftest.py` installs an autouse RAM watchdog that raises `_RAMExceeded` into the test thread at **70%** system memory and `os._exit(1)`s at 90%. Running the suite on a busy dev box (already >70% from other apps) turns *every* test into an ERROR (`184 errors in 10.10s`) that has nothing to do with the code under test — I hit exactly this. A test harness that fails based on unrelated ambient memory pressure produces false alarms and trains people to ignore red. Gate this behind an opt-in env var, or make it `pytest.skip` rather than fail, and base it on the *test process'* RSS delta, not global `virtual_memory().percent`.

---

## What's good (credit where due)

- Path sandboxing (`tools/_path_guard.py`) is clean, correctly handles file-vs-dir roots, and is consistently applied across read/write/edit/grep/find/copy.
- The Windows CRLF normalization in `edit.py`/`write.py` is thoughtful and well-commented — a real bug class handled properly.
- Compaction (`tools/compact.py`) correctly respects the assistant/tool pairing invariant and snapshots for rollback on failure.
- The API-retry logic in `loop.py` (separate counters for transient errors vs. ghost responses, exponential backoff, pause-on-exhaustion) is genuinely robust.
- Config resolution, model-tier switching, and the subprocess subagent protocol are cohesive and readable.

---

## Prioritized action list

1. **Block release** on findings 1–4 (two guaranteed crashes, one RCE, one sandbox escape). All four are on primary paths and all four have small, contained fixes.
2. Fix 5–7 in the same pass (one-liners with real user-visible impact).
3. Add regression tests that would have caught 1 and 2: an image-read integration test, and a `run_one` smoke test. These are the two that a single test each would have prevented.
4. Sweep the dead code (12) and the medium nits (8–11, 13).
5. Get CI running the suite in a real `dagi` env and de-fang the RAM watchdog (14) so the suite is trustworthy.

The recurring theme is **missing coverage on the boundaries**: the one non-string tool result, the one attribute that got removed, the one config value that defaults to `None`, the remote surface with no auth. The happy path is well-built; the edges are where this needs to reach production standard.
