/**
 * Preload script — runs in a sandboxed renderer context with access to
 * a limited Node.js API. Exposes the IPC bridge via contextBridge.
 * Populated fully in Task 8 (Secure IPC).
 */

import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("dagiAPI", {
  send: (channel: string, data: unknown) => ipcRenderer.send(channel, data),
  on: (channel: string, fn: (...args: unknown[]) => void) => {
    ipcRenderer.on(channel, (_evt, ...args) => fn(...args));
  },
  removeAllListeners: (channel: string) => ipcRenderer.removeAllListeners(channel),
});
