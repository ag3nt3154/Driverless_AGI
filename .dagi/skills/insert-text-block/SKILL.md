---
name: insert-text-block
description: Use when a document contains [bracketed] markers — prose blocks to insert, reference material that should replace overlapping existing text, or editorial comments to apply. DAGI scans all markers, presents a cohesion plan for user approval, then implements edits that make the result flow smoothly.
---

# Insert Text Block

A skill for resolving `[bracketed]` markers in a document — either inserting prose blocks or applying editorial comments — while preserving narrative cohesion and stylistic consistency throughout.

## Overview

Authors often draft documents with three kinds of `[...]` placeholders:

1. **Text blocks** — raw prose fragments the author wants woven into the document (e.g., `[She hesitated at the door, breath held tight.]`)
2. **Reference blocks** — prose fragments whose content substantially overlaps with nearby existing text, signalling that the bracketed version is the authoritative source and should replace the current text after being adapted to match the document's style
3. **Editorial comments** — instructions directing changes to surrounding text (e.g., `[transition needed here]`, `[cut this to one sentence]`, `[make this paragraph more formal]`)

This skill handles all three. The critical constraint is that every edit must leave the surrounding text feeling like it was always there — no seams, no tonal inconsistency, no broken rhythm.

---

## Reference Block Mandate

> **The user has already read both the original text and the reference block. The presence of a reference block is an explicit instruction: use this version, not the original.**

This is non-negotiable and applies regardless of:
- Whether the original text appears to say the same thing
- Whether the original text is more polished, cleaner, or shorter
- Whether the reference block was previously derived from the original
- Whether the differences between them seem minor

**The reference block is the base. The neighbouring document text adapts to it — not the other way around.**

When a REFERENCE_BLOCK is encountered, the workflow is:
1. Treat the reference block content as the starting point for the final passage
2. Edit the reference block as needed — wording, structure, and depth may all change — so that it fits the document well
3. Rewrite neighbouring sentences so the adapted reference block fits naturally into them
4. The original overlapping text is removed entirely — it has no authority over the final result

**Rationalizations to reject outright:**

| Rationalization | Why it is wrong |
|---|---|
| "The original already says this, so I'll keep it" | The user chose the reference block over the original. Keep the reference. |
| "They're nearly identical — I'll use the original phrasing" | Even near-identical text has different word choices and emphasis. The reference version is the one the user wants. |
| "I'll blend the best parts of both" | Blending is not what was asked. The reference block is the base; the original is discarded. |
| "The original is clearer / better written" | Irrelevant. The user has made the decision. Implement it. |
| "The reference block was probably derived from the original anyway" | Irrelevant. The current bracketed version is the user's preferred state. |

---

## Phase 1: Scan and Classify

Read the entire document. Extract every `[...]` occurrence and classify it.

### Classification Rules

| Type | Signals | Examples |
|---|---|---|
| **Text block** | Reads as prose; no imperative verb; no substantial overlap with nearby text | `[The rain had not let up since Tuesday.]` |
| **Reference block** | Reads as prose AND the same subject matter, information, or narrative beat already appears in the surrounding paragraph or adjacent paragraphs | `[The treaty was signed on 14 March 1847, ceding the northern territories.]` placed near an existing sentence about the same treaty and date |
| **Editorial comment** | Starts with or implies a directive verb; references surrounding text | `[expand this]`, `[needs a transition]`, `[cut the last sentence]`, `[make more vivid]` |

**Classifying reference blocks — what counts as substantial overlap:**
- The block and a nearby passage describe the **same event, fact, or narrative beat**
- They share key nouns, names, or dates
- Reading both together would feel repetitive

**When a prose block could be text block or reference block:** check the surrounding paragraph and the paragraphs immediately before and after. If similar content exists in that neighbourhood, classify as REFERENCE_BLOCK. If no similar content, classify as TEXT_BLOCK.

**When ambiguous (text block vs. editorial comment):** treat it as a text block if it could plausibly be read as prose in context. Treat it as an editorial comment if it contains any of: *make, add, remove, cut, delete, expand, contract, move, change, revise, clarify, rephrase, transition, note, TODO, fix, shorten, lengthen, rewrite, ensure*.

### Extraction Output (internal)

For each marker, record:
- **Location** — surrounding paragraph or nearest heading for context
- **Raw content** — exact text inside `[...]`
- **Type** — TEXT_BLOCK, REFERENCE_BLOCK, or EDITORIAL_COMMENT
- **Surrounding context** — the sentence before and the sentence after the marker
- **Overlapping passage** (REFERENCE_BLOCK only) — the existing text being displaced

---

## Phase 2: Plan Each Edit

For every marker, draft the proposed resolution. Consider the following for each:

### For Text Blocks

- **Integration style:** How should the block attach to what precedes it? Does it start a new sentence, join an existing one, or form its own paragraph?
- **Transitional edits:** Does the preceding sentence need a comma, em-dash, or linking word? Does the following sentence need to be re-anchored (pronoun reference, conjunctions)?
- **Tonal match:** Does the inserted prose match the document's register (formal/informal, past/present tense, POV)?
- **Redundancy check:** Does the inserted block repeat something already said nearby? If so, trim the duplicate — from the insertion or the document.

### For Reference Blocks

See the **Reference Block Mandate** above. The reference block is the base. Start from it. Do not start from the original text and patch in elements of the reference.

**Step-by-step:**

