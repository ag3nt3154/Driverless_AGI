"""
datetime_now — returns the current UTC and local datetime.
Useful for time-based filtering of session logs or any task requiring the
current time (e.g. computing "last hour" cutoffs).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from agent.base_tool import BaseTool


class DatetimeNowTool(BaseTool):
    name = "datetime_now"
    description = (
        "Returns the current UTC datetime, local datetime, and Unix timestamp. "
        "Use whenever you need to know the current time — e.g. to compute a "
        "'last hour' cutoff for filtering session logs by started_at."
    )
    _parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def run(self) -> str:
        now_utc = datetime.now(timezone.utc)
        now_local = datetime.now().astimezone()
        return json.dumps({
            "utc": now_utc.isoformat(),
            "local": now_local.isoformat(),
            "unix_timestamp": now_utc.timestamp(),
        })
