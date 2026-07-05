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

The bracketed content is treated as the authoritative version. The existing overlapping text is the version to be replaced.

1. **Identify the displaced passage** — the specific sentence(s) or paragraph in the document that cover the same ground as the reference block. This is what will be removed.
2. **Adapt the reference block to the document** — edit it for tonal register, tense, POV, and stylistic consistency with the rest of the document. Do not change the substance of the reference material; only surface-level style should change.
3. **Draft the replacement** — show the adapted reference block as it will appear in place of the displaced passage, with any join edits to neighbouring text.
4. **Scope the displacement carefully** — only remove the text that genuinely overlaps. If the existing passage contains details not present in the reference block, flag this in the plan for the user to decide whether to retain them.

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
| Treating a reference block as a plain insertion, leaving the overlapping original text in place | When a text block covers the same ground as nearby text, classify as REFERENCE_BLOCK and replace the overlapping passage rather than appending |
| Over-displacing — removing existing text that contains details not in the reference block | Scope the displaced passage precisely; flag any details present in the document but absent from the reference block for the user to decide |
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
