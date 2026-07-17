# DAGI TUI Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stream assistant text and reasoning token-by-token into a live TUI preview widget, while every downstream consumer (tool dispatch, tracker, compaction, non-TUI surfaces) keeps working unchanged on the fully-accumulated response.

**Architecture:** `AgentLoop` gains a streaming API-call path (`stream=True` + `stream_options={"include_usage": True}`) that accumulates chunks into the same `message`/`usage` shapes the blocking path produces, firing new no-op-default delta callbacks along the way. The TUI mounts a `StreamPreview` widget (Textual `Static`, hidden by default) that live-updates during a stream and hides when the turn's final panels are written to the append-only `RichLog` as today.

**Tech Stack:** Python 3.14 (conda env `dagi`), `openai` SDK chunk streaming, Textual/Rich for TUI, pytest.

**Spec:** `docs/superpowers/specs/2026-07-17-dagi-streaming-design.md`

**Conventions for every task:**
- Run tests with `conda run -n dagi python -m pytest <path> -v` (per CLAUDE.local.md, always use the `dagi` conda env).
- If `tests/conftest.py`'s RAM watchdog blocks pytest (fires when system RAM > 70% — known environment issue, see TODO.md 2026-07-16 entries), verify by invoking the test functions directly with `conda run -n dagi python -c "..."` and note this in the commit message.
- All commits go on the current branch; one commit per task.

**One deliberate deviation from the spec:** the spec says "config toggle, default on". The *dataclass* default for `AgentConfig.stream` is `False`; the *config-file* default (what `resolve_model_config` produces when `config.yaml` has no `stream:` key) is `True`. This is because dozens of existing tests and the benchmark harness construct `AgentConfig(...)` directly and mock `client.chat.completions.create` to return a single blocking response object — a dataclass default of `True` would make the loop try to iterate those mocks as streams and break the suite. Every real entry point (`tui.py`, `main.py`, `telegram_bot.py`, subagents) resolves config through `resolve_model_config`, so the user-facing default is still ON.

---

## File map

