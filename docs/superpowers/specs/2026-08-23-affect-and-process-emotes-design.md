# Affect and Process-State Emotes Design

**Date:** 2026-08-23 | **Status:** Approved in design review
**Scope:** DAGI core, tool registry, session persistence, callbacks, and PySide/TUI renderers

## Summary

DAGI will replace its free-form `emote` tool with two independent expression
channels:

1. A model-controlled, three-dimensional affect channel using the standard
   valence-arousal-dominance (VAD) model.
2. An automatic process-state channel derived from the agent's real lifecycle,
   such as `idle`, `thinking`, or `tool:read`.

Each channel resolves to one GIF, PNG, JPEG, or JPG asset. The PySide right
sidebar alternates the latest VAD and process-state assets every three seconds.
Core state is renderer-independent; only PySide owns the presentation timer.

## Goals

- Give DAGI a persistent, model-visible affect vector with three VAD axes.
- Let DAGI change affect only through relative tool deltas.
- Make affect drift naturally between tool adjustments.
- Derive process state automatically without model involvement.
- Resolve affect and process state through user-maintained image libraries.
- Fall back safely to the existing `.dagi/emotes/default.md` display.

## Non-Goals

- Generating or bundling production artwork.
- Inferring VAD coordinates from filenames or image contents.
- Letting the model choose or override process-state images.

## Approved User-Facing Behavior

### Affect

- The axes are valence, arousal, and dominance.
- Each coordinate is clamped to `[-1.0, +1.0]`.
- A new conversation samples each baseline coordinate independently and
  uniformly from `[-0.3, +0.3]`.
- Affect persists for the conversation and is restored with it.
- The model changes affect through relative deltas only.
- The current vector and selected VAD emote appear in the ephemeral session
  context appended to each model request.
- The selected VAD emote is the nearest library vector, stabilized with
  hysteresis.

### Process state

- Process state is derived from authoritative agent lifecycle events.
- Model processing and answer streaming both use the single `thinking` state.
- Tool execution uses `tool:<registered-tool-name>`.
- Process state is not model-controlled and is not restored from old sessions.

### PySide display

- The sidebar shows one large expression asset.
- It starts with the VAD asset and alternates channels every 3,000 ms.
- Incoming state changes do not reset or delay the timer.
- The VAD interval shows the emote ID and compact VAD coordinates.
- The process interval shows the process-state key.
- GIFs animate; static images preserve aspect ratio.

## Architecture

### Channel separation

The feature has two semantic controllers and one presentation component:

```text
AgentLoop lifecycle ----> ProcessStateController ----> process snapshot
        |
adjust_affect tool -----> AffectController ----------> affect snapshot
        |                       |
        |                       +----> session-context tail
        |
        +---- callbacks -> Qt bridge -> ExpressionWidget
                                           |
                                           +---- strict 3 s rotation
```

The controllers do not import Qt. They publish immutable snapshots containing
semantic state and a resolved asset reference. PySide stores the latest
snapshot from each channel and decides which one is visible.

### Session ownership

One `AffectController` belongs to the root conversation session. It must not
belong to an individual `AgentLoop` or tool registry because PySide rebuilds
those objects between user turns.

The root `SessionTracker` carries the controller reference while a conversation
is live. The root session tracker JSONL records affect changes so session
restoration can seed a new controller from the previous conversation state.
Subagents do not receive or mutate the root affect controller.

`ProcessStateController` belongs to the active root runtime. It begins at
`idle` whenever a conversation is created or restored.

## Core Data Model

### AffectVector

An immutable value object:

```text
AffectVector(
    valence: float,
    arousal: float,
    dominance: float,
)
```

Construction rejects non-finite values. Public adjustment operations clamp
each resulting axis to `[-1.0, +1.0]`.

### Asset references

Controllers return one of two asset variants:

```text
ImageAsset(id: str, path: Path)
TextFallback(path: Path, reason: str)
```

The normal core path validates image metadata and file paths. Image decoding
remains a renderer responsibility, so a renderer can replace a failed
`ImageAsset` with the same `TextFallback` contract.

### AffectSnapshot

```text
AffectSnapshot(
    baseline: AffectVector,
    current: AffectVector,
    emote_id: str,
    asset: ImageAsset | TextFallback,
    reason: "init" | "adjust" | "drift" | "restore",
)
```

### ProcessSnapshot

```text
ProcessSnapshot(
    state: str,
    asset: ImageAsset | TextFallback,
)
```

## Affect Behavior

### Initialization

Production uses an unseeded random generator. Tests inject a seeded generator.
The initial baseline and current vector are identical. Initialization selects
the nearest valid VAD emote and emits an `init` snapshot.

### Replacement tool

The old provider-visible `emote(text)` schema is removed. The replacement is:

```text
adjust_affect(
    valence_delta: number,
    arousal_delta: number,
    dominance_delta: number,
)
```

All three parameters are required and constrained to `[-1.0, +1.0]`. The model
passes zero for an unchanged axis. The tool:

