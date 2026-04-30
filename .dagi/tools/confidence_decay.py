"""
confidence_decay — applies the Ebbinghaus forgetting-curve decay to a wiki node
confidence score.

Formula: max(0.2, old_score * exp(-decay_rate * days_elapsed))
  - Hard floor of 0.2: confidence never falls below this regardless of age.
  - decay_rate 0.005 ≈ half-life of 139 days.

Call this during memory-lint for every node that has a confidence field.
"""
from __future__ import annotations

import json
import math
from datetime import date

from agent.base_tool import BaseTool


class ConfidenceDecayTool(BaseTool):
    name = "confidence_decay"
    description = (
        "Applies forgetting-curve decay to a wiki node confidence score. "
        "Pass the current score, the date the confidence was last updated "
        "(confidence_last_updated), the current date, and a decay rate. "
        "Returns the decayed score clamped to [0.2, 1.0] — hard floor is 0.2. "
        "Default decay_rate is 0.005 (half-life ~139 days). "
        "Nodes with a returned score <= 0.3 should be flagged for review."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "old_score": {
                "type": "number",
                "description": "Current confidence score, float in [0.2, 1.0].",
            },
            "date_added": {
                "type": "string",
                "description": (
                    "ISO date string (YYYY-MM-DD) of confidence_last_updated "
                    "frontmatter field. Fall back to date_added if that field is absent."
                ),
            },
            "current_date": {
                "type": "string",
                "description": "ISO date string (YYYY-MM-DD) for today.",
            },
            "decay_rate": {
                "type": "number",
                "description": (
                    "Exponential decay rate constant. Default 0.005. "
                    "Higher = faster decay. At 0.005, score halves in ~139 days."
                ),
            },
        },
        "required": ["old_score", "date_added", "current_date", "decay_rate"],
    }

    FLOOR = 0.2

    def run(
        self,
        old_score: float,
        date_added: str,
        current_date: str,
        decay_rate: float = 0.005,
    ) -> str:
        d_added = date.fromisoformat(date_added)
        d_current = date.fromisoformat(current_date)
        days_elapsed = max(0, (d_current - d_added).days)
        decayed = old_score * math.exp(-decay_rate * days_elapsed)
        decayed = max(self.FLOOR, min(1.0, decayed))
        return json.dumps({
            "old_score": old_score,
            "decayed_score": round(decayed, 4),
            "days_elapsed": days_elapsed,
            "decay_rate": decay_rate,
            "at_floor": decayed == self.FLOOR,
        })
