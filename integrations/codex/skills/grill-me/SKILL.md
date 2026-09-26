---
name: grill-me
description: Grill the user relentlessly about a plan, decision, or idea. Use when the user wants to stress-test their thinking, or uses any 'grill' trigger phrases.
---

Interview the user relentlessly until you reach a shared understanding. Map this as a **design tree**: every decision branches into the decisions that hang off it.

Work the tree in **rounds**. The **frontier** is every decision whose prerequisites are already settled — the questions you can ask _now_ without guessing at answers not yet heard. Ask the whole frontier in one round: number each question and give your recommended answer. Then wait for answers before the next round.

Each question should be formatted like so:

```php-template
❓ **Q1** - **<question title>**: <question body, might be multiple paragraphs, including multiple choices>

➡️ <your recommended answer>
```

Each round reshapes the tree — settled decisions push the frontier outward and unblock dependent questions. Recompute the frontier and ask the next round. A question that depends on another question still open in this round belongs to a later round.

Find facts yourself. When a frontier question needs an environment fact, dispatch a sub-agent to find it rather than asking the user. Do not block on it: only questions downstream of the running exploration wait; ask the rest of the frontier now. Decisions belong to the user — put each decision to them and wait.

The session is done when the frontier is empty: every branch visited, nothing left silently assumed. Do not act until the user confirms shared understanding.

## Return to caller

Summarize the agreed scope, decisions, alternatives tested, unresolved issues, and concrete
next actions. When used by `enter-workflow`, return that summary to the owner; it selects
the next stage and obtains any required approval. Preserve valid decisions on continuation.
When invoked standalone, return the summary without starting planning or implementation.
