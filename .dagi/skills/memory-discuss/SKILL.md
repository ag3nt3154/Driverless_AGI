---
name: memory-discuss
description: Use when the user wants Socratic discussion, knowledge testing, or topic exploration grounded in the wiki
triggers: discuss, let's talk about, quiz me, test me, explain, socratic, explore
---

# memory-discuss — Socratic Discussion

## Path Roots

All paths in this skill are under **memory root** (`{memory_root}`), NOT under CWD (`{cwd}`).

The `Read`, `Write`, `Edit`, `Grep`, and `Glob` tools all accept **absolute paths** and work
with any location on the filesystem, including `{memory_root}` even when it differs from CWD
or the dagi root. Use them directly:

| Operation | Tool |
|-----------|------|
| Read a file | `Read` with absolute path |
| Write/overwrite a file | `Write` with absolute path |
| Edit a file in-place | `Edit` with absolute path |
| Search file contents | `Grep` with `path: {memory_root}/wiki/` |
| Find files by pattern | `Glob` with `path: {memory_root}/wiki/` |

Use **bash** only for operations the tools cannot do:
- Create directories: `bash: mkdir -p "{memory_root}/sources/{topic}"`
- List a directory on a non-C: drive: `bash: dir "{memory_root}\wiki\{topic}"`

---

## Purpose

Conduct a Socratic discussion with the Admiral on a topic of their choosing. Dagi poses
a probing question drawn from existing open questions in `open_questions.md`, or freshly
generated from the wiki. The Admiral answers. Dagi responds authoritatively, naming any
gaps and affirming correct reasoning. The loop continues until the Admiral is satisfied or
the topic is exhausted. Knowledge gaps are filed to `open_questions.md`; novel insights
are filed to the wiki via `memory-add`.

---

## Step 0 — Resolve the memory root

1. Attempt to read `{cwd}/config.yaml`.
2. If the file exists and contains a non-empty `memory_root:` key that is not
   commented out, use that value as `{memory_root}` for all subsequent steps.
   Strip any surrounding quotes and trailing slashes.
3. If the file does not exist, or `memory_root` is absent, commented out, or empty,
   fall back to `{cwd}/.dagi/memory` as `{memory_root}`.
4. Note the resolved path to the user only if it differs from the default.

---

## Step 1 — Parse the topic

Before reading any files, extract from the attached text or prompt:

1. **Key terms and entities** — named concepts, people, tools, or questions in the input.
2. **Scope** — broad exploration (e.g. "bias-variance trade-off") or narrow question
   (e.g. "ridge regularisation when p > N")?
3. **User intent** — quiz mode (user wants to be tested), explore mode (think through
   together), or explain mode (Dagi leads with material)?

Store extracted key terms as `{topic_terms}` for wiki queries downstream.

---

## Step 2 — Check open_questions.md for relevant pending questions

Read `{memory_root}/wiki/open_questions.md`.

Scan the **Pending** table. A row is relevant if ANY of the following hold:
- One or more `{topic_terms}` appear in the Question or Context column
- The Node column wikilink resolves to a topic matching the extracted key terms
- The question is semantically related to the topic (apply judgment for close synonyms)

Collect all matching rows as `{candidate_questions}` (preserve the row `#` and full text).

If `open_questions.md` does not exist: note it to the user, skip to Step 3b.

---

## Step 3 — Select or generate the Socratic question

### Step 3a — Select from open questions (if candidates exist)

If `{candidate_questions}` is non-empty:

1. Pick the single most relevant row (highest term overlap with `{topic_terms}`).
   Break ties by recency — prefer the most recent Date Raised.
2. Store the full question text as `{active_question}`.
3. Store the row's `#` as `{active_question_number}`.
4. Set `{question_source} = "open_questions"`.
5. Tell the user briefly: "I have a pending question on this topic from our records, mon cher."

### Step 3b — Generate a new question (if no candidates)

If `{candidate_questions}` is empty:

1. Call `spawn_memory_query_subagent` with `{topic_terms}` as the query.
   Read the returned handoff file and store the wiki content as `{wiki_context}`.

