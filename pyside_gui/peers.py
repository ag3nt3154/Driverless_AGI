"""Text formats and selection rules for model-spawned peer agents (no Qt)."""
from __future__ import annotations

MAX_POST = 700
HEAD = 500
TAGS = ("done", "max-continuations", "error")


def task_post(peer: str, task: str) -> tuple[str, bool]:
    """The ``[task]`` post for ``peer``; ``attach`` is True if the task was cut."""
    text = f"@{peer} [task] {task}"
    if len(text) <= MAX_POST:
        return text, False
    return f"@{peer} [task] {task[:HEAD]}… (full task in task.md)", True


def report_post(spawner: str, tag: str, body: str) -> str:
    """The ``[done|max-continuations|error]`` report post for ``spawner``."""
    if tag not in TAGS:
        raise ValueError(f"unknown report tag: {tag!r}")
    body = body.strip() or "(no text)"
    head = body if len(body) <= HEAD else body[:HEAD] + "…"
    return f"@{spawner} [{tag}] {head}"[:MAX_POST]  # the full text is attached


def peer_footer(spawner: str) -> str:
    """Wake-message footer for a peer woken by its spawner: the handoff is posted for it."""
    return (
        f"You are a peer agent spawned by @{spawner}. When this work is complete, call "
        f"write_handoff with your report: it is posted to @{spawner} automatically as [done] "
        "with the full report attached. Do not post your result, progress or acknowledgements "
        f"with post_board, and do not @mention @{spawner}: a mention starts a new turn for it. "
        "Use fetch_attachment for any attachment you need (task.md holds a task that was cut)."
    )


def spawner_footer(peer: str) -> str:
    """Wake-message footer for a spawner woken by its peer's automatic report."""
    return (
        f"This is the automatic report of your peer @{peer}; use fetch_attachment for the full "
        f"handoff. Do not reply on the board or @mention @{peer} unless you give it new work: "
        "a mention starts a new turn for it."
    )


def pick_eviction(peers):
    """The eligible idle+done peer with the oldest ``last_active``, or None."""
    eligible = [p for p in peers if p.state == "idle" and p.last_outcome == "done"]
    if not eligible:
        return None
    return min(eligible, key=lambda p: p.last_active)


def _word(state: str) -> str:
    return "waiting for you" if state == "waiting" else state


def limit_error(peers, limit: int) -> str:
    """The error text shown when the spawn limit is hit and nothing can be closed."""
    listed = ", ".join(f"{p.handle} ({_word(p.state)})" for p in peers)
    return (
        f"Error: {limit} spawned agents are open and none can be closed: {listed}. "
        "Wait for a [done] message, close one in the Agents view, "
        "or post a follow-up to an idle one."
    )


def active_notice(peers) -> str | None:
    """A chat line listing peers still ``running``/``waiting``, or None if none are."""
    active = [p for p in peers if p.state in ("running", "waiting")]
    if not active:
        return None
    items = ", ".join(f"{p.handle} ({_word(p.state)})" for p in active)
    return f"⏹ Stopped. Peers still active: {items}. See the Agents view."
