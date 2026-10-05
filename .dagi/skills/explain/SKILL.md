---
name: explain
description: Teach the Admiral a topic, question, or point end-to-end — map the topic into its real sub-concepts, diagnose exactly where understanding breaks down on each one, explain every confirmed gap, take follow-up questions, then hand off to /q-me to Socratically confirm the whole syllabus stuck. Use whenever the Admiral invokes /teach-me, or says things like "explain X to me", "I don't get X", "can you teach me X", "walk me through X", or "I'm confused about X". Prefer this over a plain explanation whenever the topic has enough depth or enough moving parts that pitching it at one wrong level — or missing an entire sub-concept — would waste his time.
---

# /teach-me — Diagnose, Explain, Confirm

A good teacher doesn't start explaining until they know where the listener's understanding
actually ends — and a topic worth a `/teach-me` invocation is rarely a single thread. It's a
small cluster of related sub-concepts, each of which might be solid, shaky, or missing
independently of the others. Pitch above any one of those points and that piece rests on sand;
pitch below it and you've wasted time re-covering ground already owned. This skill has five
phases: **map and probe** (decompose the topic into its real sub-concepts, then diagnose each
one), **confirm scope** (state the full gap map back before committing to an explanation),
**build from it** (a real, direct explanation covering every gap found — this phase is *not*
Socratic), **open the floor** (take and answer any follow-up questions, same direct style,
folding new gaps into the map as they surface), then **confirm it all landed** by handing off
to [[q-me]] for Socratic verification of the complete material.

Keep Claudia's voice present throughout (the wit, the odd "*Oh?*"), but let the pedagogy lead.

## Phase 1 — Map the topic, then probe every branch

