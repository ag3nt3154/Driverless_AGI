/**
 * Preload script — runs in the renderer's isolated world with selective
 * access to ipcRenderer. Exposes a narrow, typed API via contextBridge
 * so the renderer never touches Electron internals directly.
 *
 * Security rules:
 *  - Only whitelisted IPC channels are allowed
 *  - No Node.js APIs leak into renderer scope
 *  - contextIsolation: true + sandbox: true are enforced in main.ts
 */

import { contextBridge, ipcRenderer, IpcRendererEvent } from "electron";

// Channels the renderer may send on (main process listens)
const SEND_CHANNELS = new Set([
  "dagi:command",
  "dagi:window-state",
]);

// Channels the renderer may listen on (main process sends)
const RECV_CHANNELS = new Set([
  "dagi:event",
  "dagi:crash",
  "dagi:ready",
]);

export type DagiAPI = typeof api;

const api = {
  /** Send a command to the main process. */
  send(channel: string, payload: unknown): void {
    if (!SEND_CHANNELS.has(channel)) {
      console.error(`[preload] Blocked send on disallowed channel: ${channel}`);
      return;
    }
    ipcRenderer.send(channel, payload);
  },

  /** Subscribe to events from the main process. Returns unsubscribe fn. */
  on(channel: string, fn: (payload: unknown) => void): () => void {
    if (!RECV_CHANNELS.has(channel)) {
      console.error(`[preload] Blocked subscribe on disallowed channel: ${channel}`);
      return () => undefined;
    }
    const handler = (_evt: IpcRendererEvent, payload: unknown) => fn(payload);
    ipcRenderer.on(channel, handler);
    return () => ipcRenderer.removeListener(channel, handler);
  },

  /** One-shot listener. */
  once(channel: string, fn: (payload: unknown) => void): void {
    if (!RECV_CHANNELS.has(channel)) return;
    ipcRenderer.once(channel, (_evt, payload) => fn(payload));
  },
};

contextBridge.exposeInMainWorld("dagiAPI", api);

// Type augmentation for renderer TypeScript
declare global {
  interface Window {
    dagiAPI: DagiAPI;
  }
}
