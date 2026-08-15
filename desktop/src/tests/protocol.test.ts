import { describe, it, expect } from "vitest";
import {
  AnyCommand,
  AnyEvent,
  PROTOCOL_VERSION,
  makeCommandId,
  serializeCommand,
  parseEvent,
} from "@shared/protocol";

// ── AnyCommand validation ─────────────────────────────────────────────────────

describe("AnyCommand", () => {
  it("parses a valid run command", () => {
    const cmd = AnyCommand.parse({
      version: PROTOCOL_VERSION,
      id: "1",
      type: "run",
      task: "hello",
    });
    expect(cmd.type).toBe("run");
    if (cmd.type === "run") expect(cmd.task).toBe("hello");
  });

  it("rejects unknown type", () => {
    expect(() =>
      AnyCommand.parse({ version: PROTOCOL_VERSION, id: "1", type: "bogus" })
    ).toThrow();
  });

  it("rejects wrong version", () => {
    expect(() =>
      AnyCommand.parse({ version: 99, id: "1", type: "run", task: "" })
    ).toThrow();
  });

  it("parses cancel command", () => {
    const cmd = AnyCommand.parse({ version: PROTOCOL_VERSION, id: "c1", type: "cancel" });
    expect(cmd.type).toBe("cancel");
  });

  it("parses pause command", () => {
    const cmd = AnyCommand.parse({ version: PROTOCOL_VERSION, id: "p1", type: "pause" });
    expect(cmd.type).toBe("pause");
  });

  it("resume defaults message to empty string", () => {
    const cmd = AnyCommand.parse({ version: PROTOCOL_VERSION, id: "r1", type: "resume" });
    if (cmd.type === "resume") expect(cmd.message).toBe("");
  });

  it("parses set_model command", () => {
    const cmd = AnyCommand.parse({
      version: PROTOCOL_VERSION,
      id: "m1",
      type: "set_model",
      model_id: "claude-opus-4-6",
    });
    expect(cmd.type).toBe("set_model");
    if (cmd.type === "set_model") expect(cmd.model_id).toBe("claude-opus-4-6");
  });

  it("rejects empty id", () => {
    expect(() =>
      AnyCommand.parse({ version: PROTOCOL_VERSION, id: "", type: "run", task: "" })
    ).toThrow();
  });
});

// ── AnyEvent validation ───────────────────────────────────────────────────────

describe("AnyEvent", () => {
  it("parses ready event", () => {
    const evt = AnyEvent.parse({ version: PROTOCOL_VERSION, type: "ready" });
    expect(evt.type).toBe("ready");
  });

  it("parses ack event", () => {
    const evt = AnyEvent.parse({
      version: PROTOCOL_VERSION,
      type: "ack",
      request_id: "1",
      result: { ok: true },
    });
    expect(evt.type).toBe("ack");
    if (evt.type === "ack") expect(evt.request_id).toBe("1");
  });

  it("parses token event", () => {
    const evt = AnyEvent.parse({ version: PROTOCOL_VERSION, type: "token", text: "hello" });
    if (evt.type === "token") expect(evt.text).toBe("hello");
  });

  it("parses tool_call event", () => {
    const evt = AnyEvent.parse({
      version: PROTOCOL_VERSION,
      type: "tool_call",
      tool: "bash",
      input: { command: "ls" },
    });
    if (evt.type === "tool_call") expect(evt.tool).toBe("bash");
  });

  it("parses question event", () => {
    const evt = AnyEvent.parse({
      version: PROTOCOL_VERSION,
      type: "question",
      question_id: "q1",
      text: "Continue?",
      options: ["yes", "no"],
    });
    if (evt.type === "question") {
      expect(evt.question_id).toBe("q1");
      expect(evt.options).toEqual(["yes", "no"]);
    }
  });

  it("rejects unknown event type", () => {
    expect(() =>
      AnyEvent.parse({ version: PROTOCOL_VERSION, type: "unknown_event" })
    ).toThrow();
  });
});

// ── Helpers ───────────────────────────────────────────────────────────────────

describe("makeCommandId", () => {
  it("returns unique ids", () => {
    const ids = Array.from({ length: 10 }, () => makeCommandId());
    const unique = new Set(ids);
    expect(unique.size).toBe(10);
  });
});

describe("serializeCommand", () => {
  it("produces valid JSON with version and id", () => {
    const line = serializeCommand("run", { task: "test" });
    const obj = JSON.parse(line);
    expect(obj.version).toBe(PROTOCOL_VERSION);
    expect(typeof obj.id).toBe("string");
    expect(obj.type).toBe("run");
    expect(obj.task).toBe("test");
  });

  it("is a single line (no newline)", () => {
    const line = serializeCommand("cancel");
    expect(line).not.toContain("\n");
  });
});

describe("parseEvent", () => {
  it("returns parsed event for valid line", () => {
    const line = JSON.stringify({ version: PROTOCOL_VERSION, type: "ready" });
    expect(parseEvent(line)?.type).toBe("ready");
  });

  it("returns null for invalid JSON", () => {
    expect(parseEvent("not json")).toBeNull();
  });

  it("returns null for unknown event type", () => {
    const line = JSON.stringify({ version: PROTOCOL_VERSION, type: "bogus" });
    expect(parseEvent(line)).toBeNull();
  });

  it("returns null for wrong version", () => {
    const line = JSON.stringify({ version: 99, type: "ready" });
    expect(parseEvent(line)).toBeNull();
  });
});
