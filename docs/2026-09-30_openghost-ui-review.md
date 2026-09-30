# OpenGhost UI/UX review — what to bring into DAGI

Date: 2026-09-30 · Source: <https://github.com/ANDRETRIPOL/OpenGhost> (v1.2.0 beta, Electron, plain JS)

OpenGhost's strength is less its widgets than how it *presents agent work*: it
pushes the model toward visual output and plain-language narration, then renders
both richly. DAGI's conversation pane is already a `QWebEngineView`
(`pyside_gui/resources/conversation.{html,css,js}`), so most ideas port into that
layer without new Qt code.

## License caveat

OpenGhost's code is MIT, but `LICENSE` excludes "the visual design of the
application, including its layout, colors, and interface" and "the animations"
(plus the name and ghost logo) from commercial use. Non-commercial use is allowed
if the copyright notice stays and the copy isn't presented as official OpenGhost.

- Fine for DAGI as a personal harness: keep an attribution note next to any
  borrowed palette/CSS.
- Do not ship borrowed styling in anything commercial.
- Do not copy the ghost art — use DAGI's own pet/VAD emotes instead.

## 1. Dark mode (decided)

Worth copying for its *structure*, not just its colours (`styles.css` top block):

| Token | Value | Use |
|---|---|---|
| `--app-bg` | `rgb(22,22,22)` | window / sidebar |
| `--chat-bg` | `rgb(25,25,25)` | conversation pane |
| `--composer-bg` | `rgb(30,30,30)` | input box |
| `--popover-bg` / `--menu-bg` | `rgb(33,33,33)` / `rgb(36,36,36)` | menus, popups |
| `--control-hover-bg` / `--row-active-bg` | `rgb(36,36,36)` / `rgb(39,39,39)` | hover, selected rows |
| `--fg-rgb` | `255,255,255` at opacities 0.85 / 0.55 / 0.25 / 0.10 | primary / secondary / tertiary / quaternary text |
| `--danger-rgb` `--success-rgb` `--warn-rgb` `--link-rgb` | `255,115,105` · `110,205,140` · `255,180,96` · `140,190,255` | semantic colour only |
| `--composer-accent-rgb` | `250,250,250` | white accent (send button, user bubble) |
| `--shadow` | `1` | global multiplier on every drop shadow |

Principles:

- Neutral greys, not tinted surfaces.
- One foreground colour at four opacities.
- Colour only carries meaning.
- The accent is white.
- Shadows are scaled by a single token.
- A light theme later is one token block (`[data-theme="light"]`).

For DAGI, one token source should drive both sides:

- the web layer: `conversation.css`, the notepad reskin;
- the Qt stylesheets: `menu_style.py`, sidebars, `slash_completer.py`, overlays.

Generating the QSS from a Python dict of the same tokens keeps them from drifting.

## 2. High value

### 2.1 Visualization-first output
The `FORMAT_GUIDE` in `chat.js` tells the model to draw whenever it can.

- **Format:** every chart or diagram goes in a ` ```mermaid ` fence whose first line
  is the diagram type:
  - structure and flow: flowchart, sequence, state, ER, class
  - data: `xychart-beta`, pie, quadrant, radar
  - plans and breakdowns: timeline, gantt, mindmap
- **GPT nudge:** GPT-family models get an extra "Before you answer" visual check
  appended at the end of the prompt.
- **DAGI port:**
  - Vendor mermaid.js next to Vditor.
  - Render mermaid fences in `conversation.js`, with a dark theme mapped to the tokens.
  - Add a trimmed formatting guide under `.dagi/prompts/`.
- **Skip** OpenGhost's own renderer (`diagram.js`, ~5k lines, with an in-place diagram
  editor). Plain mermaid covers most of the value.

### 2.2 `files` block
Folder listings come out as a structured block and render as a card with icons,
sizes and dates, instead of an ASCII tree:

```
files
  title Downloads
  path C:\Users\anna\Downloads
  report.pdf | 2.4 MB | 2026-09-27 14:05
  photos/ | 48 items | 2026-09-20
