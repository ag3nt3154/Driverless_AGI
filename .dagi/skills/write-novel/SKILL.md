---
name: write-novel
description: Plan and write a complete novel with structure, character development, and narrative arc
---

# Write a Novel

A skill to guide the creation of a complete novel from concept to final manuscript. This skill covers planning, drafting, and refinement phases.

## Overview

Writing a novel is a multi-phase process. This skill treats it as:

1. **Conceptualization** — Define premise, genre, tone, and scope
2. **Planning** — Build world, characters, and outline
3. **Drafting** — Write scene-by-scene with consistency
4. **Revision** — Refine prose, pacing, and narrative threads

Each phase produces artifacts (notes, outlines, drafts) that feed the next.

---

## Phase 1: Conceptualization

### Define the Premise

Answer these questions succinctly:

- **What is the central conflict?** (internal + external)
- **Who is the protagonist?** What do they want? What must they learn?
- **What genre does this live in?** (literary fiction, thriller, romance, sci-fi, fantasy, etc.)
- **What is the target length?** (70,000–100,000 words for adults; adjust by genre)
- **What is the "handle" or hook?** One sentence that sells the book.

### Choose a Working Title

A placeholder title that captures the mood. You'll refine it later.

### Set the Tone and Scope

- **Tone:** Dark, hopeful, witty, intimate, epic?
- **Point of view:** First person (whose voice?), third limited, omniscient?
- **Tense:** Past or present?
- **POV character count:** One main POV or multiple?

---

## Phase 2: Planning

### Build Your Protagonist

Fill out a character sheet for each main character:

- **Name, age, physical brief**
- **What they want** (conscious goal)
- **What they need** (unconscious growth)
- **Their defining wound or flaw**
- **How they speak** — voice, vocabulary, catchphrases
- **The lie they believe** — the false assumption they operate under
- **Their arc trajectory** — from what to what?

### Sketch the World

- **Setting and era** — time, place, social context
- **Rules of the world** — especially for genre fiction (magic systems, tech, society)
- **What is the status quo?** What will shatter it?

### Develop Supporting Cast

At minimum, define:

- **Antagonist or opposing force** — what they want instead of the protagonist
- **Deuteragonist / best friend** — the mirror character who sees the protagonist clearly
- **Love interest** (if applicable) — what makes them compelling
- **Mentor / antagonist** — the ally who causes trouble
- **Secondary characters** — keep to 5–7 major ones to track cleanly

### Design the Three-Act Structure

Classic structure with word count targets (for an 80,000–90,000 word novel):

| Act | Scope | Target Words |
|---|---|---|
| **Act I — Setup** | Normal world, inciting incident, call to action | ~15,000–20,000 |
| **Act II-A — Rising** | First attempts, complications, midpoint reversal | ~25,000–30,000 |
| **Act II-B — Escalation** | Consequences worsen, stakes raise, all seems lost | ~25,000–30,000 |
| **Act III — Resolution** | Final confrontation, climax, new normal | ~10,000–15,000 |

### Create a Scene Outline

For each scene, specify:

- **Scene number and title** (e.g., "01 — The Letter Arrives")
- **POV character**
- **Location and time**
- **What happens** — goal, conflict, disaster/turn
- **Scene purpose** — what narrative thread does this advance?
- **Word count estimate**

Aim for roughly 2,000–3,000 words per chapter. For an 80,000-word novel, plan 30–40 scenes or chapters.

### Map the Character Arc

For the protagonist, map their internal journey:

```
Act I:  Lie believed → Inciting event challenges the lie
Act II: Attempts to restore the lie → lie collapses at midpoint
Act III: New truth → transformed action → resolution
```

---

## Phase 3: Drafting

### Drafting Principles

- **Write the first draft for discovery.** Don't aim for perfection. Aim for completion.
- **Never skip a scene you don't feel ready for.** Write it rough and move on.
- **Stick to present tense and voice once chosen.** Don't drift.
- **Keep a running word count log.** Track progress daily.
- **When stuck, advance the scene with the cheapest conflict possible.** (A knock at the door. A miscommunication. An interruption.)

### Scene Writing Formula

Every scene needs at minimum:

```
1. Establish setting and POV character's emotional state
2. Introduce or escalate conflict
3. Give the POV character an active goal in the scene
4. Complicate or block that goal
5. End with a turn, revelation, or unanswered question
```

### Maintaining Consistency

- Keep a **bible file** — a plain text or markdown doc with:
  - Character names and quick bios
  - World rules
  - Timeline of events
  - Recurring phrases and speech patterns
  - Setting details

Update it as you draft. Read it before each writing session.

### Writing Workflow

Use the following session loop:

1. Read the bible file
2. Read the previous scene's ending
3. Write the next scene (target: 1,500–3,000 words)
4. Log word count
5. Update the bible with any new details

### Draft Phase Commands

The agent executing this skill should:

- Use `write` to create draft files incrementally (e.g., `ch01.md`, `ch02.md`)
- Use `bash` to log daily word counts: `wc -w drafts/*.md`
- Use `edit` to add new scenes into an existing draft file without rewriting everything

---

## Phase 4: Revision

### Structural Revision

First pass — big picture only:

- Does Act I hook within the first 5,000 words?
- Does the midpoint change everything?
- Does Act III resolve all major threads?
- Are there scenes that serve no narrative purpose? Cut or merge.

### Character Arc Revision

Second pass — character consistency:

- Does the protagonist behave consistently with their established voice?
- Do secondary characters have distinct voices?
- Does the internal arc complete satisfyingly?

### Line-Level Revision

Third pass — prose quality:

- Eliminate repeated words within the same paragraph
- Vary sentence length and structure
- Remove weak openings (filter words, "it was," passive voice)
- Strengthen dialogue — does each line earn its place?

### Beta Reader Integration

After internal revision:

1. Send draft to 2–3 beta readers
2. Collect feedback on: pace, character likeability, plot holes, emotional resonance
3. Create a revision pass addressing consistent feedback themes
4. Repeat if needed

---

## File Structure for a Novel Project

```
novel/
├── SKILL.md              # This skill
├── bible.md              # Characters, world, rules, timeline
├── outline.md            # Scene-by-scene outline
├── drafts/
│   ├── ch01.md
│   ├── ch02.md
│   └── ...
└── revisions/
    ├── draft1_notes.md
    └── draft2_notes.md
```

---

## Tips for the Agent

- When asked to write a novel, begin by asking the user to define the premise, genre, and POV.
- If no premise is given, offer to generate one by asking targeted questions (or propose one).
- Keep draft files small (chapter-sized) for easier editing.
- Use the bible as the single source of truth for consistency.
- For a 80,000-word novel at 1,500 words/day, expect ~53 days to first draft.
- Offer to generate character sheets, scene outlines, or bible entries as separate artifacts.
