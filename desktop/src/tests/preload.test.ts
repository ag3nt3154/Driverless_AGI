// @vitest-environment node
/**
 * Tests for the preload channel whitelist logic.
 * We can't import preload.ts directly (contextBridge is Electron-only),
 * so we extract and test the channel-gate predicate in isolation.
 */

import { describe, it, expect, vi } from "vitest";

// ── Replicate the whitelist logic from preload.ts ─────────────────────────────

const SEND_CHANNELS = new Set(["dagi:command", "dagi:window-state"]);
const RECV_CHANNELS = new Set(["dagi:event", "dagi:crash", "dagi:ready"]);

function canSend(channel: string): boolean {
  return SEND_CHANNELS.has(channel);
}

function canReceive(channel: string): boolean {
  return RECV_CHANNELS.has(channel);
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("Preload channel whitelist", () => {
  it("allows dagi:command on send", () => {
    expect(canSend("dagi:command")).toBe(true);
  });

  it("allows dagi:window-state on send", () => {
    expect(canSend("dagi:window-state")).toBe(true);
  });

  it("blocks arbitrary channels on send", () => {
    expect(canSend("shell:exec")).toBe(false);
    expect(canSend("dagi:event")).toBe(false);
    expect(canSend("")).toBe(false);
  });

  it("allows dagi:event on receive", () => {
    expect(canReceive("dagi:event")).toBe(true);
  });

  it("allows dagi:crash on receive", () => {
    expect(canReceive("dagi:crash")).toBe(true);
  });

  it("allows dagi:ready on receive", () => {
    expect(canReceive("dagi:ready")).toBe(true);
  });

  it("blocks send channels from receive", () => {
    expect(canReceive("dagi:command")).toBe(false);
    expect(canReceive("dagi:window-state")).toBe(false);
  });

  it("blocks arbitrary channels on receive", () => {
    expect(canReceive("shell:exec")).toBe(false);
    expect(canReceive("")).toBe(false);
  });
});
