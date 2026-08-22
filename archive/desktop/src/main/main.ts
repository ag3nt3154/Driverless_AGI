/**
 * Electron main process.
 *
 * Responsibilities:
 *  - Resolve the Python interpreter (env var → saved config → conda picker)
 *  - Create a hardened BrowserWindow (contextIsolation, sandbox, no nodeIntegration)
 *  - Persist window size/position via electron-window-state
 *  - Spawn and supervise the Python sidecar via PythonSupervisor
 *  - Bridge IPC: renderer → main → sidecar (commands) and sidecar → main → renderer (events)
 */

import { app, BrowserWindow, ipcMain, dialog, Menu, MenuItem } from "electron";
import path from "path";
import fs from "fs";
import windowStateKeeper from "electron-window-state";
import { PythonSupervisor } from "./python-supervisor";
import type { SidecarEvent } from "@shared/protocol";

declare const MAIN_WINDOW_VITE_DEV_SERVER_URL: string;
declare const MAIN_WINDOW_VITE_NAME: string;

// ── Constants ─────────────────────────────────────────────────────────────────

const isDev = process.env.NODE_ENV !== "production";

/**
 * Walk upward from `start` looking for pyproject.toml — the definitive
 * marker that we're inside the DAGI repo.
 */
function findRepoRoot(start: string): string | null {
  let dir = path.resolve(start);
  const { root } = path.parse(dir);
  while (dir !== root) {
    if (fs.existsSync(path.join(dir, "pyproject.toml"))) return dir;
    dir = path.dirname(dir);
  }
  return null;
}

/**
 * Resolve the DAGI repo root.
 *
 * Priority:
 *  1. DAGI_ROOT env var (explicit override)
 *  2. Walk upward from __dirname (works in dev + portable exe inside repo)
 *  3. Walk upward from the exe path (packaged, exe still inside repo tree)
 *  4. Saved path from config.json
 *  5. null → user will be prompted later
 */
function resolveProjectRoot(): string | null {
  if (process.env.DAGI_ROOT && fs.existsSync(process.env.DAGI_ROOT)) {
    return process.env.DAGI_ROOT;
  }
  const fromDir = findRepoRoot(__dirname);
  if (fromDir) return fromDir;
  if (app.isPackaged) {
    const fromExe = findRepoRoot(path.dirname(process.execPath));
    if (fromExe) return fromExe;
  }
  const saved = loadConfig().projectRoot;
  if (saved && fs.existsSync(path.join(saved, "pyproject.toml"))) {
    return saved;
  }
  return null;
}

let projectRoot: string;

// ── Config persistence ────────────────────────────────────────────────────────

interface AppConfig {
  pythonPath?: string;
  projectRoot?: string;
}

function configPath(): string {
  return path.join(app.getPath("userData"), "config.json");
}

function loadConfig(): AppConfig {
  try {
    return JSON.parse(fs.readFileSync(configPath(), "utf8")) as AppConfig;
  } catch {
    return {};
  }
}

function saveConfig(cfg: AppConfig): void {
  fs.mkdirSync(path.dirname(configPath()), { recursive: true });
  fs.writeFileSync(configPath(), JSON.stringify(cfg, null, 2), "utf8");
}

// ── Conda env detection ───────────────────────────────────────────────────────

interface CondaEnv {
  name: string;
  pythonPath: string;
}

function scanCondaEnvs(): CondaEnv[] {
  const home = process.env.USERPROFILE ?? process.env.HOME ?? "";
  const roots = [
    path.join(home, "miniconda3"),
    path.join(home, "anaconda3"),
    path.join(home, "AppData", "Local", "miniconda3"),
    "C:\\ProgramData\\miniconda3",
    "/opt/conda",
    "/usr/local/miniconda3",
  ];

  const envs: CondaEnv[] = [];

  for (const root of roots) {
    const basePy = process.platform === "win32"
      ? path.join(root, "python.exe")
      : path.join(root, "bin", "python");
    if (fs.existsSync(basePy)) {
      envs.push({ name: `base (${path.basename(root)})`, pythonPath: basePy });
    }

    const envsDir = path.join(root, "envs");
    if (!fs.existsSync(envsDir)) continue;
    for (const name of fs.readdirSync(envsDir)) {
      const py = process.platform === "win32"
        ? path.join(envsDir, name, "python.exe")
        : path.join(envsDir, name, "bin", "python");
      if (fs.existsSync(py)) {
        envs.push({ name, pythonPath: py });
      }
    }
  }

  return envs.filter((e, i) => envs.findIndex(x => x.pythonPath === e.pythonPath) === i);
}

// ── Python resolution ─────────────────────────────────────────────────────────

async function showEnvPicker(envs: CondaEnv[]): Promise<string | null> {
  const buttons = [...envs.map(e => e.name), "Browse...", "Cancel"];
  const { response } = await dialog.showMessageBox({
    type: "question",
    title: "DAGI — Choose Python environment",
    message: "Select the conda environment that has dagi_gui installed:",
    detail: "This is saved and can be changed via File → Change Python.",
    buttons,
    defaultId: Math.max(0, envs.findIndex(e => e.name === "dagi")),
    cancelId: buttons.length - 1,
  });

  if (response === buttons.length - 1) return null;
  if (response === buttons.length - 2) {
    const { filePaths } = await dialog.showOpenDialog({
      title: "Select python.exe",
      filters: [{ name: "Python", extensions: ["exe", "*"] }],
      properties: ["openFile"],
    });
    return filePaths[0] ?? null;
  }
  return envs[response].pythonPath;
}