1. Adds each delta to the current vector.
2. Clamps the result.
3. Resolves the VAD asset with hysteresis.
4. Persists and publishes the new snapshot.
5. Returns the prior vector, requested delta, resulting vector, and emote ID.

The tool is available to the main agent in normal mode wherever the old
`emote` tool was available. It is not available to subagents or in plan mode.

### Natural drift

Drift occurs after each completed agent iteration that continues to another
iteration. It does not occur before the first request, while idle, or while
paused.

For each axis:

```text
drift_delta = 0.05 * (baseline - current) + uniform(-0.02, +0.02)
```

The controller applies and clamps all three deltas, resolves the VAD asset,
persists an `affect_drift` record, and publishes a `drift` snapshot.

The default coefficients are configurable:

```yaml
affect:
  drift_pull: 0.05
  drift_noise: 0.02
  emote_hysteresis: 0.05
```

Configuration validation requires non-negative finite values. The drift-noise
value may not exceed `1.0`.

### Nearest-emote selection

The VAD library uses ordinary Euclidean distance with equal weight on all
axes. Squared distance may be used internally because it preserves ordering.

The current emote remains selected until another emote's Euclidean distance is
at least `0.05` smaller. A missing or invalid current asset bypasses hysteresis
and resolves to the text fallback.

### Model context

The existing `## Session Context` board receives one compact line:

```text
Affect: V=+0.42 A=+0.31 D=+0.18 | emote=focused
```

The board remains an ephemeral final system message. Affect does not enter the
stable system prefix or the derived conversation message surface.

## Affect Persistence

The root session tracker JSONL gains these record types:

```text
affect_init    baseline + current vector + emote ID
affect_adjust  prior vector + requested delta + result + emote ID
affect_drift   prior vector + applied delta + result + emote ID
```

Records include the normal UTC timestamp. Ordinary PySide turns reuse the live
controller through the root tracker. Restoring a historical conversation reads
the last valid affect record and original baseline from that session log.

Legacy sessions without affect records receive a new randomized baseline.
Malformed historical affect records are reported once and also receive a new
randomized baseline; they do not prevent conversation restoration.

## Automatic Process-State Behavior

`AgentLoop` updates process state at authoritative lifecycle boundaries before
it notifies external callbacks:

```text
waiting for user input       -> idle
starting/model API work      -> thinking
assistant answer streaming  -> thinking
tool starts                 -> tool:<tool-name>
tool ends                   -> thinking
turn completes              -> idle
pause                       -> paused
fatal loop failure          -> error
resume or retry             -> thinking
```

An ordinary tool result that contains an error does not by itself make the
controller sticky in `error`; after that tool ends, the loop returns to
`thinking`. `paused` and fatal `error` remain active until an explicit resume,
retry, or new turn transition.

Subagent dispatch is represented by the registered top-level subagent tool
name. Nested child events do not replace the root process state in the first
version.

State asset lookup follows this chain:

```text
tool:read -> tool -> thinking -> idle
```

For non-tool keys, an exact miss falls back to `idle`. A fallback key found
later in the chain is normal resolution, not a library error.

## Asset Libraries

Production artwork is user-supplied under two subfolders:

```text
.dagi/emotes/
|-- default.md
|-- states/
|   |-- manifest.yaml
|   |-- idle.gif
|   |-- thinking.gif
|   `-- ...
`-- vad/
    |-- manifest.yaml
    |-- focused.gif
    |-- calm.png
    `-- ...
```

Supported image suffixes are `.gif`, `.png`, `.jpg`, and `.jpeg`, matched
case-insensitively.

### VAD manifest

```yaml
version: 1
emotes:
  - id: focused
    file: focused.gif
    vad: [0.40, 0.50, 0.30]
  - id: calm
    file: calm.png
    vad: [0.30, -0.60, 0.20]
```

The loader validates:

- Manifest version and shape.
- At least one emote.
- Unique, non-empty IDs.
- Exactly three finite coordinates within `[-1.0, +1.0]`.
- Supported file suffixes.
- Existing regular files.
- Resolved asset paths contained by `.dagi/emotes/vad`.

### Process-state manifest

```yaml
version: 1
states:
  idle: idle.gif
  thinking: thinking.gif
  paused: paused.png
  error: error.png
  tool: working.gif
  "tool:read": reading.gif
  "tool:grep": searching.gif
  "tool:bash": terminal.gif
```

The loader applies the same path and suffix validation. `idle`, `thinking`,
and `tool` are required fallback keys.

### Universal fallback

Any manifest, mapping, lookup, missing-file, unsupported-format, unsafe-path,
or renderer decode error displays the UTF-8 contents of:

```text
.dagi/emotes/default.md
```

Whitespace and line breaks are preserved so the existing default remains:

```text
  █▀▄ ▄▀▄ ▄▀  █
  █▄▀ █▀█ ▀▄█ █

  (づ｡◕‿‿◕｡)づ