1. **Write the reference block text down as your working draft.** Do not look at the original text while doing this step.
2. **Edit the reference block freely** — wording, sentence structure, depth, and phrasing may all be changed to make the passage fit the document well. The reference block is the *starting point*, not a verbatim constraint. What must not happen is discarding the reference block's content or intent in favour of the original text.
3. **Identify the displaced passage** — the sentence(s) or paragraph that cover the same ground. Mark it for full removal.
4. **Adapt the neighbouring sentences** — edit the sentence immediately before and the sentence immediately after the reference block so they connect smoothly to it. The neighbours change to accommodate the reference block; the reference block does not change to accommodate the neighbours.
5. **Flag displaced-only details** — if the original passage contains a specific fact, name, or detail that the reference block does not mention, flag it in the plan. Do not silently absorb it into the reference block draft; let the user decide.

**What the plan draft must show:**
- The reference block text as it will appear (post surface edits), clearly identified as coming from the reference block
- The original text it replaces, shown separately and struck from the plan
- Any edits to neighbouring sentences, shown explicitly

### For Editorial Comments

- **Scope:** What exactly does the comment apply to? Identify the precise passage affected (sentence, paragraph, section).
- **Intent:** What change does the comment call for? State the intent explicitly in the plan.
- **Proposed edit:** Draft the revised passage. If the comment says "expand", draft the expanded version. If it says "cut", identify what to remove.
- **Adjacent impact:** Will the edit require touching sentences before or after the scope to restore flow?

---

## Phase 3: Present the Plan

**Do not implement anything yet.** Present the plan to the user before making a single edit.

Format each entry as follows:

```
### [n] <Type> — Line ~<line_number>

**Marker:** `[exact bracket content]`
**Surrounding context:**
  Before: "<sentence before>"
  After:  "<sentence after>"

[For REFERENCE_BLOCK only:]
**Displaced passage:**
  "<the existing text being replaced>"

**Proposed edit:**
<show the revised passage with the marker resolved, including any edits to neighbouring text>

**What changes:**
- <bullet: what is inserted/modified/replaced and why>
- <bullet: any neighbouring text altered, and why>
[For REFERENCE_BLOCK: bullet noting any details present in the displaced passage but absent from the reference block, flagged for user decision]
```

End the plan with a summary count: `N text blocks, R reference blocks (replacements), M editorial comments — ready to implement on approval.`

**Wait for the user to confirm** before proceeding to Phase 4. If the user adjusts a proposed edit, update that entry and re-confirm.

> **Hard gate: do not touch the document until the user explicitly approves the plan.** Phrases like "looks good," "yes," "proceed," or "go ahead" count as approval. Silence, a question, or a correction do not. If uncertain whether the user has approved, ask — do not assume and begin.

---

## Phase 4: Implement

Once the user approves the plan, implement all edits in document order (top to bottom).

### Implementation Rules

1. **Remove the `[...]` marker entirely** — no brackets, no residue.
2. **Apply exactly the planned edit** — do not improvise during implementation.
3. **Preserve surrounding formatting** — heading levels, bullet structure, code blocks remain untouched unless the comment explicitly targets them.
4. **One `read` + targeted `edit` per marker** — do not rewrite large sections unnecessarily.
5. **After all edits:** do a final read-through pass. Check that:
   - No stray brackets remain
   - Paragraph breaks are appropriate
   - Tense and POV are consistent throughout
   - No repeated words or phrases introduced by the insertions

### Final Report

After implementation, report:

```
Resolved N markers:
  - X text blocks inserted
  - R reference blocks replaced (adapted reference material substituted for existing text)
  - Y editorial comments applied
Neighbouring edits: <brief summary of any significant surrounding text changes>
```

---

## Common Mistakes

| Mistake | Fix |
|---|---|
| Inserting a text block verbatim without adjusting surrounding connective tissue | Always check the join — edit the sentence before or after as needed |
| Treating a reference block as a plain insertion, leaving the overlapping original text in place | Classify as REFERENCE_BLOCK and replace the overlapping passage — do not append alongside it |
| Drafting from the original and patching in reference block phrasing | Draft from the reference block verbatim first; edit neighbours to fit it — never the reverse |
| Keeping the original because it is "cleaner" or "already says the same thing" | See the Reference Block Mandate. The user has chosen the reference. Implement it. |
| Blending the original and reference into a composite | Not asked for. The reference block is the base; the original is discarded. |
| Silently absorbing displaced-only details into the reference block draft | Flag them explicitly in the plan; let the user decide whether to retain them |
| Implementing edits before explicit user approval | The plan must be confirmed before any file is touched. Ambiguous responses require clarification, not assumption |
| Treating all `[...]` as editorial when some are prose | Apply the classification rules; when uncertain, read it in context |
| Implementing before presenting the plan | Phase 3 (plan) is mandatory — always present first |
| Missing a nested or adjacent marker | Scan with a regex pass (`\[.+?\]`) to ensure nothing is skipped |
| Changing tense or POV during insertion | Match the document's established tense and POV exactly |
| Leaving a seam at the join point | Read the merged sentence aloud (mentally) — if it stumbles, revise the join |

---

## Tips

- If the document is long, scan all markers first and number them before drafting any plan entry — this prevents missing a marker discovered mid-edit.
- If a text block is long (multi-sentence), consider whether it should be its own paragraph rather than appended to an existing one.
- Editorial comments that say `[delete this]` or `[cut]` with no further direction: remove the entire sentence or paragraph the comment is attached to, then smooth the surrounding text.
- If two markers are adjacent or overlapping in scope, treat them as a single combined edit in the plan.
