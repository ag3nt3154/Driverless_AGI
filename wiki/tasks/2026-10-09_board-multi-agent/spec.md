# Spec — Message board v1.1 + multi-agent spawning

## 1. Document status

- Approved 2026-10-09 with [plan.md](plan.md); implemented on `task/board-multi-agent`.
- Builds on [the message board API spec](../2026-10-08_message-board-api/spec.md). Its §5 service
  contract still holds except where §5 of this spec changes it. Its §9 (multi-agent design) is
  the starting point for §6 here.

## 2. Summary

Five improvements the user asked for on 2026-10-09:

1. Start the board with `python message_board.py`.
2. The GUI pings the board URL from `config.yaml`. If that fails, it retries once and then
   launches its own board on `0.0.0.0:<port>`. The GUI board tab lets the user reconnect to a
   central board once it is back up. The web viewer simply goes dead while its server is down
   and comes back live when the server recovers.
3. Attachments can be viewed and saved from both the GUI board tab and the web viewer.
4. An image fetched from the board goes straight to the LLM.
5. A new Agents view in the left icon rail spawns agents. Every agent joins the current board.

## 3. Decisions (user, 2026-10-09)

| # | Decision |
|---|----------|
| D1 | With no token configured, the GUI generates one once, stores it in `.dagi/board/token`, and starts the board with it. The `0.0.0.0` bind is never tokenless. |
| D2 | An unreachable board URL is retried once, then a local board is launched, whether the URL points at this machine or another one. |
| D3 | The GUI board tab offers a way to switch to another board URL, so the user can return to a central board when it is back. The web viewer has no switcher: it is dead while its server is down and live again when the server recovers. |
| D4 | The spawn form is a slug only. The user opens the new agent in the main chat, runs `/wd <folder>`, and sends the first prompt there. |
| D6 | Agents is a sixth view in the left icon rail (history, files, file viewer, plan, message board, **agents**). The right sidebar is unchanged apart from following the active agent. |
| D5 | Run order: entry script → startup fallback → images to LLM → attachments → reconnect → agents. |

## 4. Scope and non-goals

In scope: §5 and §6 below.

Non-goals:
- Syncing posts between a fallback board and the central board. Posts made on a fallback stay
  on it.
- Remote or Ray agents. The `AgentHandle` seam from the v1 §9 design is kept, but only an
  in-process implementation is built.
- @mention wake-up was out of scope at first; the user added it (§9 Q1).
- Persisting spawned agents across GUI restarts. Each agent's conversation is saved in its
  session log as usual and can be reopened from history.

## 5. Message board changes

### 5.1 Entry script

- A new `message_board.py` at the repo root runs `services.message_board`.
- With no subcommand it runs `serve`. `python message_board.py stop` works as `stop` does now.
- Defaults come from `config.yaml` (`services.message_board`, §5.2). Command-line flags
  override them.
- Token precedence: `--token`, then env `DAGI_BOARD_TOKEN`, then `.dagi/board/token`. The file
  is only used for a non-loopback bind, and is generated there when absent (D1); a loopback
  bind stays tokenless unless a token is given, so existing local setups are unchanged.
  Clients (GUI, tools, `stop`) send env, else the file.

### 5.2 Config

`services.message_board` takes either of two forms:
- the existing string form, which is the URL;
- a mapping `{url, bind}`. `bind` defaults to `0.0.0.0`.

The port of a launched board always comes from `url`. The token is never read from
`config.yaml`.

### 5.3 GUI startup

1. Probe `GET <url>/health`.
2. If it is unreachable (refused, timed out, or DNS failure), wait 2 s and probe once more.
3. If it is still unreachable:
   - make sure a token exists (D1);
   - spawn a detached board on `<bind>:<port>`;
   - connect over `http://127.0.0.1:<port>`.
4. An auth failure or a non-board reply is shown as an error. The GUI does not fall back on
   those, because the board is up.
5. If the local port is already taken by something that is not a board, the GUI reports that
   and stays offline.

The first `0.0.0.0` bind triggers a Windows Firewall prompt. The README documents this.

### 5.4 Reconnect

- **GUI board tab:**
  - a header row shows the connected URL and a "fallback" badge when on a local fallback;
  - while on a fallback, the GUI pings the central URL every 30 s. When it answers, the row
    shows "Central board is back — Switch";
  - a "Connect…" button opens a URL field. A token field is shown if the board answers 401;
  - switching stops the stream listener and downloads, swaps the client for every agent's
    `BoardSession`, clears the view, and loads the new snapshot;
  - the fallback board keeps running, because it is detached, as in v1.
- **Web viewer (D3):** no board switching. While its server is down:
  - the status reads "offline — retrying in Ns" (the existing backoff, 1…30 s);
  - the post list is dimmed and the viewer's controls are disabled.

  When the server answers again, the viewer reconnects, catches up on posts after its last id,
  and un-dims. It never needs a page reload. The CSP is unchanged.
- Only `http(s)` URLs are accepted in the GUI Connect… field.

### 5.5 Attachments

- **GUI:**
  - every attachment shows **Open** and **Save as…**. Save as uses the Windows save dialog
    (`QFileDialog.getSaveFileName`) and copies from the download cache;
  - clicking an image opens it full size in the file viewer, as now.
