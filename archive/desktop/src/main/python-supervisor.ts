/**
 * Python sidecar supervisor — spawns the dagi-gui-sidecar process, reads
 * its NDJSON stdout, and dispatches events to subscribers.
 *
 * Responsibilities:
 *  - Start / restart the sidecar process (with exponential back-off)
 *  - Write commands as NDJSON lines to sidecar stdin
 *  - Split stdout on newlines, parse events, fan out to listeners
 *  - Reject pending requests when the process crashes
 *  - Expose a clean stop() that sends shutdown and terminates
 */

import { spawn as nodeSpawn, ChildProcess, SpawnOptions } from "child_process";
import { EventEmitter } from "events";
import { parseEvent, SidecarEvent, makeCommandId } from "@shared/protocol";

type SpawnFn = (cmd: string, args: string[], opts: SpawnOptions) => ChildProcess;
type EventHandler = (event: SidecarEvent) => void;
type AckResolver = (result: Record<string, unknown>) => void;
type AckRejector = (err: Error) => void;

export interface SupervisorOptions {
  /** Path to the Python interpreter (e.g. conda env python). */
  pythonPath: string;
  /** Working directory for the sidecar process. */
  cwd: string;
  /** Max restart attempts before giving up (0 = never restart). */
  maxRestarts?: number;
  /** Base back-off delay in ms (doubles each attempt). */
  baseBackoffMs?: number;
  /** Injectable spawn function for testing. Defaults to child_process.spawn. */
  spawnFn?: SpawnFn;
}

interface PendingRequest {
  resolve: AckResolver;
  reject: AckRejector;
}

export class PythonSupervisor extends EventEmitter {
  private readonly _opts: Required<SupervisorOptions>;
  private _proc: ChildProcess | null = null;
  private _pending = new Map<string, PendingRequest>();
  private _restarts = 0;
  private _stopped = false;
  private _stdoutBuf = "";
  private _ready = false;
  private _lastStderr: string[] = [];
  private static readonly _MAX_STDERR_LINES = 30;

