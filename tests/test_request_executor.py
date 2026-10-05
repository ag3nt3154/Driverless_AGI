"""tests/test_request_executor.py — RequestExecutor retry policy, without an AgentLoop."""
from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import openai
import pytest

from agent._request_executor import RequestExecutor, RequestOutcome

_REQ = httpx.Request("POST", "https://api.example.com/v1/chat/completions")


def _status_error(code: int):
    return openai.APIStatusError(
        message="err", response=httpx.Response(code, request=_REQ), body=None
    )


def _response(content="hi", prompt_tokens=10, tool_calls=None):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg)],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens),
    )


def _ghost():
    return _response(content=None, prompt_tokens=0)


def _executor(side_effect, *, supports_pause=False, abort=None, error_retries=3, null_retries=3):
    callbacks = MagicMock()
    callbacks.supports_pause = supports_pause
    executor = RequestExecutor(
        send=MagicMock(side_effect=side_effect),
        abort=abort or threading.Event(),
        callbacks=callbacks,
        pause=MagicMock(),
        api_error_retries=error_retries,
        null_response_retries=null_retries,
        on_attempt=MagicMock(),
    )
    return executor


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch("agent._request_executor.time.sleep") as sleep:
        yield sleep


class TestResponse:
    def test_first_valid_response_is_returned(self):
        resp = _response()
        ex = _executor([resp])
        result = ex.execute()
        assert result.outcome is RequestOutcome.RESPONSE
        assert result.response is resp
        ex.on_attempt.assert_called_once()

    def test_tool_call_only_response_is_not_a_ghost(self):
        resp = _response(content=None, prompt_tokens=0, tool_calls=[object()])
        assert _executor([resp]).execute().response is resp

    def test_transient_errors_then_success(self, _no_sleep):
        resp = _response()
        ex = _executor([openai.APIConnectionError(request=_REQ), _status_error(503), resp])
        result = ex.execute()
        assert result.outcome is RequestOutcome.RESPONSE
        assert [c.args[0] for c in _no_sleep.call_args_list] == [2, 4]  # shared counter
        assert ex.on_attempt.call_count == 3

    def test_ghosts_then_success(self, _no_sleep):
        resp = _response()
        result = _executor([_ghost(), _ghost(), resp]).execute()
        assert result.outcome is RequestOutcome.RESPONSE
        assert result.response is resp
        _no_sleep.assert_not_called()  # ghost retries are instant


class TestErrors:
    def test_non_transient_status_propagates_immediately(self):
        ex = _executor([_status_error(400)])
        with pytest.raises(openai.APIStatusError):
            ex.execute()
        assert ex.send.call_count == 1

    def test_exhausted_without_pause_support_raises_last_error(self):
        ex = _executor([_status_error(500)] * 2, error_retries=2)
        with pytest.raises(openai.APIStatusError):
            ex.execute()
        ex.pause.assert_not_called()

    def test_exhausted_with_pause_support_pauses(self):
        ex = _executor([httpx.ReadTimeout("t")] * 2, supports_pause=True, error_retries=2)
        result = ex.execute()
        assert result.outcome is RequestOutcome.PAUSED
        ex.pause.assert_called_once()
        ex.callbacks.on_pause.assert_called_once()
        texts = [c.args[0] for c in ex.callbacks.on_assistant_text.call_args_list]
        assert texts[-1].startswith("[Connection error — all 2 retries failed.")

    def test_backoff_caps_at_60s(self, _no_sleep):
        ex = _executor([_status_error(429)] * 7 + [_response()], error_retries=10)
        ex.execute()
        assert [c.args[0] for c in _no_sleep.call_args_list] == [2, 4, 8, 16, 32, 60, 60]


class TestNullExhausted:
    def test_ghost_limit_reports_count(self):
        result = _executor([_ghost()] * 3, null_retries=3).execute()
        assert result.outcome is RequestOutcome.NULL_EXHAUSTED
        assert result.null_retries == 3


class TestAborted:
    def test_abort_before_first_attempt_sends_nothing(self):
        abort = threading.Event()
        abort.set()
        ex = _executor([], abort=abort)
        result = ex.execute()
        assert result.outcome is RequestOutcome.ABORTED
        assert result.response is None
        ex.send.assert_not_called()

    def test_abort_during_send_keeps_partial_response(self):
        abort = threading.Event()
        partial = _ghost()  # would otherwise be retried as a ghost

        def send():
            abort.set()
            return partial

        ex = _executor(None, abort=abort)
        ex.send = send
        result = ex.execute()
        assert result.outcome is RequestOutcome.ABORTED
        assert result.response is partial

    def test_abort_during_backoff_stops_retrying(self, _no_sleep):
        abort = threading.Event()
        _no_sleep.side_effect = lambda _s: abort.set()
        ex = _executor([_status_error(502), _response()], abort=abort)
        result = ex.execute()
        assert result.outcome is RequestOutcome.ABORTED
        assert ex.send.call_count == 1
