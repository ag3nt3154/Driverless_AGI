---
title: 'Board @-mentions only count with the exact full handle (@slug_xxxxxxxx)'
description: 'The board silently drops @worker, @worker-1a2b3c4d and capitalized forms; post_board now warns and read_board lists online handles.'
tags: [board, mentions, '@-mention', _MENTION_RE, extract_mentions, post_board, read_board, spawned-agents, handle]
updated: 2026-10-14
---
## Symptom
In the GUI, the main agent posted to a spawned agent by name and the worker never woke up.
The worker only saw the messages because it was running a loop that read the board every 30 seconds.

## Cause
`services/message_board/store.py` `_MENTION_RE` records a mention only for an exact handle in the form
`@<slug>_<8 lowercase hex>`, or for `@board-admin`. The board stores the post but silently
drops `@worker`, `@worker-1a2b3c4d` (hyphen) and `@Worker_1a2b3c4d` (capital letter). `post_board` also replied
`Posted #N.` with no warning, and agents were never told the other agents' handles.
The GUI delivery path (`BoardController._on_post` -> `AgentsController.on_board_mention` ->
`AgentSession.deliver_mention`) was correct.

## Fix (2026-10-14, commit 2027e1f, branch task/board-mention-handles)
- `post_board` compares the `@`-tokens in the text with the `post["mentions"]` the server sends back.
  - Dropped tokens: a warning that says no one was notified, followed by the online members and an example handle.
  - Recorded handles that aren't online: a softer note.
- `read_board` output now begins with `You are <handle>. Online members: ...`. The list is capped at 10 entries.
- The `post_board` description and `.dagi/prompts/main/main_system.md` say to use the full handle.

## Gotchas
- The GUI delivers a mention by handle whether or not that member is online. A correctly written handle
  of an offline or just-spawned agent still reaches it, so don't call that case "not notified".
- `board-admin` is a registered member and appears in the online list. Never use it as the example handle.

## Idea (not done)
Have the server turn a bare `@slug` into the full handle when exactly one member has that slug.
This is related to `todo-board-at-all-mention.md`.
