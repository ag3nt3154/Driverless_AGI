// @vitest-environment node
import { describe, it, expect } from "vitest";
import { dagiReducer, initialState, AppState } from "../renderer/state";
import { PROTOCOL_VERSION } from "@shared/protocol";

const V = PROTOCOL_VERSION;

function ev(type: string, extras: object = {}) {
  return { version: V, type, ...extras } as any;
}

function runEvents(events: object[]): AppState {
  return events.reduce(
    (s, e) => dagiReducer(s, { type: "sidecar_event", event: e as any }),
    initialState
  );
}

describe("dagiReducer", () => {
  it("starts with initial state", () => {
    expect(initialState.status).toBe("idle");
    expect(initialState.turns).toHaveLength(0);
  });

  it("clear resets to initial state", () => {
    const s = runEvents([ev("turn_start", { turn: 1 })]);
    const cleared = dagiReducer(s, { type: "clear" });
    expect(cleared).toEqual(initialState);
  });

  it("set_status changes status and clears error", () => {
    const s = dagiReducer(
      { ...initialState, status: "error", error: "boom" },
      { type: "set_status", status: "idle" }
    );
    expect(s.status).toBe("idle");
    expect(s.error).toBeNull();
  });

  it("turn_start creates new turn and sets running", () => {
    const s = runEvents([ev("turn_start", { turn: 1 })]);
    expect(s.status).toBe("running");
    expect(s.turns).toHaveLength(1);
    expect(s.turns[0].index).toBe(1);
    expect(s.turns[0].text).toBe("");
    expect(s.turns[0].complete).toBe(false);
  });

  it("token appends text to last turn", () => {
    const s = runEvents([
      ev("turn_start", { turn: 1 }),
      ev("token", { text: "Hello" }),
      ev("token", { text: " world" }),
    ]);
    expect(s.turns[0].text).toBe("Hello world");
  });

  it("thinking appends to last turn thinking field", () => {
    const s = runEvents([
      ev("turn_start", { turn: 1 }),
      ev("thinking", { text: "Let me think" }),
    ]);
    expect(s.turns[0].thinking).toBe("Let me think");
  });

  it("tool_call appends to toolCalls list", () => {
    const s = runEvents([
      ev("turn_start", { turn: 1 }),
      ev("tool_call", { tool: "bash", input: { command: "ls" }, call_id: "c1" }),
    ]);
    expect(s.turns[0].toolCalls).toHaveLength(1);
    expect(s.turns[0].toolCalls[0].tool).toBe("bash");
    expect(s.turns[0].toolCalls[0].callId).toBe("c1");
  });

  it("tool_result updates matching toolCall", () => {
    const s = runEvents([
      ev("turn_start", { turn: 1 }),
      ev("tool_call", { tool: "bash", input: {}, call_id: "c1" }),
      ev("tool_result", { tool: "bash", content: "output", call_id: "c1" }),
    ]);
    expect(s.turns[0].toolCalls[0].result).toBe("output");
    expect(s.turns[0].toolCalls[0].isError).toBeUndefined();
  });

  it("tool_result with is_error=true marks error", () => {
    const s = runEvents([
      ev("turn_start", { turn: 1 }),
      ev("tool_call", { tool: "bash", input: {}, call_id: "c1" }),
      ev("tool_result", { tool: "bash", content: "fail", call_id: "c1", is_error: true }),
    ]);
    expect(s.turns[0].toolCalls[0].isError).toBe(true);
  });

  it("turn_end marks turn complete", () => {
    const s = runEvents([
      ev("turn_start", { turn: 1 }),
      ev("turn_end", { turn: 1 }),
    ]);
    expect(s.turns[0].complete).toBe(true);
  });

  it("task_complete sets status to idle", () => {
    const s = runEvents([
      ev("turn_start", { turn: 1 }),
      ev("task_complete", { result: "done" }),
    ]);
    expect(s.status).toBe("idle");
  });

  it("error sets status to error and stores message", () => {
    const s = runEvents([ev("error", { message: "something broke" })]);
    expect(s.status).toBe("error");
    expect(s.error).toBe("something broke");
  });

  it("question sets status to paused and stores question", () => {
    const s = runEvents([
      ev("turn_start", { turn: 1 }),
      ev("question", { question_id: "q1", text: "Continue?", options: ["yes", "no"] }),
    ]);
    expect(s.status).toBe("paused");
    expect(s.question?.questionId).toBe("q1");
    expect(s.question?.options).toEqual(["yes", "no"]);
  });

  it("cost_update stores total and token count", () => {
    const s = runEvents([ev("cost_update", { total_usd: 0.042, session_tokens: 1000 })]);
    expect(s.totalCostUsd).toBeCloseTo(0.042);
    expect(s.sessionTokens).toBe(1000);
  });

  it("plan_update stores plan content", () => {
    const s = runEvents([ev("plan_update", { content: "# Plan\n- step 1" })]);
    expect(s.planContent).toBe("# Plan\n- step 1");
  });

  it("compact clears turns", () => {
    const s = runEvents([
      ev("turn_start", { turn: 1 }),
      ev("compact", { summary: "compressed" }),
    ]);
    expect(s.turns).toHaveLength(0);
  });

  it("multiple turns accumulate", () => {
    const s = runEvents([
      ev("turn_start", { turn: 1 }),
      ev("token", { text: "first" }),
      ev("turn_end", { turn: 1 }),
      ev("turn_start", { turn: 2 }),
      ev("token", { text: "second" }),
      ev("turn_end", { turn: 2 }),
    ]);
    expect(s.turns).toHaveLength(2);
    expect(s.turns[0].text).toBe("first");
    expect(s.turns[1].text).toBe("second");
  });

  it("no-op events leave state unchanged", () => {
    const s = runEvents([
      ev("ready"),
      ev("ack", { request_id: "1", result: {} }),
      ev("shutdown_complete"),
    ]);
    expect(s).toEqual(initialState);
  });

  it("token without a turn is a no-op", () => {
    const s = runEvents([ev("token", { text: "orphan" })]);
    expect(s.turns).toHaveLength(0);
  });
});
