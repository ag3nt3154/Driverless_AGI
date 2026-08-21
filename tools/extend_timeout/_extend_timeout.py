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
        from tools._handoff_format import (
            dispatch_status_result,
            format_handoff_result,
        )
        from tools.subagent_api import resume_subagent_by_pid

        result = resume_subagent_by_pid(pid, float(extra_seconds))
        if result.is_ok:
            unverified = result.status == "ok_unverified"
            return format_handoff_result(
                str(result.handoff_path), unverified=unverified,
            )
        return dispatch_status_result(
            {"status": result.status, "pid": result.pid,
             "message": ""},
            "subagent",
        )