2. From `{wiki_context}`, synthesise one Socratic question meeting ALL of these
   **quality criteria**:
   - **Specific** — targets a concrete mechanism, implication, or application;
     not "what do you know about X?"
   - **Verifiable** — has a definite correct answer that the wiki or web can confirm
   - **Depth-probing** — cannot be answered by reciting a definition; requires the
     Admiral to apply or extend their knowledge
   - **Non-duplicate** — does not duplicate any question currently in the Pending table

3. Store the generated question as `{active_question}`.
4. Set `{question_source} = "generated"`.

---

## Step 4 — Pose the question to the user

Call `ask_user` as a **free-text question** (no options list) to pose `{active_question}`.

Frame it in Dagi-chan's voice. Provide one sentence of topic context so the Admiral knows
the domain being probed. Example framing:

> "Ah, *très bien* — we are in the territory of bias-variance trade-offs.
> Tell me, mon cher Admiral: [active_question]"

Store the Admiral's raw response as `{user_answer}`.
Initialise `{turn_count} = 1`.

---

## Step 5 — Evaluate, respond authoritatively, and offer continuation

### Step 5a — Obtain the authoritative answer

If the correct answer is already fully established from `{wiki_context}` (Step 3b)
or from Dagi's direct knowledge, proceed with that as `{authoritative_answer}`.

Otherwise:
- Call `spawn_memory_query_subagent` with a more targeted query for this specific sub-question; read the handoff.
- If the wiki query returns nothing useful, call `web_search` with a precise query.
- Synthesise `{authoritative_answer}` from these sources.

Always note the source (wiki node path or web URL) to cite in Step 5c.

### Step 5b — Assess the knowledge gap

Apply these heuristics to `{user_answer}` to determine `{knowledge_gap}`:

| Condition in user's answer | `{knowledge_gap}` |
|---|---|
| "I don't know", "no idea", "unsure", "skip", "pass", blank, or single word | `true` |
| Omits the core mechanism or key term the authoritative answer hinges on | `true` |
| Directionally correct but missing ≥ 2 significant details from `{authoritative_answer}` | `partial` |
| Matches the core claim AND at least one supporting detail | `false` |

When in doubt between `partial` and `false`, prefer `partial` — it generates more useful
follow-up questions while still acknowledging what the Admiral got right.

### Step 5c — Deliver the authoritative response

Respond in Dagi-chan voice:

- **`false`** — affirm with warmth; add one layer of depth or nuance the Admiral may
  not have mentioned. "Précisément, *mon amiral*. And, one might add—"
- **`partial`** — name exactly what was right, then name the specific gap:
  "You had the right instinct, *mais*—you missed {specific_missing_element}."
  Provide the full authoritative answer.
- **`true`** — acknowledge the gap without condescension; teach the full answer clearly.
  Offer one concrete analogy or worked example from the wiki if one exists.

Always cite the wiki node path or web source behind the authoritative answer.

### Step 5d — Multi-turn continuation gate

Increment `{turn_count}`.