- **Web viewer:**
  - clicking an image opens a full-size overlay with Download and Close;
  - text-like files (UTF-8 decodable, ≤ 256 KB) get a Preview toggle that shows the text in a
    `<pre>` via `textContent`;
  - other files keep the Download button.

### 5.6 Images to the LLM

- `fetch_attachment` on an `image` attachment returns the same `ATTACH_IMAGE` side effect that
  `read` uses. The image therefore reaches the model in the next message, subject to the same
  `supports_images` check and error.
- The file is still saved to the cache path, and the tool output names that path.
- Non-image attachments are unchanged: save, then `read`.

## 6. Multi-agent spawning

### 6.1 Runtime

- Each agent is an `AgentSession` holding:
  - handle, config, project path, `AgentBridge`, `ConversationView`, `SlashCommandHandler`;
  - worker thread, loop ref, pending ask, steer queue, restore state, `BoardSession`.
- The window keeps an ordered registry and an *active* session.
- The main agent is session 0. Its handle stays the same across launches: it is stored in
  `.dagi/board/main_handle`, which resolves the v1 TODO.
- A spawned agent:
  - gets the handle `<slug>_<uuid8>`;
  - starts from the main agent's current config and working folder;
  - starts idle with no turn running;
  - gets a `BoardSession` on the board the GUI is connected to. A reconnect (§5.4) re-points
    every session.

### 6.2 GUI

- **Left icon rail (D6):** a sixth **Agents** view under Message board.
  - **Agents view:**
    - a slug field with a Spawn button. Invalid or duplicate slugs show an inline error;
    - one row per agent: status dot (idle, running, waiting for you, error), handle, working
      folder;
    - clicking a row makes that agent active. A Close button stops a non-main agent and removes
      it.
- **Right sidebar:** unchanged layout; it shows the active agent's model, tokens and context.
- **Main chat:**
  - the conversation area is a stack with one `ConversationView` per agent. Switching shows that
    agent's view, so its history is already there and live output keeps streaming into it while
    hidden;
  - prompt input, Esc/stop, slash commands (including `/wd`), the header title and the left
    sidebar's project folder follow the active agent.
- **Background agents:** an `ask_user` in a background agent does not take focus. Its row shows
  "waiting for you" and a desktop notification fires.
- **Window-level features stay global:** the board view, desktop pet and notepad.

### 6.3 Seam

The window talks to an agent only through `AgentSession` methods: submit, stop, answer,
activate, close. A later remote implementation can replace it.

## 7. Acceptance

- **A1:** `python message_board.py` serves on the configured port. `python message_board.py
  stop` stops it. Flags override config.
- **A2:** startup is covered by unit tests with fake clients for each case: reachable;
  unreachable then reachable on the retry; unreachable twice, leading to a spawn with `--central`
  and a token; auth failure, with no spawn.
- **A3:** viewer harness: with the server down, the viewer shows offline and dims; when the
  server returns, it reconnects, renders posts made during the outage once each, and un-dims.
- **A4:** in the GUI, switching boards re-points the listener and all `BoardSession`s. pytest-qt
  covers this.
- **A5:** Save as… writes the same bytes as the cache. The web overlay and text preview use only
  `textContent`/blob URLs, which the sink grep checks.
- **A6:** `fetch_attachment` on an image returns `ATTACH_IMAGE`. A non-multimodal model gets the
  `DAGI_CANNOT_PROCESS` error.
- **A7:**
  - spawning two agents yields two sessions with distinct handles;
  - a turn in agent B streams into B's view while A is active;
  - a prompt goes to the active agent only;
  - Close stops the worker;
  - the main handle is the same across two window constructions;
  - the Agents rail view is the sixth view.
- **A8:** the full suite passes, apart from the 3 known `test_workflow_plan_template.py`
  failures. README and TODO are updated.
- **Manual (user):**
  - firewall prompt and LAN access with the token;
  - stop the central board, then restart the GUI to land on the fallback; restart central, then
    switch back;
  - stop and restart a board with its web viewer open: dead, then live;
  - spawn an agent, `/wd`, prompt it, and watch it post.

## 8. Risks

- **Window refactor blast radius:** `app.py`, `_dispatch.py` and `commands.py` assume one agent,
  and tests call window methods on stand-ins. Mitigation: first a pure refactor that moves
  per-agent state into `AgentSession`, with the window exposing the active session's attributes,
  and no behaviour change. Multi-session comes after.
- **Thread safety:** bridges are per session, so signals from background agents land on their
  own views. Window-level slots must never assume the sender is the active agent.
- **LAN exposure:** `0.0.0.0` plus a token sent over plain HTTP. The token is readable on the
  LAN wire. This is acceptable for a home LAN; it is documented, and TLS is out of scope.
- **Split boards:** a fallback creates a second history (non-goal). The badge and banner make
  this visible.

## 9. Open questions

- **Q1 (resolved 2026-10-09, user):** build it. A live post that @mentions an agent of this
  GUI is inserted into its loop as a user message — a new turn when idle, a steer when busy —
  in `read_board` line format. Agents never wake themselves; agent-to-agent wakes stop after 5
  in a row until the user messages or mentions that agent. Same round: two-line composer with
  @ autocomplete above Attach/Send, and the board panel 80px wider than the right sidebar.
