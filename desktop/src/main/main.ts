/**
 * Electron main process.
 *
 * Responsibilities:
 *  - Create a hardened BrowserWindow (contextIsolation, sandbox, no nodeIntegration)
 *  - Persist window size/position via electron-window-state
 *  - Spawn and supervise the Python sidecar via PythonSupervisor
 *  - Bridge IPC: renderer → main → sidecar (commands) and sidecar → main → renderer (events)
 *  - Show a crash dialog and attempt restart on sidecar fatal
 */

import { app, BrowserWindow, ipcMain, dialog } from "electron";
import path from "path";
import windowStateKeeper from "electron-window-state";
import { PythonSupervisor } from "./python-supervisor";
import type { SidecarEvent } from "@shared/protocol";

declare const MAIN_WINDOW_VITE_DEV_SERVER_URL: string;
declare const MAIN_WINDOW_VITE_NAME: string;

// ── Config ────────────────────────────────────────────────────────────────────

const isDev = process.env.NODE_ENV !== "production";
const projectRoot = app.isPackaged
  ? path.dirname(process.execPath)
  : path.resolve(__dirname, "../../..");

function resolvePython(): string {
  if (process.env.DAGI_PYTHON) return process.env.DAGI_PYTHON;
  // Prefer conda env; fall back to PATH python
  const condaEnv = process.env.CONDA_PREFIX;
  if (condaEnv) {
    return process.platform === "win32"
      ? path.join(condaEnv, "python.exe")
      : path.join(condaEnv, "bin", "python");
  }
  return process.platform === "win32" ? "python.exe" : "python3";
}

// ── Sidecar supervisor ────────────────────────────────────────────────────────

let supervisor: PythonSupervisor | null = null;
let mainWindow: BrowserWindow | null = null;

function buildSupervisor(): PythonSupervisor {
  const sup = new PythonSupervisor({
    pythonPath: resolvePython(),
    cwd: projectRoot,
    maxRestarts: 3,
    baseBackoffMs: 1000,
  });

  // Forward all sidecar events to the renderer
  sup.on("event", (evt: SidecarEvent) => {
    mainWindow?.webContents.send("dagi:event", evt);
  });

  sup.on("log", (text: string) => {
    if (isDev) console.error("[sidecar]", text);
  });

  sup.on("fatal", (err: Error) => {
    dialog.showErrorBox(
      "DAGI sidecar crashed",
      `The Python agent process has crashed after multiple restart attempts.\n\n${err.message}\n\nPlease restart the application.`
    );
  });

  sup.on("restarting", ({ attempt, delayMs }: { attempt: number; delayMs: number }) => {
    if (isDev) console.log(`[sidecar] restarting (attempt ${attempt}, delay ${delayMs}ms)`);
    mainWindow?.webContents.send("dagi:crash", { attempt, delayMs });
  });

  return sup;
}

// ── Window creation ───────────────────────────────────────────────────────────

function createWindow(): BrowserWindow {
  const saved = windowStateKeeper({ defaultWidth: 1280, defaultHeight: 800 });

  const win = new BrowserWindow({
    x: saved.x,
    y: saved.y,
    width: saved.width,
    height: saved.height,
    minWidth: 640,
    minHeight: 480,
    backgroundColor: "#0d0d0d",
    show: false, // shown after ready-to-show to avoid flash
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
    },
  });

  saved.manage(win);

  win.once("ready-to-show", () => win.show());

  if (MAIN_WINDOW_VITE_DEV_SERVER_URL) {
    win.loadURL(MAIN_WINDOW_VITE_DEV_SERVER_URL);
    if (isDev) win.webContents.openDevTools();
  } else {
    win.loadFile(
      path.join(__dirname, `../renderer/${MAIN_WINDOW_VITE_NAME}/index.html`)
    );
  }

  win.on("closed", () => {
    mainWindow = null;
  });

  return win;
}

// ── IPC handlers ──────────────────────────────────────────────────────────────

function registerIpc(): void {
  // Renderer → main → sidecar
  ipcMain.on("dagi:command", async (_evt, payload: unknown) => {
    if (!supervisor) return;
    try {
      if (typeof payload !== "object" || payload === null) return;
      const p = payload as Record<string, unknown>;
      await supervisor.request(p["type"] as string, p);
    } catch (err) {
      mainWindow?.webContents.send("dagi:event", {
        version: 1,
        type: "command_error",
        message: String(err),
      });
    }
  });
}

// ── App lifecycle ─────────────────────────────────────────────────────────────

app.whenReady().then(async () => {
  registerIpc();
  mainWindow = createWindow();

  supervisor = buildSupervisor();
  try {
    await supervisor.start();
    mainWindow?.webContents.send("dagi:ready", {});
  } catch (err) {
    dialog.showErrorBox("DAGI failed to start", String(err));
  }

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      mainWindow = createWindow();
    }
  });
});

app.on("window-all-closed", async () => {
  if (supervisor) {
    await supervisor.stop().catch(() => undefined);
    supervisor = null;
  }
  if (process.platform !== "darwin") app.quit();
});
