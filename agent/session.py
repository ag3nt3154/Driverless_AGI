from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ToolCallRecord:
    name: str
    description: str
    input: str   # raw JSON arguments string
    result: str  # tool output; lists encoded as "__list__:<json>"


@dataclass
class MessageNode:
    id: str
    seq: int
    entity: str                          # "system" | "user" | "assistant"
    content: str | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    cost: float | None
    tool_calls: list[ToolCallRecord]
    timestamp: str


class SessionTracker:
    def __init__(
        self,
        model: str,
        logs_dir: str | Path = ".dagi/logs",
        thread_id: str | None = None,
    ) -> None:
        self._model = model
        self._thread_id = thread_id or uuid4().hex
        self._logs_dir = Path(logs_dir)
        self._messages: list[MessageNode] = []
        self._seq = 0
        self._started_at = datetime.now(timezone.utc)

        self._logs_dir.mkdir(parents=True, exist_ok=True)
        ts = self._started_at.strftime("%Y-%m-%d_%H-%M-%S")
        self._path = self._logs_dir / f"session_{ts}.jsonl"

        self._write({
            "type": "session_start",
            "thread_id": self._thread_id,
            "model": self._model,
            "started_at": self._started_at.isoformat(),
        })

    @property
    def thread_id(self) -> str:
        return self._thread_id

    # ------------------------------------------------------------------ events

    def record_system(self, content: str) -> None:
        node = self._add(entity="system", content=content)
        self._write({"type": "message", **asdict(node)})

    def record_user(self, content: str) -> None:
        node = self._add(entity="user", content=content)
        self._write({"type": "message", **asdict(node)})

    def record_assistant(
        self,
        content: str | None,
        usage,
        tool_calls: list[ToolCallRecord],
    ) -> None:
        input_tokens = getattr(usage, "prompt_tokens", None) if usage else None
        output_tokens = getattr(usage, "completion_tokens", None) if usage else None
        cost = getattr(usage, "cost", None) if usage else None
        node = self._add(
            entity="assistant",
            content=content,
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            tool_calls=tool_calls,
        )
        self._write({"type": "message", **asdict(node)})

    def record_tool_start(self, name: str, description: str, input_str: str) -> None:
        self._write({
            "type": "tool_start",
            "name": name,
            "description": description,
            "input": input_str,
            "timestamp": _now(),
        })

    def record_tool_end(self, name: str, result_str: str) -> None:
        self._write({
            "type": "tool_end",
            "name": name,
            "result": result_str,
            "timestamp": _now(),
        })

    def finish(self, raw_messages: list | None = None) -> None:
        finished_at = datetime.now(timezone.utc)

        assistant_nodes = [m for m in self._messages if m.entity == "assistant"]
        total_in = sum(n.input_tokens for n in assistant_nodes if n.input_tokens is not None)
        total_out = sum(n.output_tokens for n in assistant_nodes if n.output_tokens is not None)
        costs = [n.cost for n in assistant_nodes if n.cost is not None]
        total_cost = sum(costs) if costs else None

        tool_call_counts: dict[str, int] = {}
        for node in assistant_nodes:
            for tc in node.tool_calls:
                tool_call_counts[tc.name] = tool_call_counts.get(tc.name, 0) + 1

        record: dict = {
            "type": "session_end",
            "finished_at": finished_at.isoformat(),
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "total_cost": total_cost,
            "tool_call_counts": tool_call_counts,
        }
        if raw_messages is not None:
            record["raw_messages"] = raw_messages
        self._write(record)

        # stderr summary
        cost_str = f"  cost=${total_cost:.5f}" if total_cost is not None else ""
        tools_str = ""
        if tool_call_counts:
            tools_str = "  tools: " + " ".join(
                f"{name}\u00d7{count}" for name, count in tool_call_counts.items()
            )
        print(f"[dagi] session saved \u2192 {self._path}", file=sys.stderr)

    # ---------------------------------------------------------------- internal

    def _write(self, record: dict) -> None:
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _add(
        self,
        entity: str,
        content: str | None = None,
        model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost: float | None = None,
        tool_calls: list[ToolCallRecord] | None = None,
    ) -> MessageNode:
        node = MessageNode(
            id=uuid4().hex,
            seq=self._seq,
            entity=entity,
            content=content,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            tool_calls=tool_calls or [],
            timestamp=_now(),
        )
        self._messages.append(node)
        self._seq += 1
        return node