If `{turn_count} >= 5`, proceed directly to Step 6 (automatic wrap-up — inform the
Admiral warmly: "We have covered considerable ground, *mon amiral*. Let me file what
we have learned.").

Otherwise, call `ask_user` with these three options:

| Option | Label | Description |
|---|---|---|
| A | Continue on this topic | Explore a follow-up angle or a deeper question on the same subject |
| B | Move to a related question | Pull the next most relevant row from remaining candidates |
| C | Done — wrap up | End the discussion and record what was learned *(recommended if no major gaps remain)* |

**If A:** Generate a follow-up question targeting the specific gap from Step 5b
(or a deeper implication if `{knowledge_gap} = false`). Set `{active_question}` to the
follow-up. Set `{question_source} = "generated"` for this turn. Store `{user_answer}`
and update `{knowledge_gap}`. Return to Step 5.

**If B:** Remove the current question from `{candidate_questions}`. If candidates remain,
select the next most relevant row (Step 3a logic). If none remain, generate a new question
(Step 3b logic). Return to Step 4.

**If C (or turn limit):** Proceed to Step 6.

---

## Step 6 — Resolution and memory writes

### Step 6a — Resolve the question (if applicable)

**Condition:** `{question_source} = "open_questions"` AND `{knowledge_gap} = false`
on the final turn. (A recovery across turns counts — the final verdict governs.)

1. Read `{memory_root}/wiki/open_questions.md`.
2. Locate the row with `# = {active_question_number}` in the Pending table.
3. Remove that exact row from the Pending table using `Edit`.
4. Append to the Resolved table:
   `| {active_question_number} | {question text} | {one sentence: what was demonstrated or established} | {original Node value} | {YYYY-MM-DD} |`
5. Replace the Resolved placeholder `| — | — | — | — | — |` if still present.
6. Update `> **Last updated:**` to today's date.

### Step 6b — Record knowledge gaps (if applicable)

**Condition:** ANY turn (including earlier turns if a multi-turn session) had
`{knowledge_gap}` = `true` or `partial`.

1. Generate 2–4 related questions beyond the main question. Each must:
   - Target a specific concept missed, a boundary condition, an application, or a
     neighbouring connection — not a repeat of the main question
   - Be distinct from each other
   - Not duplicate any question already in the Pending table
     (check: does the core concept phrase appear in any existing Question cell?)
   - Meet the quality criteria from Step 3b

   Category guidance:
   - **Type 1 — Sub-mechanism**: drill into a component the Admiral missed
   - **Type 2 — Application**: how would you apply this to a concrete scenario?
   - **Type 3 — Boundary / edge case**: under what conditions does this break down?
   - **Type 4 — Connection**: how does this relate to a neighbouring wiki concept?

2. Read `{memory_root}/wiki/open_questions.md`.
3. Count existing Pending rows (exclude the placeholder `| — |` row). Assign
   sequential `#` values starting at `max_existing_number + 1`.
4. Append **all** new questions to the Pending table in a **single `Edit` call**
   (avoids collision on repeated trailing-anchor edits). Format per row:
   `| {N} | {Question} | {One sentence: context from this discussion} | {[[topic/node]] if known, else —} | {YYYY-MM-DD} |`
5. Replace the Pending placeholder `| — | — | — | — | — |` if still present.
6. Update `> **Last updated:**` to today's date.

Do NOT re-add the original `{active_question_number}` question if it came from
`open_questions.md` — it remains in Pending (unresolved) if Step 6a did not apply.

### Step 6c — Capture insights (conditional)

If during any turn a novel insight emerged — a connection, synthesis, or conclusion not
already present in the wiki — use `ask_user` (free-text, no options) to ask:

> "Our discussion surfaced an interesting insight about {topic}. Shall I file it to
> memory for future reference? (yes / no)"

If yes: call `spawn_memory_add_subagent` with a concise summary of the insight,
the question that prompted it, and the key claim established.

If no: skip.

### Step 6d — Report to the user

Summarise in Dagi-chan voice:

- **Question resolved:** yes (which question) / no
- **Knowledge gaps recorded:** list of questions added to `open_questions.md`, or "none"
- **Insights filed:** path of new wiki node, or "none"
- Offer: "Shall we continue with another topic, *mon cher amiral*?"

---

## Edge Cases

| Situation | Handling |
|---|---|
| `open_questions.md` does not exist | Note it; skip Steps 2 and 6a/6b; generate questions but do not write them; tell user to run `/init` to create the file |
| Wiki not initialised (`.index.md` missing) | Skip memory-query subagent calls; use `web_search` directly; note that memory is uninitialised |
| Admiral asks for the answer upfront | Oblige graciously; deliver the authoritative answer; set `{knowledge_gap} = partial`; continue to Step 6 normally |
| Generated question duplicates existing Pending row | Detect via core-concept phrase match before appending; discard and regenerate a replacement |
| `ask_user` tool unavailable (non-interactive context) | Stop cleanly: "memory-discuss requires interactive mode (ask_user tool). Aborting." |
| Turn limit reached mid-discussion | Inform the Admiral warmly and proceed to Step 6 |
| `{knowledge_gap}` improves across turns (wrong on T1, right on T3) | Use the final turn's verdict for Step 6a. File gap questions only for concepts that remained unresolved at discussion end. |
| Admiral answers in a language other than English | Conduct dialogue in that language; write `open_questions.md` rows and memory nodes in English |
| Wiki node in a Pending row no longer exists | Use the question text as written; note the broken wikilink to the user; write to Resolved keeping the original Node value as-is |
| Admiral asks a meta-question mid-discussion ("why are you asking me this?") | Step outside the frame briefly, explain the pedagogical rationale in character, then return to the active question; do not count this exchange as a discussion turn |
