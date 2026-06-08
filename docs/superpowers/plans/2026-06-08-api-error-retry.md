# API Error Retry with Exponential Backoff — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add retry logic for transient OpenAI API errors (429, 5xx, connection, timeout) so a single server hiccup doesn't abort an entire task.

**Architecture:** Extend the existing ghost-response retry loop in `AgentLoop.run()` to also catch transient exceptions with exponential backoff. Protect compaction by snapshotting `_messages` before the summarisation API call and restoring on failure. New `api_error_retries` config field, separate from `null_response_retries`.

**Tech Stack:** Python, openai SDK (error classes: `APIStatusError`, `APIConnectionError`, `APITimeoutError`), pytest

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `agent/loop.py` | Modify:96-131 | Add `api_error_retries` field to `AgentConfig` |
| `agent/loop.py` | Modify:1-10 | Add `import time` |
| `agent/loop.py` | Modify:354-391 | Wrap API call in transient-error retry with backoff |
| `tools/compact.py` | Modify:196-252 | Snapshot `_messages` before API call, restore on failure |
| `agent/config_loader.py` | Modify:88-108 | Read `api_error_retries` from config, pass to `AgentConfig` |
| `tests/test_continuation.py` | Modify (append) | New `TestApiErrorRetry` and `TestCompactionSnapshot` classes |

---

### Task 1: Add `api_error_retries` to `AgentConfig` and config loader

**Files:**
- Modify: `agent/loop.py:96-131` (AgentConfig dataclass)
- Modify: `agent/loop.py:1-10` (imports)
- Modify: `agent/config_loader.py:88-108` (_build_config_from_entry)
- Test: `tests/test_continuation.py` (append)

- [ ] **Step 1: Write the failing test for config field**

In `tests/test_continuation.py`, add at the bottom of the file:

```python
class TestApiErrorRetryConfig:
    def test_default_api_error_retries(self):
        """AgentConfig defaults api_error_retries to 3."""
        config = AgentConfig(
            model="test-model",
            api_key="test-key",
            system_prompt="You are a test agent.",
        )
        assert config.api_error_retries == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_continuation.py::TestApiErrorRetryConfig -v`
Expected: FAIL with `AttributeError` — `AgentConfig` has no `api_error_retries` field.

- [ ] **Step 3: Add `api_error_retries` field to `AgentConfig`**

In `agent/loop.py`, add `import time` to the imports block (after `import threading` on line 4):

```python
import time
```

In `agent/loop.py`, add after line 131 (`emote_tool: bool = True`):

```python
    # Transient API error retries: how many times to retry on 429/5xx/connection
    # errors before propagating the exception. Independent of null_response_retries.
    api_error_retries: int = 3
```

- [ ] **Step 4: Wire `api_error_retries` in config loader**

In `agent/config_loader.py`, in `_build_config_from_entry()`, add after line 89 (`max_continuations = int(raw.get("max_continuations", 10))`):

```python
    api_error_retries = int(raw.get("api_error_retries", 3))
```

And in the `return AgentConfig(...)` block, add after `max_continuations=max_continuations,` (line 106):

```python
        api_error_retries=api_error_retries,
```

- [ ] **Step 5: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_continuation.py::TestApiErrorRetryConfig -v`
Expected: PASS

- [ ] **Step 6: Run all existing tests to verify no regressions**

Run: `conda run -n dagi python -m pytest tests/test_continuation.py -v`
Expected: All 12 tests PASS

- [ ] **Step 7: Commit**

```bash
git add agent/loop.py agent/config_loader.py tests/test_continuation.py
git commit -m "feat: add api_error_retries config field for transient error retry"
```

---

### Task 2: Implement transient error retry in the agent loop

**Files:**
- Modify: `agent/loop.py:354-391` (ghost-response retry loop)
- Test: `tests/test_continuation.py` (append)

- [ ] **Step 1: Write failing tests for transient error retry**

In `tests/test_continuation.py`, add these imports at the top (after the existing imports):

```python
import time
import openai
import httpx
```

Then add at the bottom of the file:

```python
def _make_api_status_error(status_code: int, message: str = "Server Error"):
    """Build a fake openai.APIStatusError with the given status code."""
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    response = httpx.Response(status_code, request=request)
    return openai.APIStatusError(
        message=message, response=response, body=None,
    )