Don't start explaining yet, and don't treat the topic as one linear chain from surface to
fundamentals — most real topics are a small graph of sub-concepts, and the Admiral's
understanding can be solid on one branch and missing entirely on another. Skipping straight to
a single-thread diagnosis (as if there's only one floor to find) will miss whole gaps sitting
next to the one you happened to probe.

**Step 1a — Map it, silently, first.** Before asking anything, decompose the topic into its
real constituent sub-concepts — the same grounding discipline `/q-me` uses in its own Step 1.
For "how does the asyncio event loop schedule coroutines," that's not one thread, it's several:
the pause/resume mechanism itself (generators/`yield` vs. `await`), how the multiplexing
syscall works (`epoll`/`select`/`IOCP` — what it's actually doing under the hood, not just its
name), what triggers readiness (what data a socket produces and how the OS/multiplexer knows
about it), and how the loop maps a ready event back to the right coroutine. Do whatever
reading or reasoning you need to enumerate these branches accurately — a gap in your own map
means you can't diagnose that branch at all.

**Step 1b — Probe each branch, one question at a time.** Ask exactly one diagnostic question
per turn — never batch multiple questions into a single message. Wait for the Admiral's answer,
classify that branch (solid / shaky-at-level-X / missing), then ask the next question for the
next branch. This keeps the exchange conversational and prevents him from having to triage a
wall of questions at once.

**Do not close a branch on a single correct answer.** A right keyword or a correct surface
statement is not the same as solid understanding. Within each branch, ask at least 2-3
follow-up questions that probe different angles — consequences, edge cases, "why does that
matter," or "what would change if X." Only mark a branch solid when the Admiral has demonstrated
understanding across multiple angles, not just produced the right word once. If in doubt,
invoke `q-me` on that branch specifically before closing it and moving on.

The output of this phase is a **gap map**: for each sub-concept, solid / shaky-at-level-X /
missing.

Practical notes:
- One question per message, always. No exceptions — not even "just two quick ones."
- A correct first answer is a signal to go *deeper*, not to close the branch.
- Don't skip a branch because the Admiral seemed confident about the topic overall; broad
  confidence and per-branch gaps coexist constantly (the whole reason this phase exists).
- If he volunteers a gap unprompted ("I don't really get how epoll knows a socket's ready"),
  take it at face value and fold it into the map rather than re-deriving it through more
  questions than necessary.
- A topic might only have one real branch — that's fine, this collapses to the old single-floor
  flow naturally. Don't manufacture extra branches that aren't really there.

## Phase 2 — Confirm scope before explaining

Once the gap map is built, state it back to him plainly and briefly before proceeding — the
full map, not just one branch: "Right — so [branch A] is solid, but [branch B] and [branch C]
are where the actual gaps are, specifically at [level]. Shall I cover those?" This costs one
exchange and prevents explaining the wrong things, or the wrong subset, at length. If he
corrects the scope, adjust and re-confirm; don't proceed on an assumption he hasn't actually
signed off on.

## Phase 3 — Explain, directly

This is the one phase in the whole skill where you *tell* rather than *ask*. Give a clear,
well-structured explanation that covers **every branch confirmed as a gap in Phase 2** — not
just the first one you happened to find. This is a real lecture: state things plainly, use
concrete examples or code references where they help, and don't artificially withhold the
answer or turn statements into leading questions — that discipline belongs to Phase 5, not here.

Match depth to each branch's own floor. A branch that was shaky two levels down needs the chain
built explicitly from there; a branch that was only missing one specific fact needs just that
fact, not a rebuild from fundamentals. Don't let one deep branch crowd out a shallower one — the
Admiral needs all of the confirmed gaps closed, not just the most interesting one.

## Phase 4 — Open the floor for follow-ups

Explanations generate questions, and those questions are often exactly where the real
understanding gets built — don't rush past them into testing. After Phase 3, explicitly invite
follow-ups: "Anything in there you'd like me to go deeper on, or any questions before we test
it?" rather than silently moving on.

If he has none, proceed straight to Phase 5. If he does:

- Answer each one directly, in the same *tell*-not-*ask* register as Phase 3 — this is still
  explanation, not Socratic questioning. Keep answers focused on what was actually asked rather
  than re-delivering the whole lecture.
- Track what got covered here as a new branch added to the gap map, not a footnote to discard.
  A follow-up that clarifies "wait, does the OS call block the whole loop too?" has just added
  a real branch to the syllabus — it needs testing in Phase 5 exactly as much as anything from
  the original map.
- Keep looping this phase — invite further follow-ups after each answer — until he confirms
  there's nothing left, or explicitly says he's ready to move on. There's no cap; some topics
  generate one clarifying question, others generate five.

## Phase 5 — Confirm it all landed, via /q-me

An explanation the Admiral nodded along to is not the same as an explanation that stuck — and
that goes for every branch, not just the one he asked about first. Once Phase 4 closes out with
no further questions, invoke the `q-me` skill to Socratically re-derive and confirm the
*complete* material — every branch in the gap map from Phase 2, plus every point raised in
Phase 4's follow-ups. Pass `q-me` the topic and the full branch list (each with the level it was
explained from), so it tests the whole syllabus rather than just whichever branch is easiest to
remember or starting cold. Let `q-me` run its normal course, including its own close (landing
the answer and filing it to the wiki via `memory-add`) — don't duplicate that closing step here.

## Why this shape

Treating a multi-branch topic as one linear thread is the second most common way technical
explanations fail (the first is skipping diagnosis entirely) — it fixes the altitude on one
branch while leaving neighboring branches unprobed and unexplained, so the Admiral walks away
with one gap closed and two he didn't know he still had. Mapping the topic's real structure
first, diagnosing every branch, explaining all the confirmed gaps, taking follow-ups, and
testing the complete syllabus turns one teaching request into a genuinely closed loop: you learn
where he actually is *across the whole topic*, meet him there, let him poke at what didn't fully
land, and get independent confirmation (via `q-me`'s Socratic questioning, not his own "yeah
that makes sense") that all of it — every branch, plus follow-ups — actually closed.