| File | Change |
|---|---|
| `agent/loop.py` | `AgentConfig.stream` field; 4 new `AgentCallbacks` fields; `_consume_stream()` method; streaming branch at the API call site; `httpx.HTTPError` in the connection-retry tuple |
| `agent/config_loader.py` | Resolve `stream` from per-model entry / top-level raw / default `True` |
| `config.example.yaml` | Document the `stream` key |
| `tui/streaming.py` | **New** — `StreamPreview` widget |
| `tui/app.py` | Yield `StreamPreview` in `compose()` |
| `tui/callbacks.py` | Wire the 4 new callbacks with a 50 ms throttle |
| `tests/test_config_loader.py` | `stream` resolution tests |
| `tests/test_agent_callbacks.py` | New-callback no-op default tests |
| `tests/test_streaming_loop.py` | **New** — `_consume_stream` + streaming `run()` tests |
| `tests/test_stream_preview.py` | **New** — widget pilot tests |
| `tests/test_tui_callbacks.py` | Streaming-callback wiring tests |
| `README.md`, `TODO.md` | Docs update (user's standing instruction) |

---

### Task 1: Config plumbing — `stream` key

**Files:**
- Modify: `agent/loop.py` (AgentConfig dataclass, ~line 154, next to `cache_prompt`)
- Modify: `agent/config_loader.py:117-154` (`_build_config_from_entry`)
- Modify: `config.example.yaml`
- Test: `tests/test_config_loader.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config_loader.py` (match the file's existing style for building temp config files — reuse its existing fixtures/helpers if it has them; the test bodies below show the required assertions):

```python
class TestStreamResolution:
    def test_stream_defaults_true_when_absent(self, tmp_path, monkeypatch):
        """No `stream` key anywhere → resolved config streams by default."""
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "default_model: m1\n"
            "models:\n"
            "  m1:\n"
            "    model: test/model\n"
            "    api_url: https://example.com/v1\n"
            "    api_key: sk-test\n",
            encoding="utf-8",
        )
        from agent.config_loader import resolve_model_config
        cfg = resolve_model_config("m1", config_path=cfg_file)
        assert cfg.stream is True

    def test_stream_global_false(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "default_model: m1\n"
            "stream: false\n"
            "models:\n"
            "  m1:\n"
            "    model: test/model\n"
            "    api_url: https://example.com/v1\n"
            "    api_key: sk-test\n",
            encoding="utf-8",
        )
        from agent.config_loader import resolve_model_config
        cfg = resolve_model_config("m1", config_path=cfg_file)
        assert cfg.stream is False

    def test_stream_per_model_overrides_global(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "default_model: m1\n"
            "stream: true\n"
            "models:\n"
            "  m1:\n"
            "    model: test/model\n"
            "    api_url: https://example.com/v1\n"
            "    api_key: sk-test\n"
            "    stream: false\n",
            encoding="utf-8",
        )
        from agent.config_loader import resolve_model_config
        cfg = resolve_model_config("m1", config_path=cfg_file)
        assert cfg.stream is False

    def test_dataclass_default_is_false(self):
        """Direct AgentConfig() construction (tests, benchmarks) must NOT stream —
        only configs resolved through config_loader get the streaming default."""
        from agent.loop import AgentConfig
        assert AgentConfig().stream is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/test_config_loader.py::TestStreamResolution -v`
Expected: 4 failures — `AttributeError: 'AgentConfig' object has no attribute 'stream'` (or `TypeError` on construction).

- [ ] **Step 3: Add the field to `AgentConfig`**

In `agent/loop.py`, directly under the `cache_prompt` field (~line 154):

```python
    # Streaming: consume the API response as a chunk stream, firing per-delta
    # callbacks. Dataclass default is False so direct AgentConfig() construction
    # (tests, benchmarks) keeps the blocking path; config_loader defaults the
    # config-file value to True, so all real entry points stream unless
    # config.yaml sets `stream: false` (globally or per-model).
    stream: bool = False
```

- [ ] **Step 4: Resolve it in `_build_config_from_entry`**

In `agent/config_loader.py`, next to the `cache_prompt` line (~line 124):

```python
    stream = bool(entry.get("stream", raw.get("stream", True)))
```

and add `stream=stream,` to the `AgentConfig(...)` constructor call at the bottom of the function (after `cache_prompt=cache_prompt,`).

Note: `worker_config` and `advanced_config` are built through this same function, so per-model `stream` overrides apply to them too. Tier switches (`_handle_switch_model`) do not copy `stream` — the session keeps the primary model's setting; this is a documented limitation in the spec.

- [ ] **Step 5: Document in `config.example.yaml`**

Find the top-level `thinking`/`cache_prompt` area and add:

```yaml
# Streaming: render assistant text/reasoning incrementally in the TUI as it
# is generated. true (default) = stream; false = wait for the full response.
# Can also be set per-model inside a models: entry to override the global value.
stream: true
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_config_loader.py -v`
Expected: all pass, including pre-existing tests.

- [ ] **Step 7: Commit**

```bash
git add agent/loop.py agent/config_loader.py config.example.yaml tests/test_config_loader.py
git commit -m "feat(streaming): add stream config key (file default on, dataclass default off)"
```

---

### Task 2: New `AgentCallbacks` fields

**Files:**
- Modify: `agent/loop.py:176-209` (AgentCallbacks dataclass)
- Test: `tests/test_agent_callbacks.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_callbacks.py`:

```python
class TestStreamingCallbackDefaults:
    def test_streaming_callbacks_default_to_noops(self):
        """The four streaming callbacks must exist with callable no-op defaults,
        so main.py / telegram_bot.py / scheduler need zero changes."""
        from agent.loop import AgentCallbacks
        cb = AgentCallbacks()
        # None of these may raise:
        cb.on_stream_start()
        cb.on_stream_end()
        cb.on_assistant_text_delta("chunk")
        cb.on_reasoning_delta("chunk")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_agent_callbacks.py::TestStreamingCallbackDefaults -v`
Expected: FAIL — `AttributeError: 'AgentCallbacks' object has no attribute 'on_stream_start'`.

- [ ] **Step 3: Add the fields**

In `agent/loop.py`, inside `AgentCallbacks` after `on_plan_shown` (~line 209):

```python
    # Streaming (config.stream=True only). on_stream_start fires before the first
    # chunk, on_stream_end always fires when consumption stops (even on error).
    # Deltas carry the raw incremental string for that chunk. The existing
    # on_assistant_text / on_reasoning still fire once afterward with full text.
    on_stream_start:         Callable[[], None]    = field(default=lambda: None)
    on_stream_end:           Callable[[], None]    = field(default=lambda: None)
    on_assistant_text_delta: Callable[[str], None] = field(default=lambda t: None)
    on_reasoning_delta:      Callable[[str], None] = field(default=lambda t: None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_agent_callbacks.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/loop.py tests/test_agent_callbacks.py
git commit -m "feat(streaming): add no-op-default streaming callbacks to AgentCallbacks"
```

---

### Task 3: `AgentLoop._consume_stream()`

**Files:**
- Modify: `agent/loop.py` (new method on `AgentLoop`, place directly above `run()`; new import)
- Test: Create `tests/test_streaming_loop.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_streaming_loop.py`. The `_make_loop` helper is copied from `tests/test_continuation.py:38-70` (subagent workers may execute tasks out of order, so it is repeated here rather than imported):

```python
"""tests/test_streaming_loop.py — _consume_stream accumulation + streaming run() path."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.loop import AgentCallbacks, AgentConfig, AgentLoop


def _make_loop(callbacks=None, **config_kwargs) -> AgentLoop:
    """Create an AgentLoop with all heavy dependencies mocked out."""
    config = AgentConfig(
        model="test-model",
        api_key="test-key",
        system_prompt="You are a test agent.",
        **config_kwargs,
    )
    fake_registry = MagicMock()
    fake_registry.get_openai_tools_list.return_value = []
    fake_registry.list_tools.return_value = []
    fake_tracker = MagicMock()
    with (
        patch("agent.loop.SessionTracker", return_value=fake_tracker),
        patch("openai.OpenAI"),
        patch.object(Path, "exists", return_value=False),
    ):
        loop = AgentLoop(
            config=config,
            callbacks=callbacks,
            _registry=fake_registry,
            _tracker=fake_tracker,
        )
    loop.tracker = fake_tracker
    loop.registry = fake_registry
    return loop


# ── Chunk factories ──────────────────────────────────────────────────────────

def _chunk(content=None, reasoning=None, tool_calls=None, usage=None, no_choices=False):
    """Build a fake streaming chunk. no_choices=True mimics the trailing
    usage-only chunk OpenRouter/OpenAI send with choices=[]."""
    if no_choices:
        return SimpleNamespace(choices=[], usage=usage)
    delta = SimpleNamespace(
        content=content,
        reasoning=reasoning,
        reasoning_content=None,
        tool_calls=tool_calls,
        model_extra={},
    )
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=usage)


def _tc_delta(index, id=None, name=None, arguments=None):
    """One partial tool-call inside a chunk's delta.tool_calls list."""
    fn = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=id, function=fn)


def _usage(prompt=10, completion=5):
    return SimpleNamespace(
        prompt_tokens=prompt, completion_tokens=completion,
        cost=None, completion_tokens_details=None,
    )


# ── _consume_stream unit tests ───────────────────────────────────────────────

class TestConsumeStream:
    def test_content_accumulated_and_deltas_fired(self):
        deltas: list[str] = []
        cb = AgentCallbacks(on_assistant_text_delta=deltas.append)
        loop = _make_loop(callbacks=cb)
        msg, usage = loop._consume_stream(iter([
            _chunk(content="Hel"), _chunk(content="lo"), _chunk(content="!"),
        ]))
        assert msg.content == "Hello!"
        assert deltas == ["Hel", "lo", "!"]
        assert msg.tool_calls is None
        assert usage is None

    def test_reasoning_accumulated_and_deltas_fired(self):
        deltas: list[str] = []
        cb = AgentCallbacks(on_reasoning_delta=deltas.append)
        loop = _make_loop(callbacks=cb)
        msg, _ = loop._consume_stream(iter([
            _chunk(reasoning="think"), _chunk(reasoning="ing"), _chunk(content="done"),
        ]))
        assert msg.reasoning_content == "thinking"
        assert deltas == ["think", "ing"]
        assert msg.content == "done"

    def test_tool_calls_reassembled_by_index(self):
        loop = _make_loop()
        msg, _ = loop._consume_stream(iter([
            _chunk(tool_calls=[_tc_delta(0, id="call_1", name="read", arguments='{"pa')]),
            _chunk(tool_calls=[_tc_delta(0, arguments='th": "x.py"}')]),
            _chunk(tool_calls=[_tc_delta(1, id="call_2", name="bash", arguments='{"command": "ls"}')]),
        ]))
        assert len(msg.tool_calls) == 2
        assert msg.tool_calls[0].id == "call_1"
        assert msg.tool_calls[0].function.name == "read"
        assert msg.tool_calls[0].function.arguments == '{"path": "x.py"}'
        assert msg.tool_calls[1].function.name == "bash"

    def test_trailing_usage_chunk_captured(self):
        loop = _make_loop()
        msg, usage = loop._consume_stream(iter([
            _chunk(content="hi"),
            _chunk(no_choices=True, usage=_usage(prompt=42, completion=7)),
        ]))
        assert usage.prompt_tokens == 42
        assert usage.completion_tokens == 7

    def test_missing_usage_yields_none(self):
        loop = _make_loop()
        _, usage = loop._consume_stream(iter([_chunk(content="hi")]))
        assert usage is None

    def test_stream_start_and_end_fired_once(self):
        events: list[str] = []
        cb = AgentCallbacks(
            on_stream_start=lambda: events.append("start"),
            on_stream_end=lambda: events.append("end"),
        )
        loop = _make_loop(callbacks=cb)
        loop._consume_stream(iter([_chunk(content="x")]))
        assert events == ["start", "end"]

    def test_stream_end_fires_even_when_iteration_raises(self):
        events: list[str] = []
        cb = AgentCallbacks(on_stream_end=lambda: events.append("end"))
        loop = _make_loop(callbacks=cb)

        def _boom():
            yield _chunk(content="par")
            raise ConnectionError("dropped")

        with pytest.raises(ConnectionError):
            loop._consume_stream(_boom())
        assert events == ["end"]

    def test_empty_stream_gives_ghost_shaped_message(self):
        """No chunks at all → content None, no tool calls — the exact shape
        the existing ghost-response check detects."""
        loop = _make_loop()
        msg, usage = loop._consume_stream(iter([]))
        assert msg.content is None
        assert msg.tool_calls is None
        assert usage is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/test_streaming_loop.py::TestConsumeStream -v`
Expected: 8 failures — `AttributeError: 'AgentLoop' object has no attribute '_consume_stream'`.

- [ ] **Step 3: Implement `_consume_stream`**

In `agent/loop.py`, add to the imports at the top of the file (if not already present):

```python
from types import SimpleNamespace
```

Add this method to `AgentLoop`, directly above `def run(`:

```python
    def _consume_stream(self, stream) -> "tuple[SimpleNamespace, object | None]":
        """Accumulate a chat-completions chunk stream into the same
        (message, usage) shapes the blocking path produces, firing per-delta
        callbacks as chunks arrive.

        Returned message mimics response.choices[0].message: .content,
        .tool_calls (list of .id/.function.name/.function.arguments, or None),
        .reasoning_content (for _extract_reasoning). usage is the provider's
        trailing usage object, or None if it never arrived — downstream
        getattr(usage, ..., 0) patterns already tolerate None.
        """
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls_acc: dict[int, dict] = {}
        usage = None
        self.callbacks.on_stream_start()
        try:
            for chunk in stream:
                if getattr(chunk, "usage", None) is not None:
                    usage = chunk.usage
                if not getattr(chunk, "choices", None):
                    continue  # usage-only trailing chunk has choices=[]
                delta = chunk.choices[0].delta
                if delta is None:
                    continue

                piece = getattr(delta, "content", None)
                if piece:
                    content_parts.append(piece)
                    self.callbacks.on_assistant_text_delta(piece)

                # OpenRouter sends `reasoning`; some providers send
                # `reasoning_content`; SDK may park unknown keys in model_extra.
                r = getattr(delta, "reasoning", None) or getattr(delta, "reasoning_content", None)
                if not r:
                    extras = getattr(delta, "model_extra", None) or {}
                    r = extras.get("reasoning") or ""
                if r:
                    reasoning_parts.append(r)
                    self.callbacks.on_reasoning_delta(r)

                for tc in getattr(delta, "tool_calls", None) or []:
                    acc = tool_calls_acc.setdefault(
                        tc.index, {"id": "", "name": "", "arguments": ""}
                    )
                    if getattr(tc, "id", None):
                        acc["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            acc["name"] = fn.name
                        if getattr(fn, "arguments", None):
                            acc["arguments"] += fn.arguments
        finally:
            self.callbacks.on_stream_end()

        tool_calls = [
            SimpleNamespace(
                id=acc["id"],
                type="function",
                function=SimpleNamespace(name=acc["name"], arguments=acc["arguments"]),
            )
            for _idx, acc in sorted(tool_calls_acc.items())
        ] or None
        message = SimpleNamespace(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
            reasoning_content="".join(reasoning_parts) or None,
        )
        return message, usage
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_streaming_loop.py -v`
Expected: 8 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/loop.py tests/test_streaming_loop.py
git commit -m "feat(streaming): add AgentLoop._consume_stream chunk accumulator"
```

---

### Task 4: Wire the streaming branch into `run()`

**Files:**
- Modify: `agent/loop.py:399-450` (the API-call-with-retry block inside `run()`)
- Test: `tests/test_streaming_loop.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_streaming_loop.py`:

```python
import httpx
import openai

from agent.loop import TASK_END_FLAG


def _stream_client(*chunk_lists):
    """Fake OpenAI client whose create() returns successive chunk iterators.
    Asserts stream kwargs are passed. Each call consumes the next chunk list."""
    calls = {"n": 0, "kwargs": []}

    def create(**kwargs):
        calls["kwargs"].append(kwargs)
        i = calls["n"]
        calls["n"] += 1
        item = chunk_lists[i]
        if isinstance(item, Exception):
            raise item
        if callable(item):          # generator factory → mid-stream error support
            return item()
        return iter(item)

    client = MagicMock()
    client.chat.completions.create.side_effect = create
    return client, calls


class TestStreamingRun:
    def test_streaming_turn_end_to_end(self):
        """A streamed text-only turn: deltas fire, final on_assistant_text fires
        with full text, token update uses the trailing usage chunk."""
        deltas: list[str] = []
        finals: list[str] = []
        tokens: list[tuple] = []
        cb = AgentCallbacks(
            on_assistant_text_delta=deltas.append,
            on_assistant_text=finals.append,
            on_token_update=lambda i, o, c, t: tokens.append((i, o)),
        )
        loop = _make_loop(callbacks=cb, stream=True)
        loop.client, calls = _stream_client([
            _chunk(content="Done. "),
            _chunk(content=TASK_END_FLAG),
            _chunk(no_choices=True, usage=_usage(prompt=33, completion=9)),
        ])
        result = loop.run("do the thing")
        assert result == "Done."
        assert deltas == ["Done. ", TASK_END_FLAG]
        assert any("Done." in f for f in finals)
        assert (33, 9) in tokens
        # The API call itself must request streaming + usage:
        assert calls["kwargs"][0]["stream"] is True
        assert calls["kwargs"][0]["stream_options"] == {"include_usage": True}

    def test_non_streaming_config_never_passes_stream_kwarg(self):
        """config.stream=False (dataclass default) → identical call to today."""
        loop = _make_loop()  # stream defaults False
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content=f"ok {TASK_END_FLAG}", tool_calls=[], model_extra={},
            ))],
            usage=_usage(),
        )
        loop.client = MagicMock()
        loop.client.chat.completions.create.return_value = response
        loop.run("task")
        _, kwargs = loop.client.chat.completions.create.call_args
        assert "stream" not in kwargs
        assert "stream_options" not in kwargs

    def test_streamed_tool_call_dispatches(self):
        """Tool-call deltas reassemble and dispatch through the registry."""
        loop = _make_loop(stream=True)
        loop.registry.dispatch.return_value = "tool ran"
        loop.registry._tools = {}
        loop.client, _ = _stream_client(
            [   # turn 1: a tool call split across chunks
                _chunk(tool_calls=[_tc_delta(0, id="c1", name="bash", arguments='{"comma')]),
                _chunk(tool_calls=[_tc_delta(0, arguments='nd": "echo hi"}')]),
                _chunk(no_choices=True, usage=_usage()),
            ],
            [   # turn 2: finish
                _chunk(content=f"finished {TASK_END_FLAG}"),
                _chunk(no_choices=True, usage=_usage()),
            ],
        )
        result = loop.run("run echo")
        assert result == "finished"
        loop.registry.dispatch.assert_called_once_with(
            "bash", {"command": "echo hi"}
        )

    def test_midstream_connection_error_retries_whole_call(self):
        """A stream that dies mid-iteration is retried from scratch via the
        existing connection-retry path; partial accumulation is discarded."""
        def _dying():
            yield _chunk(content="partial ")
            raise openai.APIConnectionError(request=httpx.Request("POST", "http://test"))

        finals: list[str] = []
        cb = AgentCallbacks(on_assistant_text=finals.append)
        loop = _make_loop(callbacks=cb, stream=True, api_error_retries=3)
        loop.client, calls = _stream_client(
            _dying,
            [
                _chunk(content=f"complete {TASK_END_FLAG}"),
                _chunk(no_choices=True, usage=_usage()),
            ],
        )
        with patch("agent.loop.time.sleep"):  # skip the backoff delay
            result = loop.run("task")
        assert result == "complete"
        assert calls["n"] == 2
        # The partial text must not leak into any final assistant text:
        assert not any("partial" in f for f in finals)

    def test_ghost_stream_retries(self):
        """An empty stream (no content, no tool calls, no usage) is a ghost
        response — silently retried like the blocking path."""
        loop = _make_loop(stream=True)
        loop.client, calls = _stream_client(
            [],  # ghost: zero chunks
            [
                _chunk(content=f"real {TASK_END_FLAG}"),
                _chunk(no_choices=True, usage=_usage()),
            ],
        )
        result = loop.run("task")
        assert result == "real"
        assert calls["n"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/test_streaming_loop.py::TestStreamingRun -v`
Expected: `test_non_streaming_config_never_passes_stream_kwarg` PASSES (that's today's behavior); the other 4 FAIL (the loop treats the chunk iterator as a response object → `AttributeError` on `.choices`).

- [ ] **Step 3: Implement the streaming branch**

In `agent/loop.py`:

a) Add to the top-of-file imports (if not already present): `import httpx`

b) Replace the single `create()` call at ~line 402-408:

```python
                        response = self.client.chat.completions.create(
                            model=self.config.model,
                            messages=self._messages,
                            tools=self.registry.get_openai_tools_list(),
                            parallel_tool_calls=False,
                            **(dict(extra_body=self._extra_body) if self._extra_body else {}),
                        )
```

with:

```python
                        _create_kwargs = dict(
                            model=self.config.model,
                            messages=self._messages,
                            tools=self.registry.get_openai_tools_list(),
                            parallel_tool_calls=False,
                            **(dict(extra_body=self._extra_body) if self._extra_body else {}),
                        )
                        if self.config.stream:
                            _stream = self.client.chat.completions.create(
                                stream=True,
                                stream_options={"include_usage": True},
                                **_create_kwargs,
                            )
                            # Mid-stream errors raised while iterating are caught
                            # by the surrounding except clauses → same retry path
                            # as a failed create(); partial accumulation discarded.
                            _msg, _usage = self._consume_stream(_stream)
                            response = SimpleNamespace(
                                choices=[SimpleNamespace(message=_msg)], usage=_usage
                            )
                        else:
                            response = self.client.chat.completions.create(**_create_kwargs)
```

c) Extend the connection-error except tuple at ~line 409 from:

```python
                    except (openai.APIConnectionError, openai.APITimeoutError):
```

to:

```python
                    except (openai.APIConnectionError, openai.APITimeoutError, httpx.HTTPError):
```

(`httpx.HTTPError` is the base of `httpx.ReadError`/`RemoteProtocolError`, which the SDK can surface when a stream's transport drops mid-iteration. Harmless for the blocking path — the SDK wraps transport errors before they escape `create()`.)

Nothing after the retry block changes: the ghost check reads `response.choices[0].message` / `response.usage`, `_extract_reasoning` finds `.reasoning_content` on the shim, tool dispatch reads `tc.id`/`tc.function.name`/`tc.function.arguments`, and `record_assistant`/`on_token_update`/compaction all use `getattr(usage, ..., 0) or 0` patterns that tolerate `usage=None`.

- [ ] **Step 4: Run the new tests, then the full suite**

Run: `conda run -n dagi python -m pytest tests/test_streaming_loop.py -v`
Expected: all PASS.

Run: `conda run -n dagi python -m pytest tests/ -q`
Expected: no new failures vs. the pre-task baseline (7 pre-existing `tests/dagi_eval/` failures from missing numpy are known-unrelated; the RAM-watchdog caveat from the plan header applies).

- [ ] **Step 5: Commit**

```bash
git add agent/loop.py tests/test_streaming_loop.py
git commit -m "feat(streaming): stream API responses in AgentLoop when config.stream is on"
```

---

### Task 5: `StreamPreview` TUI widget

**Files:**
- Create: `tui/streaming.py`
- Modify: `tui/app.py:58-68` (`compose()`)
- Test: Create `tests/test_stream_preview.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_stream_preview.py` (sync-wrapping-async pattern copied from `tests/test_prompt_input_multiline.py`):

```python
"""tests/test_stream_preview.py — StreamPreview live-stream widget."""
from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult

from tui.streaming import StreamPreview


class _App(App[None]):
    def compose(self) -> ComposeResult:
        yield StreamPreview(id="stream-preview")


def test_hidden_by_default() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test():
            w = app.query_one(StreamPreview)
            assert w.styles.display == "none"
    asyncio.run(run())


def test_show_progress_makes_visible_and_renders_text() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test():
            w = app.query_one(StreamPreview)
            w.show_progress("", "Hello wor")
            assert w.styles.display == "block"
            rendered = str(w._render_tail("", "Hello wor"))
            assert "Hello wor" in rendered
    asyncio.run(run())


def test_finish_hides_and_clears() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test():
            w = app.query_one(StreamPreview)
            w.show_progress("thinking...", "text")
            w.finish()
            assert w.styles.display == "none"
    asyncio.run(run())


def test_render_tail_keeps_only_last_lines() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test():
            w = app.query_one(StreamPreview)
            long_text = "\n".join(f"line {i}" for i in range(50))
            rendered = str(w._render_tail("", long_text))
            assert "line 49" in rendered          # newest line kept
            assert "line 0" not in rendered       # oldest trimmed
            assert len(rendered.splitlines()) <= StreamPreview.TAIL_LINES
    asyncio.run(run())


def test_render_tail_includes_reasoning_before_text() -> None:
    async def run() -> None:
        app = _App()
        async with app.run_test():
            w = app.query_one(StreamPreview)
            rendered = str(w._render_tail("pondering", "answer"))
            assert rendered.index("pondering") < rendered.index("answer")
    asyncio.run(run())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/test_stream_preview.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tui.streaming'`.

- [ ] **Step 3: Implement the widget**

Create `tui/streaming.py`:

```python
from __future__ import annotations

from rich.text import Text
from textual.widgets import Static


class StreamPreview(Static):
    """Live preview of the currently-streaming assistant turn.

    ConversationPane is a RichLog — append-only, so in-flight text cannot be
    updated there without leaving stale partial copies in scrollback. This
    widget shows the growing reasoning/text while a response streams; when the
    stream ends it hides again and the final Markdown/Panel is written to the
    conversation pane exactly as before streaming existed.

    Hidden via DEFAULT_CSS until show_progress() is first called. Only the
    last TAIL_LINES lines are rendered so the preview never crowds out the
    conversation; the full text always lands in the conversation pane at the
    end of the turn.
    """

    TAIL_LINES = 12

    DEFAULT_CSS = """
    StreamPreview {
        display: none;
        height: auto;
        max-height: 14;
        padding: 0 1;
        border-top: dashed $panel;
        color: $text-muted;
    }
    """

    def show_progress(self, reasoning: str, text: str) -> None:
        """Render the accumulated stream so far and make the widget visible."""
        self.styles.display = "block"
        self.update(self._render_tail(reasoning, text))

    def finish(self) -> None:
        """Hide and clear — the final text is written to the conversation pane."""
        self.styles.display = "none"
        self.update("")

    def _render_tail(self, reasoning: str, text: str) -> Text:
        out = Text()
        if reasoning:
            out.append("🧠 ", style="dim")
            out.append(reasoning.strip(), style="dim italic")
        if reasoning and text:
            out.append("\n\n")
        if text:
            out.append(text)
        lines = out.split("\n", allow_blank=True)
        if len(lines) > self.TAIL_LINES:
            lines = lines[-self.TAIL_LINES:]
        return Text("\n").join(lines)
```

- [ ] **Step 4: Mount it in the TUI**

In `tui/app.py`:

a) Add the import next to the other `tui` imports:

