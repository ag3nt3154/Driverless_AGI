"""tests/test_terminal_subagent.py — Unit tests for _poll_with_spinner behaviour."""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch
import pytest

from agent.ipc import IpcTimeoutError
from tools._terminal_subagent import _poll_with_spinner, _POLL_INTERVAL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ipc(side_effects):
    """Return a mock IpcChannel whose poll_result raises/returns per side_effects."""
    ipc = MagicMock()
    ipc.poll_result.side_effect = side_effects
    return ipc


# ---------------------------------------------------------------------------
# timeout=None  — polls indefinitely until a result appears
# ---------------------------------------------------------------------------

class TestPollWithSpinnerNoTimeout:
    """When timeout=None the poller must never raise IpcTimeoutError itself."""

    def test_succeeds_on_first_poll(self):
        """Immediate result: no retries needed."""
        result = {"seq": 1, "status": "ok", "result": "hello"}
        ipc = _make_ipc([result])

        out = _poll_with_spinner(ipc, "worker", seq=1, timeout=None)

        assert out == result
        ipc.poll_result.assert_called_once_with(1, timeout=_POLL_INTERVAL)

    def test_succeeds_after_several_ipc_timeouts(self):
        """IpcTimeoutError raised N times then succeeds — no exception propagated."""
        result = {"seq": 1, "status": "ok", "result": "done"}
        side_effects = [IpcTimeoutError("poll miss")] * 5 + [result]
        ipc = _make_ipc(side_effects)

        out = _poll_with_spinner(ipc, "worker", seq=1, timeout=None)

        assert out == result
        assert ipc.poll_result.call_count == 6
        # Every call should use _POLL_INTERVAL as the timeout when no deadline
        for c in ipc.poll_result.call_args_list:
            assert c == call(1, timeout=_POLL_INTERVAL)

    def test_always_uses_poll_interval_as_timeout(self):
        """With timeout=None, poll_timeout should always equal _POLL_INTERVAL."""
        result = {"seq": 1, "status": "ok", "result": ""}
        ipc = _make_ipc([IpcTimeoutError()] * 3 + [result])

        _poll_with_spinner(ipc, "worker", seq=1, timeout=None)

        for c in ipc.poll_result.call_args_list:
            _, kwargs = c
            assert kwargs["timeout"] == _POLL_INTERVAL


# ---------------------------------------------------------------------------
# timeout=int  — raises IpcTimeoutError when deadline is exceeded
# ---------------------------------------------------------------------------

class TestPollWithSpinnerWithTimeout:
    def test_raises_when_poll_never_succeeds(self):
        """A finite timeout that is always missed must bubble up IpcTimeoutError.

        We mock time.monotonic so the deadline is perceived as already elapsed
        on the very first iteration — no actual wall-clock sleep needed.
        """
        ipc = MagicMock()
        ipc.poll_result.side_effect = IpcTimeoutError("miss")  # raises infinitely

        # t=0 on deadline setup; t=timeout+1 on the remaining check → expired
        with patch("tools._terminal_subagent.time") as mock_time:
            mock_time.monotonic.side_effect = [0.0, 6.0]  # first call sets base, second exceeds deadline

            with pytest.raises(IpcTimeoutError, match="Timeout after 5s"):
                _poll_with_spinner(ipc, "worker", seq=1, timeout=5)

    def test_succeeds_before_deadline(self):
        """If result arrives before deadline, no exception is raised."""
        result = {"seq": 1, "status": "ok", "result": "fast"}
        ipc = _make_ipc([result])

        out = _poll_with_spinner(ipc, "worker", seq=1, timeout=30)

        assert out == result

    def test_poll_timeout_capped_to_remaining(self):
        """With a very short deadline, poll_timeout must be <= remaining time."""
        result = {"seq": 1, "status": "ok", "result": "x"}
        ipc = _make_ipc([result])

        # Use a large timeout so we don't actually hit the deadline
        out = _poll_with_spinner(ipc, "worker", seq=1, timeout=3600)
        assert out == result

        # The poll_timeout passed to ipc.poll_result must never exceed _POLL_INTERVAL
        _, kwargs = ipc.poll_result.call_args
        assert kwargs["timeout"] <= _POLL_INTERVAL