  constructor(opts: SupervisorOptions) {
    super();
    this._opts = {
      maxRestarts: 3,
      baseBackoffMs: 500,
      spawnFn: nodeSpawn as SpawnFn,
      ...opts,
    };
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  /** Spawn the sidecar. Resolves when the first "ready" event is received. */
  start(): Promise<void> {
    return new Promise((resolve, reject) => {
      const onReady = (evt: SidecarEvent) => {
        if (evt.type === "ready") {
          this.off("event", onReady);
          this._ready = true;
          resolve();
        }
      };
      this.on("event", onReady);
      try {
        this._spawn();
      } catch (err) {
        this.off("event", onReady);
        reject(err);
      }
      // Reject if process dies before ready
      this.once("crash", (err: Error) => {
        this.off("event", onReady);
        const stderr = this._lastStderr.length
          ? `\n\nPython stderr:\n${this._lastStderr.join("\n")}`
          : "";
        reject(new Error(err.message + stderr));
      });
    });
  }

  /**
   * Send a command and wait for its ack. Returns the ack result payload.
   * Rejects if the process crashes before acking.
   */
  request(
    type: string,
    extras: Record<string, unknown> = {}
  ): Promise<Record<string, unknown>> {
    const id = makeCommandId();
    return new Promise((resolve, reject) => {
      this._pending.set(id, { resolve, reject });
      const line = JSON.stringify({ version: 1, id, type, ...extras }) + "\n";
      if (!this._proc?.stdin?.writable) {
        this._pending.delete(id);
        reject(new Error("Sidecar not running"));
        return;
      }
      this._proc.stdin.write(line);
    });
  }

  /** Subscribe to a specific event type emitted by the sidecar. */
  subscribe(eventType: string, handler: EventHandler): () => void {
    const wrapper = (evt: SidecarEvent) => {
      if (evt.type === eventType) handler(evt);
    };
    this.on("event", wrapper);
    return () => this.off("event", wrapper);
  }

  /** Stop the sidecar gracefully; falls back to SIGKILL after timeout. */
  async stop(timeoutMs = 3000): Promise<void> {
    this._stopped = true;
    if (!this._proc) return;

    // Try graceful shutdown
    try {
      await this.request("shutdown", {}).catch(() => undefined);
    } catch {
      // already dead
    }

    // Wait for exit or force-kill
    await new Promise<void>((resolve) => {
      const t = setTimeout(() => {
        this._proc?.kill("SIGKILL");
        resolve();
      }, timeoutMs);
      this._proc?.once("close", () => {
        clearTimeout(t);
        resolve();
      });
    });

    this._proc = null;
  }

  get isReady(): boolean {
    return this._ready;
  }

  // ── Private ────────────────────────────────────────────────────────────────

  private _spawn(): void {
    const { pythonPath, cwd, spawnFn } = this._opts;
    const proc = spawnFn(pythonPath, ["-m", "dagi_gui"], {
      cwd,
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env, PYTHONUNBUFFERED: "1", PYTHONPATH: cwd },
    });

    proc.stderr?.on("data", (chunk: Buffer) => {
      const text = chunk.toString("utf8").trimEnd();
      if (!text) return;
      this.emit("log", text);
      const lines = text.split("\n");
      this._lastStderr.push(...lines);
      if (this._lastStderr.length > PythonSupervisor._MAX_STDERR_LINES) {
        this._lastStderr.splice(0, this._lastStderr.length - PythonSupervisor._MAX_STDERR_LINES);
      }
    });

    proc.stdout?.setEncoding("utf8");
    proc.stdout?.on("data", (chunk: string) => {
      this._stdoutBuf += chunk;
      this._flushLines();
    });

    proc.once("close", (code) => {
      this._ready = false;
      this._rejectAllPending(new Error(`Sidecar exited (code=${code})`));
      if (!this._stopped) {
        this._scheduleRestart(code);
      }
    });

    proc.once("error", (err) => {
      this.emit("error", err);
    });

    this._proc = proc;
  }

  private _flushLines(): void {
    const lines = this._stdoutBuf.split("\n");
    this._stdoutBuf = lines.pop() ?? "";
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      const evt = parseEvent(trimmed);
      if (evt === null) {
        this.emit("parse_error", trimmed);
        continue;
      }
      // Resolve pending ack
      if (evt.type === "ack") {
        const p = this._pending.get(evt.request_id);
        if (p) {
          this._pending.delete(evt.request_id);
          p.resolve(evt.result ?? {});
        }
      } else if (evt.type === "command_error" && evt.request_id) {
        const p = this._pending.get(evt.request_id);
        if (p) {
          this._pending.delete(evt.request_id);
          p.reject(new Error(evt.message));
        }
      }
      this.emit("event", evt);
    }
  }

  private _rejectAllPending(err: Error): void {
    for (const [id, p] of this._pending) {
      this._pending.delete(id);
      p.reject(err);
    }
    this.emit("crash", err);
  }

  /** Last N lines of stderr — useful for crash diagnostics. */
  get lastStderr(): string {
    return this._lastStderr.join("\n");
  }

  private _scheduleRestart(code: number | null): void {
    const { maxRestarts, baseBackoffMs } = this._opts;
    if (maxRestarts === 0 || this._restarts >= maxRestarts) {
      const stderr = this._lastStderr.length
        ? `\n\nPython stderr:\n${this._lastStderr.join("\n")}`
        : "";
      this.emit("fatal", new Error(`Sidecar crashed (code=${code}); max restarts reached${stderr}`));
      return;
    }
    const delay = baseBackoffMs * Math.pow(2, this._restarts);
    this._restarts++;
    this.emit("restarting", { attempt: this._restarts, delayMs: delay });
    setTimeout(() => {
      if (!this._stopped) this._spawn();
    }, delay);
  }
}