```python
from .streaming import StreamPreview
```

b) In `compose()` (~line 66), insert between `ConversationPane` and the running indicator:

```python
        yield ConversationPane(id="conversation", highlight=True, markup=True, wrap=True)
        yield StreamPreview(id="stream-preview")
        yield Static("", id="running-indicator")
```

(No `DagiApp.CSS` change needed — the widget carries its own `DEFAULT_CSS`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_stream_preview.py -v`
Expected: 5 PASS.

- [ ] **Step 6: Commit**

```bash
git add tui/streaming.py tui/app.py tests/test_stream_preview.py
git commit -m "feat(streaming): add StreamPreview widget to the TUI layout"
```

---

### Task 6: Wire streaming callbacks in `tui/callbacks.py`

**Files:**
- Modify: `tui/callbacks.py:18-119` (`build_callbacks`)
- Test: `tests/test_tui_callbacks.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tui_callbacks.py` (reuses the module's existing `_make_app` helper — note its `app.query_one` returns one shared mock for every widget class, so `app._conv` doubles as the `StreamPreview` mock):

```python
class TestStreamingWiring:
    def test_stream_start_resets_and_deltas_update_preview(self):
        app = _make_app()
        callbacks = build_callbacks(app, loop_ref=[])
        callbacks.on_stream_start()
        callbacks.on_assistant_text_delta("Hello ")
        callbacks.on_reasoning_delta("hmm")
        # show_progress called with ACCUMULATED strings, not raw chunks:
        calls = app._conv.show_progress.call_args_list
        assert calls, "deltas must drive StreamPreview.show_progress"
        last_reasoning, last_text = calls[-1].args
        assert last_text == "Hello "
        assert last_reasoning == "hmm"

    def test_deltas_accumulate_across_calls(self):
        app = _make_app()
        callbacks = build_callbacks(app, loop_ref=[])
        callbacks.on_stream_start()
        callbacks.on_assistant_text_delta("Hel")
        # Second delta lands inside the 50 ms throttle window → may be skipped,
        # but the forced flush on stream end must still carry the full text:
        callbacks.on_assistant_text_delta("lo")
        # The final flush on stream end always carries the full accumulation:
        callbacks.on_stream_end()
        # stream end hides the preview:
        assert app._conv.finish.called
        # and the last show_progress before it saw the full text:
        last_reasoning, last_text = app._conv.show_progress.call_args_list[-1].args
        assert last_text == "Hello"

    def test_stream_end_always_finishes_preview(self):
        app = _make_app()
        callbacks = build_callbacks(app, loop_ref=[])
        callbacks.on_stream_start()
        callbacks.on_stream_end()
        assert app._conv.finish.called

    def test_second_stream_starts_clean(self):
        """A new stream must not inherit the previous turn's text."""
        app = _make_app()
        callbacks = build_callbacks(app, loop_ref=[])
        callbacks.on_stream_start()
        callbacks.on_assistant_text_delta("first turn")
        callbacks.on_stream_end()
        callbacks.on_stream_start()
        callbacks.on_assistant_text_delta("second")
        callbacks.on_stream_end()
        _, last_text = app._conv.show_progress.call_args_list[-1].args
        assert last_text == "second"
        assert "first turn" not in last_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/test_tui_callbacks.py::TestStreamingWiring -v`
Expected: 4 failures — `AgentCallbacks` defaults are no-ops, so `show_progress`/`finish` are never called.

- [ ] **Step 3: Implement the wiring**

In `tui/callbacks.py`:

a) Add imports at the top:

```python
import time

from .streaming import StreamPreview
```

b) Inside `build_callbacks`, after `conv = app.query_one(ConversationPane)`:

```python
    preview = app.query_one(StreamPreview)
```

c) Add the handlers (place next to `on_reasoning`):

```python
    # ── Streaming preview ────────────────────────────────────────────────
    # State lives here (agent-thread-only access: start → deltas → end are
    # all fired from the agent worker thread, never concurrently).
    # call_from_thread is throttled to ≥50 ms between UI refreshes so fast
    # token streams don't stall the agent thread; every flush passes the FULL
    # accumulated strings, so skipped refreshes lose nothing.
    _stream = {"reasoning": "", "text": "", "last_flush": 0.0}
    _FLUSH_INTERVAL = 0.05

    def _flush_stream(force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - _stream["last_flush"]) < _FLUSH_INTERVAL:
            return
        _stream["last_flush"] = now
        app.call_from_thread(preview.show_progress, _stream["reasoning"], _stream["text"])

    def on_stream_start() -> None:
        _stream["reasoning"] = ""
        _stream["text"] = ""
        _stream["last_flush"] = 0.0

    def on_assistant_text_delta(chunk: str) -> None:
        _stream["text"] += chunk
        _flush_stream()

    def on_reasoning_delta(chunk: str) -> None:
        _stream["reasoning"] += chunk
        _flush_stream()

    def on_stream_end() -> None:
        if _stream["reasoning"] or _stream["text"]:
            _flush_stream(force=True)   # final render with the complete text
        app.call_from_thread(preview.finish)
```

d) Register them in the `AgentCallbacks(...)` constructor at the bottom of `build_callbacks`:

```python
        on_stream_start=on_stream_start, on_stream_end=on_stream_end,
        on_assistant_text_delta=on_assistant_text_delta,
        on_reasoning_delta=on_reasoning_delta,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_tui_callbacks.py -v`
Expected: all PASS (new class + the 5 pre-existing notify tests, which are unaffected because `_make_app`'s shared `query_one` mock absorbs the new `query_one(StreamPreview)` call).

- [ ] **Step 5: Commit**

```bash
git add tui/callbacks.py tests/test_tui_callbacks.py
git commit -m "feat(streaming): wire delta callbacks to StreamPreview with 50ms throttle"
```

---

### Task 7: Live verification, docs, and wrap-up

**Files:**
- Modify: `README.md`, `TODO.md`

- [ ] **Step 1: Full test suite**

Run: `conda run -n dagi python -m pytest tests/ -q`
Expected: no new failures vs. baseline (known exceptions: 7 `tests/dagi_eval/` numpy failures; RAM-watchdog caveat).

- [ ] **Step 2: Manual TUI smoke test (requires a real API key — one short billed call)**

Run: `conda run --no-capture-output -n dagi python tui.py`
Send a trivial task (e.g. "say hello and end the turn"). Verify:
1. While generating, a dim preview area appears above the input box and grows as text arrives.
2. When the turn completes, the preview disappears and the normal Markdown message + `— turn complete —` marker appear in the conversation pane.
3. With a thinking-enabled model (`thinking: high` on a reasoning model), the 🧠 reasoning tail streams in the preview before the answer text.
4. Set `stream: false` in `config.yaml`, restart, repeat — behavior identical to pre-change (no preview, full response at once).

If no API budget is available, skip and note it — the mocked tests in Task 4 cover the loop mechanics.

- [ ] **Step 3: Update README.md**

- In the TUI section (`### Interactive TUI`), add a sentence: while a response is being generated, assistant text and reasoning stream live into a preview area above the input box; the finished message is then written to the conversation pane as before.
- In the Configuration section, document the `stream` key (global + per-model override, default on, escape hatch for providers that misbehave with streaming), mirroring how `thinking` is documented.

- [ ] **Step 4: Update TODO.md**

Add a Completed entry dated with the actual completion date, following the file's existing format (problem → fix → test), covering: config key, `_consume_stream`, streaming branch + mid-stream retry, `StreamPreview`, callback wiring + throttle. Note the dataclass-default-False / config-default-True decision explicitly.

- [ ] **Step 5: Commit**

```bash
git add README.md TODO.md
git commit -m "docs: document TUI streaming support"
```

---

## Self-review notes

- **Spec coverage:** config surface → Task 1; `_consume_stream` + delta/start/end callbacks → Tasks 2–3; call-site wiring, mid-stream retry, ghost check, usage degradation → Task 4; live widget → Task 5; TUI wiring + throttle → Task 6; testing/regression + docs → Tasks 4/7. The spec's "mount/unmount" of the preview is implemented as a permanently-composed widget toggling `display` — same visual behavior, simpler thread-safe implementation; noted here as an intentional refinement.
- **Type consistency:** `show_progress(reasoning, text)` / `finish()` names match between Task 5 (definition), Task 6 (wiring), and both test files. `_consume_stream` returns `(message, usage)` consumed only in Task 4's shim.
- **Known limitation carried from spec:** tier switches (`switch_model`) don't re-resolve `stream` per tier; the session keeps the primary model's setting.