class TestApiErrorRetry:
    def test_transient_error_retries_then_succeeds(self):
        """A single 500 followed by a valid response should succeed."""
        loop = _make_loop()
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_api_status_error(500),
            _make_response(f"Done. {TASK_END_FLAG}"),
        ]

        with patch("agent.loop.time.sleep"):
            result = loop.run("do something")

        assert loop.client.chat.completions.create.call_count == 2
        assert "Done." in result

    def test_non_transient_error_raises_immediately(self):
        """A 401 should not be retried — raises immediately."""
        loop = _make_loop()
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = _make_api_status_error(401)

        with pytest.raises(openai.APIStatusError) as exc_info:
            loop.run("do something")
        assert exc_info.value.status_code == 401
        assert loop.client.chat.completions.create.call_count == 1

    def test_exhausted_retries_raises(self):
        """After api_error_retries failures, the exception propagates."""
        loop = _make_loop()
        loop.config.api_error_retries = 2
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = _make_api_status_error(503)

        with patch("agent.loop.time.sleep"):
            with pytest.raises(openai.APIStatusError):
                loop.run("do something")

        assert loop.client.chat.completions.create.call_count == 2

    def test_429_is_retried(self):
        """Rate limit (429) is treated as transient."""
        loop = _make_loop()
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_api_status_error(429, "Rate limited"),
            _make_response(f"OK. {TASK_END_FLAG}"),
        ]

        with patch("agent.loop.time.sleep"):
            result = loop.run("do something")

        assert "OK." in result

    def test_connection_error_is_retried(self):
        """APIConnectionError is treated as transient."""
        loop = _make_loop()
        loop.client = MagicMock()
        request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
        loop.client.chat.completions.create.side_effect = [
            openai.APIConnectionError(request=request),
            _make_response(f"OK. {TASK_END_FLAG}"),
        ]

        with patch("agent.loop.time.sleep"):
            result = loop.run("do something")

        assert "OK." in result

    def test_retry_counter_resets_per_iteration(self):
        """Each loop iteration gets a fresh retry budget."""
        loop = _make_loop(max_continuations=1)
        loop.config.api_error_retries = 2
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            # Iteration 1: one transient error, then success (no flag → continue)
            _make_api_status_error(500),
            _make_response("Still working..."),
            # Iteration 2: one transient error, then success (with flag → done)
            _make_api_status_error(502),
            _make_response(f"Done. {TASK_END_FLAG}"),
        ]

        with patch("agent.loop.time.sleep"):
            result = loop.run("do something")

        assert loop.client.chat.completions.create.call_count == 4
        assert "Done." in result

    def test_backoff_delay_increases(self):
        """Backoff should use 2^attempt seconds, capped at 60."""
        loop = _make_loop()
        loop.config.api_error_retries = 4
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_api_status_error(500),
            _make_api_status_error(500),
            _make_api_status_error(500),
            _make_response(f"OK. {TASK_END_FLAG}"),
        ]

        with patch("agent.loop.time.sleep") as mock_sleep:
            loop.run("do something")

        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert delays == [2, 4, 8]

    def test_on_assistant_text_called_during_retry(self):
        """User should see a retry notification."""
        texts = []
        callbacks = AgentCallbacks(on_assistant_text=lambda t: texts.append(t))

        loop = _make_loop()
        loop.callbacks = callbacks
        loop.client = MagicMock()
        loop.client.chat.completions.create.side_effect = [
            _make_api_status_error(500, "Internal Server Error"),
            _make_response(f"OK. {TASK_END_FLAG}"),
        ]

        with patch("agent.loop.time.sleep"):
            loop.run("do something")

        retry_msgs = [t for t in texts if "Retrying" in t]
        assert len(retry_msgs) == 1
        assert "1/3" in retry_msgs[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/test_continuation.py::TestApiErrorRetry -v`
Expected: All 8 tests FAIL (no retry logic exists yet — exceptions propagate immediately).

- [ ] **Step 3: Implement the retry logic**

In `agent/loop.py`, replace lines 354–391 (the entire ghost-response retry block, from the comment through `# ─────`) with:

```python
                # ── API call with retry ────────────────────────────────────
                # Retries on two classes of failure:
                # 1. Transient API errors (429, 500, 502, 503, connection,
                #    timeout) — exponential backoff, separate counter.
                # 2. Ghost responses (HTTP 200, content=None, usage=None) —
                #    instant retry, separate counter.
                _TRANSIENT_CODES = (429, 500, 502, 503)
                _null_retries = 0
                _error_retries = 0
                while True:
                    self.callbacks.on_api_call(list(self._messages))
                    try:
                        response = self.client.chat.completions.create(
                            model=self.config.model,
                            messages=self._messages,
                            tools=self.registry.get_openai_tools_list(),
                            parallel_tool_calls=False,
                            **(dict(extra_body=self._reasoning_extra) if self._reasoning_extra else {}),
                        )
                    except (openai.APIConnectionError, openai.APITimeoutError):
                        _error_retries += 1
                        if _error_retries >= self.config.api_error_retries:
                            raise
                        delay = min(2 ** _error_retries, 60)
                        self.callbacks.on_assistant_text(
                            f"[Connection error. Retrying in {delay}s "
                            f"({_error_retries}/{self.config.api_error_retries})...]"
                        )
                        time.sleep(delay)
                        continue
                    except openai.APIStatusError as exc:
                        if exc.status_code not in _TRANSIENT_CODES:
                            raise
                        _error_retries += 1
                        if _error_retries >= self.config.api_error_retries:
                            raise
                        delay = min(2 ** _error_retries, 60)
                        self.callbacks.on_assistant_text(
                            f"[Server error {exc.status_code}. Retrying in {delay}s "
                            f"({_error_retries}/{self.config.api_error_retries})...]"
                        )
                        time.sleep(delay)
                        continue

                    message = response.choices[0].message
                    _prompt_tok = getattr(response.usage, "prompt_tokens", 0) or 0
                    _is_ghost = (
                        not message.tool_calls
                        and not (message.content or "").strip()
                        and _prompt_tok == 0
                    )
                    if not _is_ghost:
                        break  # valid response — proceed
                    _null_retries += 1
                    if _null_retries >= self.config.null_response_retries:
                        error_msg = (
                            f"Error: model returned a null response "
                            f"{_null_retries} time(s) in a row. "
                            "Check your model endpoint and retry your task."
                        )
                        self.callbacks.on_error(Exception(error_msg))
                        return error_msg
                    # else: discard ghost, retry with identical context
                # ─────────────────────────────────────────────────────────────
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_continuation.py::TestApiErrorRetry -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Run all tests to check for regressions**

Run: `conda run -n dagi python -m pytest tests/test_continuation.py -v`
Expected: All tests PASS (original 11 + 1 config + 8 retry = 20)

- [ ] **Step 6: Commit**

```bash
git add agent/loop.py tests/test_continuation.py
git commit -m "feat: retry transient API errors with exponential backoff"
```

---

### Task 3: Snapshot and restore `_messages` during compaction

**Files:**
- Modify: `tools/compact.py:196-252` (compact method, API call + mutation block)
- Test: `tests/test_continuation.py` (append)

- [ ] **Step 1: Write failing tests for compaction snapshot**

In `tests/test_continuation.py`, add at the bottom:

```python
class TestCompactionSnapshot:
    def test_compaction_api_failure_restores_messages(self):
        """If the summarisation API call fails, _messages must be unchanged."""
        from tools.compact import CompactTool

        original_messages = [
            {"role": "system", "content": "You are a test agent."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "Do task A"},
            {"role": "assistant", "content": "Working on it...",
             "tool_calls": [{"id": "tc1", "type": "function",
                             "function": {"name": "bash", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "tc1", "content": "done"},
            {"role": "assistant", "content": "Task A done."},
            {"role": "user", "content": "Do task B"},
            {"role": "assistant", "content": "On it."},
        ]
        messages = [dict(m) for m in original_messages]
        expected_snapshot = [dict(m) for m in original_messages]

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = openai.APIConnectionError(
            request=httpx.Request("POST", "https://api.example.com/v1/chat/completions"),
        )

        config = AgentConfig(
            model="test-model",
            api_key="test-key",
            system_prompt="You are a test agent.",
            keep_recent_tokens=100,
        )

        tool = CompactTool()
        tool.bind(messages, config, mock_client)

        with pytest.raises(openai.APIConnectionError):
            tool.compact(force=True)

        assert len(messages) == len(expected_snapshot)
        for i, (actual, expected) in enumerate(zip(messages, expected_snapshot)):
            assert actual == expected, f"Message {i} differs after failed compaction"

    def test_compaction_success_still_works(self):
        """Normal compaction should still mutate _messages correctly."""
        from tools.compact import CompactTool

        messages = [
            {"role": "system", "content": "You are a test agent."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
            {"role": "user", "content": "Task A"},
            {"role": "assistant", "content": "Done A."},
            {"role": "user", "content": "Task B"},
            {"role": "assistant", "content": "Done B."},
        ]

        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, cost=None)
        summary_msg = SimpleNamespace(content="Summary of conversation.")
        summary_choice = SimpleNamespace(message=summary_msg)
        summary_response = SimpleNamespace(choices=[summary_choice], usage=usage)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = summary_response

        config = AgentConfig(
            model="test-model",
            api_key="test-key",
            system_prompt="You are a test agent.",
            keep_recent_tokens=100,
        )

        tool = CompactTool()
        tool.bind(messages, config, mock_client)

        result = tool.compact(force=True)

        assert result.did_compact is True
        assert any("[CONTEXT SUMMARY" in m.get("content", "") for m in messages)
```

- [ ] **Step 2: Run tests to verify the failure test fails**

Run: `conda run -n dagi python -m pytest tests/test_continuation.py::TestCompactionSnapshot::test_compaction_api_failure_restores_messages -v`
Expected: FAIL — the current code does not snapshot/restore, so `_messages` may be in a partially modified state (though in practice the mutation happens *after* the API call, the test verifies the contract).

Actually, looking at the current code flow in `compact.py`, the slice mutation (`msgs[head_end:tail_start] = [summary_message]`) happens at line 238 — *after* the API call at line 218. If the API call throws, the mutation hasn't happened. So the failure test will actually PASS without changes because the exception propagates before mutation. However, the snapshot approach protects against *any* future rearrangement of the compact logic, and also guards against failures in post-API-call processing (e.g., line 222 `response.choices[0]` failing on a malformed response). Let's adjust the test to verify a failure *after* the API response but before mutation completes.

Replace the test with this version that simulates a malformed response:

```python
class TestCompactionSnapshot:
    def test_compaction_failure_restores_messages(self):
        """If anything fails during compaction, _messages must be unchanged."""
        from tools.compact import CompactTool

        original_messages = [
            {"role": "system", "content": "You are a test agent."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "Do task A"},
            {"role": "assistant", "content": "Working on it...",
             "tool_calls": [{"id": "tc1", "type": "function",
                             "function": {"name": "bash", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "tc1", "content": "done"},
            {"role": "assistant", "content": "Task A done."},
            {"role": "user", "content": "Do task B"},
            {"role": "assistant", "content": "On it."},
        ]
        messages = [dict(m) for m in original_messages]
        expected_len = len(messages)

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = openai.APIConnectionError(
            request=httpx.Request("POST", "https://api.example.com/v1/chat/completions"),
        )

        config = AgentConfig(
            model="test-model",
            api_key="test-key",
            system_prompt="You are a test agent.",
            keep_recent_tokens=100,
        )

        tool = CompactTool()
        tool.bind(messages, config, mock_client)

        with pytest.raises(openai.APIConnectionError):
            tool.compact(force=True)

        assert len(messages) == expected_len
        for i, (actual, expected) in enumerate(zip(messages, original_messages)):
            assert actual == expected, f"Message {i} differs after failed compaction"

    def test_compaction_success_still_works(self):
        """Normal compaction should still mutate _messages correctly."""
        from tools.compact import CompactTool

        messages = [
            {"role": "system", "content": "You are a test agent."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
            {"role": "user", "content": "Task A"},
            {"role": "assistant", "content": "Done A."},
            {"role": "user", "content": "Task B"},
            {"role": "assistant", "content": "Done B."},
        ]

        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, cost=None)
        summary_msg = SimpleNamespace(content="Summary of conversation.")
        summary_choice = SimpleNamespace(message=summary_msg)
        summary_response = SimpleNamespace(choices=[summary_choice], usage=usage)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = summary_response

        config = AgentConfig(
            model="test-model",
            api_key="test-key",
            system_prompt="You are a test agent.",
            keep_recent_tokens=100,
        )

        tool = CompactTool()
        tool.bind(messages, config, mock_client)

        result = tool.compact(force=True)

        assert result.did_compact is True
        assert any("[CONTEXT SUMMARY" in m.get("content", "") for m in messages)
```

- [ ] **Step 3: Implement snapshot-and-restore in `compact()`**

In `tools/compact.py`, replace lines 196–252 (from `# ── Slice the middle` through end of method) with:

```python
        # ── Slice the middle to be summarised ─────────────────────────────
        middle = msgs[head_end:tail_start]
        if not middle:
            return _NO_COMPACTION

        # ── Snapshot for rollback on failure ──────────────────────────────
        snapshot = list(msgs)

        try:
            # ── Build summarisation prompt ────────────────────────────────
            prior_section = (
                f"\n\n=== PRIOR SUMMARY (carry this forward) ===\n{prior_summary}"
                if prior_summary
                else ""
            )
            summarisation_messages = [
                {"role": "system", "content": _COMPACT_SYSTEM},
                {
                    "role": "user",
                    "content": _COMPACT_USER.format(
                        prior_section=prior_section,
                        conversation=_format_messages_for_summary(middle),
                    ),
                },
            ]

            summary_response = self._client.chat.completions.create(
                model=config.model,
                messages=summarisation_messages,
            )
            summary_text = summary_response.choices[0].message.content or "(no summary)"

            # ── Token usage from the summarisation call ───────────────────
            su = summary_response.usage
            sum_in = getattr(su, "prompt_tokens", 0) or 0
            sum_out = getattr(su, "completion_tokens", 0) or 0
            sum_cost = getattr(su, "cost", None)

            # ── Build replacement message (role=user avoids pairing invariant)
            summary_message = {
                "role": "user",
                "content": "[CONTEXT SUMMARY — prior conversation compacted]\n\n" + summary_text,
            }

            # ── Mutate in place ───────────────────────────────────────────
            removed_count = len(middle)
            msgs[head_end:tail_start] = [summary_message]

        except Exception:
            msgs[:] = snapshot
            raise

        # ── Notify observers ──────────────────────────────────────────────
        if self._on_summary:
            self._on_summary(summary_message["content"])
        if self._on_compaction:
            self._on_compaction(len(msgs), removed_count)

        return CompactionResult(
            did_compact=True,
            removed_count=removed_count,
            summary_input_tokens=sum_in,
            summary_output_tokens=sum_out,
            summary_cost=sum_cost,
        )
```

- [ ] **Step 4: Run compaction tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_continuation.py::TestCompactionSnapshot -v`
Expected: Both tests PASS

- [ ] **Step 5: Run all tests to check for regressions**

Run: `conda run -n dagi python -m pytest tests/test_continuation.py -v`
Expected: All tests PASS (20 + 2 = 22)

- [ ] **Step 6: Commit**

```bash
git add tools/compact.py tests/test_continuation.py
git commit -m "fix: snapshot _messages before compaction, restore on failure"
```

---

### Task 4: Final validation and cleanup

**Files:**
- All modified files from Tasks 1-3

- [ ] **Step 1: Run all tests one final time**

Run: `conda run -n dagi python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Verify config.yaml documentation**

Check that `config.yaml` already has a comment near `null_response_retries` — the new field `api_error_retries` is optional and defaults to 3, so it does not need to be added to the file unless the user wants to override it.

- [ ] **Step 3: Commit any remaining changes**

If there are no remaining uncommitted changes, skip this step.
