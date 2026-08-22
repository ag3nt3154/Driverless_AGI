/**
 * Pure renderer state — no side effects, fully testable.
 *
 * The reducer maps incoming SidecarEvents to state mutations.
 * All mutable state lives here; components are purely presentational.
 */

import type { SidecarEvent, ToolCallEventType, ToolResultEventType } from "@shared/protocol";

// ── Domain types ──────────────────────────────────────────────────────────────

export type AgentStatus = "idle" | "running" | "paused" | "error";

export interface ToolCall {
  callId: string;
  tool: string;
  input: Record<string, unknown>;
  result?: string;
  isError?: boolean;
  /** ISO timestamp of the call */
  startedAt: string;
}

export interface Turn {
  index: number;
  text: string;
  thinking: string;
  toolCalls: ToolCall[];
  /** True once turn_end received */
  complete: boolean;
}

export interface QuestionPrompt {
  questionId: string;
  text: string;
  options?: string[];
}

export interface AppState {
  status: AgentStatus;
  turns: Turn[];
  /** Pending user question from ask_user tool */
  question: QuestionPrompt | null;
  totalCostUsd: number;
  sessionTokens: number;
  /** Plan markdown content */
  planContent: string;
  error: string | null;
}

// ── Actions ───────────────────────────────────────────────────────────────────

export type Action =
  | { type: "sidecar_event"; event: SidecarEvent }
  | { type: "clear" }
  | { type: "set_status"; status: AgentStatus };

// ── Initial state ─────────────────────────────────────────────────────────────

export const initialState: AppState = {
  status: "idle",
  turns: [],
  question: null,
  totalCostUsd: 0,
  sessionTokens: 0,
  planContent: "",
  error: null,
};

// ── Reducer ───────────────────────────────────────────────────────────────────

export function dagiReducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case "clear":
      return { ...initialState };

    case "set_status":
      return { ...state, status: action.status, error: null };

    case "sidecar_event":
      return applyEvent(state, action.event);

    default:
      return state;
  }
}

function applyEvent(state: AppState, evt: SidecarEvent): AppState {
  switch (evt.type) {
    case "turn_start":
      return {
        ...state,
        status: "running",
        error: null,
        turns: [
          ...state.turns,
          {
            index: evt.turn,
            text: "",
            thinking: "",
            toolCalls: [],
            complete: false,
          },
        ],
      };

    case "token": {
      if (state.turns.length === 0) return state;
      const turns = [...state.turns];
      const last = { ...turns[turns.length - 1] };
      last.text += evt.text;
      turns[turns.length - 1] = last;
      return { ...state, turns };
    }

    case "thinking": {
      if (state.turns.length === 0) return state;
      const turns = [...state.turns];
      const last = { ...turns[turns.length - 1] };
      last.thinking += evt.text;
      turns[turns.length - 1] = last;
      return { ...state, turns };
    }

    case "tool_call": {
      if (state.turns.length === 0) return state;
      const turns = [...state.turns];
      const last = { ...turns[turns.length - 1] };
      const tc: ToolCall = {
        callId: evt.call_id ?? `${evt.tool}-${Date.now()}`,
        tool: evt.tool,
        input: evt.input,
        startedAt: new Date().toISOString(),
      };
      last.toolCalls = [...last.toolCalls, tc];
      turns[turns.length - 1] = last;
      return { ...state, turns };
    }

    case "tool_result": {
      if (state.turns.length === 0) return state;
      const turns = [...state.turns];
      const last = { ...turns[turns.length - 1] };
      const callId = evt.call_id;
      last.toolCalls = last.toolCalls.map((tc) => {
        if (!callId || tc.callId === callId) {
          return { ...tc, result: evt.content, isError: evt.is_error };
        }
        return tc;
      });
      turns[turns.length - 1] = last;
      return { ...state, turns };
    }

    case "turn_end": {
      if (state.turns.length === 0) return state;
      const turns = [...state.turns];
      const last = { ...turns[turns.length - 1], complete: true };
      turns[turns.length - 1] = last;
      return { ...state, turns };
    }

    case "task_complete":
      return { ...state, status: "idle" };

    case "error":
      return { ...state, status: "error", error: evt.message };

    case "question":
      return {
        ...state,
        status: "paused",
        question: {
          questionId: evt.question_id,
          text: evt.text,
          options: evt.options,
        },
      };

    case "cost_update":
      return {
        ...state,
        totalCostUsd: evt.total_usd,
        sessionTokens: evt.session_tokens ?? state.sessionTokens,
      };

    case "plan_update":
      return { ...state, planContent: evt.content };

    case "compact":
      return { ...state, turns: [] };

    case "status":
      return {
        ...state,
        status: (evt.status === "running" || evt.status === "paused"
          ? evt.status
          : "idle") as AgentStatus,
      };

    case "session_cleared":
      return { ...initialState };

    // Protocol/lifecycle events — no state change needed
    case "ready":
    case "ack":
    case "command_error":
    case "shutdown_complete":
    case "subagent":
      return state;

    default:
      return state;
  }
}
