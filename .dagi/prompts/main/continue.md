This is an automated message from the coding harness.

You MUST call `write_handoff` or `ask_user` to end your turn.

Use **`ask_user`** if you need the user to answer a question before continuing.
Use **`write_handoff`** for everything else:
- You have completed your task.
- You are having a casual conversation or responding to a greeting.
- You have produced output and have nothing more to do until the user replies.

Pass your final response text as the `content` argument to `write_handoff`.
Do NOT write plain text before calling `write_handoff` — put your entire response in `content`.
Do NOT call `write_handoff` before `ask_user` — `ask_user` pauses the turn on its own.

If NONE of the above apply and you still have active work remaining, resume exactly where you left off — do not repeat what you already did.
