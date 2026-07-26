"""tools/extend_timeout.py — Resume waiting for a timed-out subagent."""
from __future__ import annotations

from agent.base_tool import BaseTool


class ExtendSubagentTimeoutTool(BaseTool):
    """Resume polling a subagent process that previously timed out."""

    name = "extend_subagent_timeout"
    description = (
        "Resume waiting for a subagent that returned a timeout status. "
        "Pass the pid from the timeout result and how many extra seconds to wait."
    )

    _parameters = {
        "type": "object",
        "properties": {
            "pid": {
                "type": "integer",
                "description": "Process ID from the timeout result.",
            },
            "extra_seconds": {
                "type": "integer",
                "description": "Additional seconds to wait (default 120).",
                "default": 120,
            },
        },
        "required": ["pid"],
    }

    def run(self, pid: int, extra_seconds: int = 120) -> str:
        from tools._handoff_format import dispatch_status_result
        from tools._subagent_runner import resume_subagent

        result = resume_subagent(pid, float(extra_seconds))
        return dispatch_status_result(result, "subagent")