```

The underlying error is emitted once with its channel, operation, and path.
Repeated timer ticks do not repeat the same warning. If `default.md` is also
unreadable, the final built-in fallback is the literal text `DAGI`.

A malformed whole manifest makes every lookup in that channel return the text
fallback. An invalid individual asset returns the text fallback only when that
asset is selected; other validated assets remain usable.

## Callback Contract

The stale three-argument `on_emote` callback is removed. `AgentCallbacks`
receives two optional observer hooks:

```text
on_affect_changed(AffectSnapshot)
on_process_state_changed(ProcessSnapshot)
```

The PySide bridge relays each snapshot through its own object-valued Qt signal,
ensuring UI updates occur on the main thread. The TUI consumes the same
snapshots as text. Headless callbacks remain no-ops.

## PySide Expression Widget

The current top-sidebar emote label is replaced by a small dedicated
`ExpressionWidget`. It owns:

- The latest affect snapshot.
- The latest process snapshot.
- The currently visible channel.
- One 3,000 ms `QTimer`.
- At most one active `QMovie`.

The timer starts on the VAD channel. Each timeout flips channels exactly once.
Snapshot arrivals update stored content without restarting the timer. When an
asset changes, the widget stops and releases the old movie before constructing
the next display.

Images scale to the available width while preserving aspect ratio. GIFs play
automatically. The widget recalculates static-image scaling on resize. During
the VAD interval, the caption contains the emote ID and compact vector. During
the process interval, it contains the state key.

For a `TextFallback`, the image area becomes a monospaced, centered,
whitespace-preserving text label. Existing sidebar sections below the
expression widget remain unchanged.

## TUI and Headless Behavior

The TUI does not load or animate image data. It renders the latest VAD emote ID
and vector plus the latest process-state key as text. It does not run the
three-second alternation.

Headless execution maintains both semantic controllers and persistence but
does not render assets. Library failures still produce one actionable warning
and resolve through the fallback contract.

## Error Handling and Observability

- Invalid configuration fails fast with a field-specific configuration error.
- Library errors do not terminate the coding agent.
- Every distinct library error is reported once and returns `TextFallback`.
- Tool inputs outside their schema are rejected without changing affect.
- Controller mutation publishes only after the new state is internally valid.
- Callback failures do not roll back an already persisted affect mutation.
- Process transitions are idempotent; repeated identical states do not emit
  duplicate snapshots.

## Testing Strategy

### Affect unit tests

- Each randomized baseline coordinate remains within `[-0.3, +0.3]`.
- Relative adjustments and per-axis clamping are correct.
- Invalid and non-finite inputs do not mutate state.
- Seeded drift matches the mean-reverting formula.
- Drift does not run before the first request, while idle, or while paused.
- Hysteresis retains the current emote near a boundary and switches after the
  configured margin is exceeded.

### Library unit tests

- Valid manifests load GIF, PNG, JPG, and JPEG paths.
- Duplicate IDs, malformed vectors, unsupported suffixes, missing files, and
  escaping paths resolve through `default.md`.
- Process-state lookup follows exact and fallback resolution order.
- Manifest-wide failures disable only their own channel.
- A missing `default.md` produces the built-in `DAGI` fallback.

Tests create tiny temporary image fixtures and do not add production art.

### Session and loop tests

- Affect records are appended after initialization, adjustment, and drift.
- A live controller survives PySide `AgentLoop` reconstruction.
- Historical restoration uses the original baseline and latest current vector.
- Legacy and malformed session records initialize safely.
- The session-context board shows the latest vector and emote ID.
- Lifecycle boundaries publish the expected process state in order.
- Fatal error, pause, resume, tool start, and tool end transitions are covered.

### Tool and registry tests

- `emote` is absent and `adjust_affect` is present in normal main mode.
- The replacement schema requires all three bounded delta values.
- Tool output reports the prior vector, delta, result, and selected emote.
- Subagents and plan mode cannot invoke the affect tool.

### PySide tests

- Bridge signals carry snapshots across threads.
- The expression widget starts with VAD and alternates every 3,000 ms.
- Snapshot arrival does not reset the timer.
- Replacing a GIF stops the previous `QMovie`.
- Static images preserve aspect ratio after resize.
- Decode failures display the exact `default.md` content.
- Captions match the currently visible channel.

### Regression tests

- Existing token, context, plan, pause, streaming, and tool-card behavior is
  unchanged.
- No test invokes a real model or incurs LLM cost.

## Implementation Boundaries

Implementation should introduce focused core modules for affect values,
controllers, and asset-library parsing rather than growing `agent/loop.py` or
`pyside_gui/right_sidebar.py` beyond project limits. `AgentLoop` should contain
only lifecycle integration and dynamic-context formatting. The PySide sidebar
should compose the expression widget rather than own its media logic.

The implementation plan must identify the exact module split after checking
current file lengths and caller relationships. It must use TDD and preserve
the existing user-owned PySide styling changes already committed to `main`.
