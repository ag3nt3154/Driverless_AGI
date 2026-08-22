from __future__ import annotations

from agent.affect import AffectController, AffectVector
from agent.base_tool import BaseTool


class AdjustAffectTool(BaseTool):
    name = "adjust_affect"
    description = (
        "Adjust the current affect vector by relative valence, arousal, and dominance deltas. "
        "All three deltas are required and must be between -1 and 1."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "valence_delta": {
                "type": "number",
                "minimum": -1,
                "maximum": 1,
                "description": "Relative change to valence. Use 0 to keep it unchanged.",
            },
            "arousal_delta": {
                "type": "number",
                "minimum": -1,
                "maximum": 1,
                "description": "Relative change to arousal. Use 0 to keep it unchanged.",
            },
            "dominance_delta": {
                "type": "number",
                "minimum": -1,
                "maximum": 1,
                "description": "Relative change to dominance. Use 0 to keep it unchanged.",
            },
        },
        "required": ["valence_delta", "arousal_delta", "dominance_delta"],
    }

    def __init__(self, controller: AffectController) -> None:
        self._controller = controller

    def run(
        self,
        valence_delta: float,
        arousal_delta: float,
        dominance_delta: float,
    ) -> str:
        before = self._controller.current.as_tuple()
        delta = AffectVector(valence_delta, arousal_delta, dominance_delta)
        snapshot = self._controller.adjust(delta)
        return (
            f"Prior: {before}\n"
            f"Requested delta: {delta.as_tuple()}\n"
            f"Result: {snapshot.current.as_tuple()}\n"
            f"Selected ID: {snapshot.emote_id}"
        )