```

This fits a coding agent well. Rows could open in the existing `show_file` / file viewer.

### 2.3 "Talk while you work"
- **Narration:** before each tool call, or group of calls, the agent writes one plain
  sentence about what it is doing and why.
- **Tool descriptions:** tool calls carry a `description` argument written for a
  non-coder.
- **Cost:** prompt-only. It makes long runs readable, and the description can label the
  tool rows in the conversation view.

### 2.4 Selection menu → Ask / Mini chat
Selecting text in an assistant message shows a small toolbar (`selection-menu.js`):

- **Ask** quotes the selection into the composer.
- **Mini chat** opens a throwaway overlay chat:
  - It uses the current conversation as context.
  - It is never saved.
  - In DAGI it maps naturally to a forked scratch agent.

It keeps "what does this line mean?" detours out of the main context.

### 2.5 Permission modes + approval cards
- **Modes:** Ask / Auto / Full access, chosen from a pill in the composer. The mode is
  also described in the system prompt.
- **Approval card** (Ask mode, `approval-card.js`) shows:
  - a plain-language headline;
  - an effect badge, computed by the app rather than the model so a harmless-sounding
    sentence can't hide a deletion;
  - "place" chips for the folder, file or site involved;
  - the raw command or diff behind a show/hide toggle, whose state is remembered.
- **DAGI gap:** DAGI has no approval layer today. This is a real feature rather than a
  skin, and the most valuable one for safety.

## 3. Medium value

1. **Long paste → card.**
   - Large pastes collapse into a chip, and one click expands them back to text.
   - Good for pasted logs.
2. **Global instant Esc.** Stops the agent from anywhere in the window; DAGI's Esc pause
   is not global yet.
3. **Link chips.** URLs render as favicon + short domain (`link-chip.js`).
4. **Chats grouped by project folder** in the sidebar.
   - Includes pinning and rename in place.
   - Would slot into `sidebars/session_history.py`.
5. **Empty-state + thinking indicator.**
   - An idle mascot sits above the composer and animates while the agent thinks.
   - DAGI version: use the pet's VAD emotes, not the ghost art.
6. **Usage history.**
   - Tokens by day, week, month and all time, per provider and model.
   - Extends the right sidebar's live token stats.

## 4. Skip

- **Built-in browser panel.** Heavy, and DAGI already has web tools.
- **Visual polish.** Liquid glass, effort-slider morphs, the splash screen and the
  theme "ink spread" transition.
- **i18n.**

## Suggested order

1. Dark tokens (web + Qt from one source)
2. Mermaid rendering + formatting prompt (+ `files` block)
3. "Talk while you work" + tool `description`
4. Selection menu + mini chat
5. Permission modes + approval cards

## Decisions

### UI pass 1 (2026-09-30) — implemented
- **Palette: full neutral.**
  - Grey surfaces (22/25/30/33/36/39).
  - White text at 0.85 / 0.55 / 0.25 / 0.10.
  - Colour only for danger/success/warn/link.
  - White accent.
  - Catppuccin is retired, not kept as a second theme.
- **Message layout: OpenGhost-style.**
  - User messages are right-aligned light bubbles.
  - Assistant text sits directly on the chat background, with no card.
  - Centred reading column with a max width.
- **Scope: whole app, from one token source.**
  - A new `pyside_gui/theme.py` generates the QSS for every Qt widget (menus, composer,
    overlays, slash popup, both sidebars and their tabs, notepad panel).
  - The same values are pushed into the web view as CSS variables (conversation pane,
    Vditor reskin).
  - Replaces the hex codes currently hard-coded across 13 files.
- **Tool calls: quiet one-liners.**
  - A dim single line with an icon plus a plain-language description.
  - Click to expand input/output.
  - Pairs with the "talk while you work" prompt rule (§2.3).

- **Sidebars: restyle, keep structure.**
  - Both sidebars and all their tabs stay.
  - Neutral tokens, flat rows, an icon-only tab strip.
  - Collapsible with a toggle button.
- **Tool one-liner label: derived by the harness** from the tool name plus its key
  argument (e.g. "Read agent/loop.py", "Ran pytest tests -q"). A model-written
  `description` argument can override it later.
- **Typography:**
  - Conversation body 15px with a 1.65 line height, system-ui.
  - UI chrome stays at 13–14px.
- **Composer:**
  - A rounded card containing:
    - the image attachments row;
    - an auto-growing text field, replacing today's fixed 100px;
    - a `+` attach button that opens a file dialog, alongside paste;
    - a model pill that opens a picker popup from the model catalog (`/model` keeps
      working);
    - a white circular send button that becomes Stop while the agent runs.
  - Not in this pass:
    - context meter;
    - long-paste cards;
    - typing while the agent runs, since mid-run message queueing needs worker changes;
    - mode, effort and quote pills, which arrive with their features.

- **Defaults accepted:**
  - reasoning collapsed to "Thought for Ns";
  - pet idle emote as the empty state;
  - notepad on the same tokens;
  - sidebar toggles in a header bar.
- **Conversation rendered with Vditor** (user request): Lute + KaTeX + highlight.js, with
  Mermaid as a later drop-in via `Vditor.mermaidRender`.

### Implementation notes (pass 1, implemented 2026-09-30)

- **Qt side:** `pyside_gui/theme.py` holds the token table.
  - `qss()` handles `@token` substitution.
  - `with_theme()` splices tokens into HTML.
  - `qcolor()` / `solid()` cover `QColor` and rich text.
  - `pyside_gui/icons.py` holds the SVG icons. QtSvg can't parse `rgba()`, so icons use hex plus
    `stroke-opacity`.
- **Web side:**
  - Vditor lives in `pyside_gui/resources/vditor/`.
  - The conversation page loads Lute, Vditor and the en_US i18n, then runs `prepareMarkdown()`
    before `Lute.Md2HTML`, followed by `codeRender` / `highlightRender` / `mathRender`.
- **Page loading:** both web views now load through `setHtml(with_theme(...), baseUrl)`. The
  notepad's navigation guard therefore accepts the initial `data:` navigation (but not link
  clicks).
- **Not done yet:**
  - mermaid;
  - the `files` block;
  - the formatting prompt;
  - "talk while you work";
  - the selection menu and mini chat;
  - permission modes and approval cards;
  - the context meter;
  - long-paste cards;
  - typing while the agent runs.

## Open questions (to discuss)

The non-UI items (§2.1–2.5) come next, starting with mermaid and the formatting prompt.
