// @vitest-environment node
/**
 * Tests for PythonSupervisor using an injectable FakeProc instead of mocking
 * child_process.spawn, which keeps the tests simple and fast.
 */

import { describe, it, expect, vi } from "vitest";
import { PassThrough } from "stream";
import { EventEmitter } from "events";
import { PROTOCOL_VERSION } from "@shared/protocol";
import { PythonSupervisor } from "../main/python-supervisor";

// ── Fake ChildProcess ─────────────────────────────────────────────────────────

class FakeProc extends EventEmitter {
  stdin: PassThrough;
  stdout: PassThrough;
  stderr: PassThrough;
  killed = false;

  constructor() {
    super();
    this.stdin = new PassThrough();
    this.stdout = new PassThrough();
    this.stderr = new PassThrough();
  }

  kill(signal?: string): boolean {
    this.killed = true;
    setImmediate(() => this.emit("close", signal === "SIGKILL" ? 137 : 0));
    return true;
  }

  emit_event(obj: object): void {
    this.stdout.push(JSON.stringify(obj) + "\n");
  }

  exit(code = 0): void {
    this.stdout.push(null);
    setImmediate(() => this.emit("close", code));
  }
}

// ── Helper ────────────────────────────────────────────────────────────────────

function makeSupervisor(opts: { maxRestarts?: number; baseBackoffMs?: number } = {}) {
  const fakeProc = new FakeProc();
  const spawnFn = vi.fn().mockReturnValue(fakeProc);

  const sup = new PythonSupervisor({
    pythonPath: "/fake/python",
    cwd: "/fake/cwd",
    maxRestarts: opts.maxRestarts ?? 0,
    baseBackoffMs: opts.baseBackoffMs ?? 50,
    spawnFn: spawnFn as any,
  });

  return { sup, fakeProc, spawnFn };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("PythonSupervisor", () => {
  it("resolves start() when ready event is received", async () => {
    const { sup, fakeProc } = makeSupervisor();
    const startP = sup.start();
    fakeProc.emit_event({ version: PROTOCOL_VERSION, type: "ready" });
    await expect(startP).resolves.toBeUndefined();
    expect(sup.isReady).toBe(true);
  });

  it("request() sends NDJSON line and resolves on ack", async () => {
    const { sup, fakeProc } = makeSupervisor();
    const startP = sup.start();
    fakeProc.emit_event({ version: PROTOCOL_VERSION, type: "ready" });
    await startP;

    let sentLine = "";
    fakeProc.stdin.on("data", (chunk: Buffer) => {
      sentLine = chunk.toString();
      const parsed = JSON.parse(sentLine.trim());
      fakeProc.emit_event({
        version: PROTOCOL_VERSION,
        type: "ack",
        request_id: parsed.id,
        result: { ok: true },
      });
    });

    const result = await sup.request("run", { task: "hello" });
    expect(result).toEqual({ ok: true });
    expect(JSON.parse(sentLine.trim())).toMatchObject({ type: "run", task: "hello" });
  });

  it("request() rejects when process crashes before ack", async () => {
    const { sup, fakeProc } = makeSupervisor();
    const startP = sup.start();
    fakeProc.emit_event({ version: PROTOCOL_VERSION, type: "ready" });
    await startP;

    const reqP = sup.request("run", { task: "hello" });
    fakeProc.exit(1);
    await expect(reqP).rejects.toThrow(/exited/);
  });

  it("subscribe() receives matching events and stops after unsubscribe", async () => {
    const { sup, fakeProc } = makeSupervisor();
    const startP = sup.start();
    fakeProc.emit_event({ version: PROTOCOL_VERSION, type: "ready" });
    await startP;

    const tokens: string[] = [];
    const unsub = sup.subscribe("token", (evt) => {
      if (evt.type === "token") tokens.push(evt.text);
    });

    fakeProc.emit_event({ version: PROTOCOL_VERSION, type: "token", text: "Hello" });
    await new Promise((r) => setImmediate(r));
    unsub();
    fakeProc.emit_event({ version: PROTOCOL_VERSION, type: "token", text: "after" });
    await new Promise((r) => setImmediate(r));

    expect(tokens).toEqual(["Hello"]);
  });

  it("emits parse_error for invalid NDJSON", async () => {
    const { sup, fakeProc } = makeSupervisor();
    const startP = sup.start();
    fakeProc.emit_event({ version: PROTOCOL_VERSION, type: "ready" });
    await startP;

    const errors: string[] = [];
    sup.on("parse_error", (raw: string) => errors.push(raw));

    fakeProc.stdout.push("not-json\n");
    await new Promise((r) => setImmediate(r));
    expect(errors).toContain("not-json");
  });

  it("emits log for sidecar stderr output", async () => {
    const { sup, fakeProc } = makeSupervisor();
    const startP = sup.start();
    fakeProc.emit_event({ version: PROTOCOL_VERSION, type: "ready" });
    await startP;

    const logs: string[] = [];
    sup.on("log", (text: string) => logs.push(text));

    fakeProc.stderr.push("WARNING: something\n");
    await new Promise((r) => setImmediate(r));
    expect(logs.some((l) => l.includes("WARNING: something"))).toBe(true);
  });

  it("emits fatal after maxRestarts exceeded", async () => {
    // maxRestarts=1: first crash → restart; second crash → fatal.
    // We need spawnFn to return a fresh FakeProc each call so the second
    // spawn gets its own close event.
    const proc1 = new FakeProc();
    const proc2 = new FakeProc();
    const spawnFn = vi.fn().mockReturnValueOnce(proc1).mockReturnValueOnce(proc2);

    const sup = new PythonSupervisor({
      pythonPath: "/fake/python",
      cwd: "/fake/cwd",
      maxRestarts: 1,
      baseBackoffMs: 10,
      spawnFn: spawnFn as any,
    });

    const startP = sup.start();
    proc1.emit_event({ version: PROTOCOL_VERSION, type: "ready" });
    await startP;

    const fatalErrors: Error[] = [];
    sup.on("fatal", (err: Error) => fatalErrors.push(err));

    // First crash → schedules restart after 10ms
    proc1.exit(1);
    // Wait for restart delay + second proc to be spawned and crash
    await new Promise((r) => setTimeout(r, 50));
    proc2.exit(1);
    await new Promise((r) => setTimeout(r, 50));

    expect(fatalErrors.length).toBeGreaterThanOrEqual(1);
  });

  it("command_error event rejects the matching pending request", async () => {
    const { sup, fakeProc } = makeSupervisor();
    const startP = sup.start();
    fakeProc.emit_event({ version: PROTOCOL_VERSION, type: "ready" });
    await startP;

    let sentId = "";
    fakeProc.stdin.on("data", (chunk: Buffer) => {
      const parsed = JSON.parse(chunk.toString().trim());
      sentId = parsed.id;
      fakeProc.emit_event({
        version: PROTOCOL_VERSION,
        type: "command_error",
        request_id: sentId,
        message: "bad command",
      });
    });

    await expect(sup.request("run", { task: "x" })).rejects.toThrow("bad command");
  });
});
