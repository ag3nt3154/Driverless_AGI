from __future__ import annotations

from agent.base_tool import BaseTool
from agent.protocol import SideEffect, ToolResult


class SwitchModelTool(BaseTool):
    name = "switch_model"
    description = (
        "Switch the active LLM to a different capability tier for the remainder of this task.\n\n"
        "Tiers:\n"
        "  - \"plan\"    — highest capability. Use when the next step requires deep reasoning, "
        "complex multi-file architecture decisions, or the current model is producing low-quality "
        "output on a hard sub-problem. Switch back to \"default\" when done.\n"
        "  - \"default\" — standard working tier. The normal model; restore here after any elevation.\n"
        "  - \"worker\"  — cheapest tier. Reserved for sub-agents; do NOT switch the main agent "
        "to worker.\n\n"
        "The tool registry and conversation history are NOT affected. Only the LLM changes.\n"
        "Always switch back to \"default\" when the difficult sub-problem is resolved."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "enum": ["plan", "default", "worker"],
                "description": "The tier to switch to.",
            },
            "reason": {
                "type": "string",
                "description": "One sentence explaining why you are switching tiers.",
            },
        },
        "required": ["target", "reason"],
    }

    def run(self, target: str, reason: str) -> ToolResult:  # noqa: ARG002
        return ToolResult(
            output=f"Switching to {target} tier.",
            side_effect=SideEffect.SWITCH_MODEL,
            side_effect_data={"tier": target},
        )