async function promptForRepoRoot(): Promise<string | null> {
  const { filePaths } = await dialog.showOpenDialog({
    title: "DAGI — Select project root",
    message: "Choose the Driverless_AGI repo folder (contains pyproject.toml):",
    properties: ["openDirectory"],
  });
  const chosen = filePaths[0];
  if (!chosen) return null;
  if (!fs.existsSync(path.join(chosen, "pyproject.toml"))) {
    dialog.showErrorBox(
      "Not a DAGI repo",
      `${chosen}\n\nNo pyproject.toml found. Please select the root of your Driverless_AGI clone.`,
    );
    return null;
  }
  saveConfig({ ...loadConfig(), projectRoot: chosen });
  return chosen;
}

async function resolvePython(): Promise<string> {
  if (process.env.DAGI_PYTHON && fs.existsSync(process.env.DAGI_PYTHON)) {
    return process.env.DAGI_PYTHON;
  }

  const saved = loadConfig().pythonPath;
  if (saved && fs.existsSync(saved)) return saved;

  const envs = scanCondaEnvs();
  const chosen = await showEnvPicker(envs);
  if (!chosen) {
    app.quit();
    return "python";
  }

  saveConfig({ pythonPath: chosen });
  return chosen;
}

// ── Sidecar supervisor ────────────────────────────────────────────────────────

let supervisor: PythonSupervisor | null = null;
let mainWindow: BrowserWindow | null = null;

function buildSupervisor(pythonPath: string): PythonSupervisor {
  const sup = new PythonSupervisor({
    pythonPath,
    cwd: projectRoot,
    maxRestarts: 3,
    baseBackoffMs: 1000,
  });

  sup.on("event", (evt: SidecarEvent) => {
    mainWindow?.webContents.send("dagi:event", evt);
  });

  sup.on("log", (text: string) => {
    if (isDev) console.error("[sidecar]", text);
  });

  sup.on("fatal", (err: Error) => {
    dialog.showErrorBox(
      "DAGI sidecar crashed",
      `The Python agent process crashed after multiple restart attempts.\n\n${err.message}\n\nUse File → Change Python to reconfigure, then restart.`
    );
  });

  sup.on("restarting", ({ attempt, delayMs }: { attempt: number; delayMs: number }) => {
    if (isDev) console.log(`[sidecar] restarting (attempt ${attempt}, delay ${delayMs}ms)`);
    mainWindow?.webContents.send("dagi:crash", { attempt, delayMs });
  });

  return sup;
}

// ── Menu ──────────────────────────────────────────────────────────────────────

function buildMenu(): void {
  const menu = new Menu();
  menu.append(new MenuItem({
    label: "File",
    submenu: Menu.buildFromTemplate([
      {
        label: "Change Python environment…",
        click: async () => {
          const envs = scanCondaEnvs();
          const chosen = await showEnvPicker(envs);
          if (!chosen) return;
          saveConfig({ pythonPath: chosen });
          dialog.showMessageBox({
            type: "info",
            message: "Python environment updated.",
            detail: `${chosen}\n\nRestart DAGI to apply.`,
            buttons: ["OK"],
          });
        },
      },
      {
        label: "Change project root…",
        click: async () => {
          const chosen = await promptForRepoRoot();
          if (!chosen) return;
          dialog.showMessageBox({
            type: "info",
            message: "Project root updated.",
            detail: `${chosen}\n\nRestart DAGI to apply.`,
            buttons: ["OK"],
          });
        },
      },
      { type: "separator" },
      { role: "quit" },
    ]),
  }));
  if (isDev) {
    menu.append(new MenuItem({
      label: "Dev",
      submenu: Menu.buildFromTemplate([
        { role: "reload" },
        { role: "toggleDevTools" },
      ]),
    }));
  }
  Menu.setApplicationMenu(menu);
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
    show: false,
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

  win.on("closed", () => { mainWindow = null; });
  return win;
}

// ── IPC handlers ──────────────────────────────────────────────────────────────

function registerIpc(): void {
  ipcMain.on("dagi:command", async (_evt, payload: unknown) => {
    if (!supervisor) return;
    try {
      if (typeof payload !== "object" || payload === null) return;
      const p = payload as Record<string, unknown>;
      await supervisor.request(p["type"] as string, p);
    } catch (err) {
      mainWindow?.webContents.send("dagi:event", {
        version: 1, type: "command_error", message: String(err),
      });
    }
  });
}

// ── App lifecycle ─────────────────────────────────────────────────────────────

app.whenReady().then(async () => {
  // Resolve repo root first — everything depends on it
  const root = resolveProjectRoot();
  if (root) {
    projectRoot = root;
  } else {
    const chosen = await promptForRepoRoot();
    if (!chosen) { app.quit(); return; }
    projectRoot = chosen;
  }

  buildMenu();
  registerIpc();
  mainWindow = createWindow();

  const pythonPath = await resolvePython();
  supervisor = buildSupervisor(pythonPath);
  try {
    await supervisor.start();
    mainWindow?.webContents.send("dagi:ready", {});
  } catch (err) {
    dialog.showErrorBox(
      "DAGI failed to start",
      `Python: ${pythonPath}\nRepo: ${projectRoot}\n\n${String(err)}\n\nUse File → Change Python environment to reconfigure.`
    );
  }

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) mainWindow = createWindow();
  });
});

app.on("window-all-closed", async () => {
  if (supervisor) {
    await supervisor.stop().catch(() => undefined);
    supervisor = null;
  }
  if (process.platform !== "darwin") app.quit();
});
