# Project Intelligence Agent — TODO

## Overview

**Purpose:** Create an intelligent project management system that:
- Ingests raw data sources (emails, documents, PDFs, meeting minutes) from a `/raw` folder
- Collates and organises information into a structured wiki
- Generates drafts for downstream output (presentations, reports)

**Core Principle:** DAGI (the AI agent) manages collation logic — reading existing wiki entries and deciding the best approach for integrating new information.

> **Note on this file:** This is the system *specification and build tracker*. The live project action-item list lives at `wiki/todo.md` once initialized. Do not confuse the two.

---

## Folder Structure

```
project_intelligence_agent/
├── /raw              ← Ingestion point (raw data sources)
├── /wiki             ← Single source of truth
│   ├── schedule.md
│   ├── todo.md       ← Live action items (NOT this file)
│   ├── readme.md
│   ├── open_questions.md
│   ├── deliverables.md
│   ├── decisions.md
│   ├── index.md
│   └── /sources      ← Sourced documents by type
│       ├── /emails
│       ├── /meetings
│       ├── /docs
│       └── /misc
├── /archive          ← Processed raw files (for reference)
├── /snapshots        ← Versioned wiki states (before each update)
├── /processing       ← Temp workspace for parsing
├── /.dagi/
│   ├── AGENTS.md     ← Agent behavioral instructions
│   ├── logs/         ← Session logs (JSONL)
│   └── skills/       ← PMS-specific skills
└── index.md          ← Meta-structure (source → wiki entry mapping)
```

---

## Core System Components

### 1. File Ingestion Module
- Monitors `/raw` folder (on-demand trigger)
- Detects new files
- Supports file types:
  - Plain text (.txt, .md)
  - PDFs (.pdf) — text extraction
  - Word documents (.docx) — text extraction
  - Email formats (.eml, .msg) — header + body extraction
  - Markdown files (.md)

### 2. Parsing Engine
- Extracts content from each file type
- Identifies:
  - Date/time information
  - Key decisions or action items
  - Named entities (people, projects, tasks)
  - Topic/classification tags
- Outputs structured data for collation

### 3. Collation Logic (DAGI's Responsibility)
- Reads existing wiki documents
- For each new piece of information, decides:
  - **Append** — New points, updates to open items
  - **Replace** — New information supersedes old (e.g., updated schedules)
  - **Merge** — Related information combined into cohesive entries
- Maintains logical consistency across documents
- Links related items across different wiki documents

### 4. Wiki Manager
- Updates existing wiki documents
- Creates new wiki documents when needed
- Maintains document structure and formatting
- Ensures cross-references between related entries

### 5. Versioning System
- Before each wiki update, creates a snapshot of affected documents
- Snapshots stored in `/snapshots` with timestamp
- Enables rollback if needed
- Snapshot naming: `{document_name}_{YYYYMMDD_HHMMSS}.md`

### 6. Index Manager
- Maintains `index.md` as the meta-structure
- Maps raw sources → wiki entries
- Tracks:
  - Source filename
  - Ingestion date
  - Wiki documents updated
  - Classification/tags

### 7. Archive Module
- Moves processed files from `/raw` to `/archive`
- Preserves original filename with timestamp
- Maintains folder structure within archive (by date/source)

---

## Wiki Document Specifications

### schedule.md
- Timeline of project milestones
- Meeting schedules
- Deadlines and delivery dates
- Replaces or appends based on new scheduling info

### todo.md *(wiki/todo.md — live action items)*
- Current action items
- Ownership and due dates
- Completion status
- New items appended, completed items archived/marked done

### readme.md
- Project overview
- Key contacts
- Quick reference information
- Updated with new details as discovered

### open_questions.md
- Unanswered questions requiring action
- Tracking of responses needed
- Links to relevant sources

### Additional Documents (as needed)
- deliverables.md — deliverable tracking with status
- decisions.md — key decisions log
- risks.md — risk register
- glossary.md — project-specific terminology

---

## Processing Pipeline

```
1. TRIGGER: User invokes "sync" command
2. SCAN: List all files in /raw
3. PARSE: For each file:
   a. Detect file type
   b. Extract content
   c. Identify metadata (date, author, tags)
   d. Store in processing structure
4. COLLATE: For each wiki document:
   a. Read current content
   b. Compare with new information
   c. Determine merge strategy (append/replace/merge)
   d. Apply changes
5. SNAPSHOT: Before updating, save current state to /snapshots
6. UPDATE: Write new wiki content
7. INDEX: Update index.md with source mappings
8. ARCHIVE: Move processed files to /archive
9. REPORT: Summarise changes made
```

---

## Command Interface

| Command | Description |
|---------|-------------|
| `sync` | Run full ingestion and collation pipeline |
| `status` | Show pending files in /raw, last sync time |
| `snapshot` | Manually create a wiki snapshot |
| `rollback <timestamp>` | Restore wiki from a snapshot |
| `index` | Display current index.md contents |
| `report` | Generate summary of recent changes |
| `validate` | Check wiki for conflicts/inconsistencies |
| `export` | Generate stakeholder report or PPT outline from wiki |

---

## Implementation Phases

### Phase 1: Foundation
- [x] `pms-init` skill designed — creates folder structure and wiki stub documents
- [ ] Run `pms-init` to generate actual wiki stubs (schedule.md, readme.md, open_questions.md, index.md, deliverables.md, decisions.md)
- [ ] Create `archive/`, `snapshots/`, `processing/` subdirectories
- [ ] Implement file scanning and detection (Python)
- [ ] Build basic text file parsing (Python)

### Phase 2: Parsing Engine *(skill designed via pms-ingest; Python code not yet written)*
- [ ] PDF text extraction (pdfplumber)
- [ ] DOCX text extraction (python-docx)
- [ ] Email parsing (.eml / .msg) with header + body extraction
- [ ] Plain text (.txt) parsing
- [ ] Metadata identification (dates, entities, classification tags)

### Phase 3: Collation Intelligence *(strategy defined in pms-ingest skill; code not yet written)*
- [ ] Wiki reading and comparison logic (Python)
- [ ] Merge strategy decision engine (append / replace / merge)
- [ ] Cross-document linking
- [ ] Conflict detection and resolution

### Phase 4: Versioning & Index *(logic defined in pms-ingest; code not yet written)*
- [ ] Snapshot creation on wiki updates
- [ ] `index.md` automated management
- [ ] Source tracking and mapping
- [ ] Rollback from snapshot

### Phase 5: Archive & Cleanup *(not yet designed in any skill)*
- [ ] Design `pms-archive` skill or extend `pms-ingest` with archive step
- [ ] File archival with timestamp (raw → archive)
- [ ] Processing folder cleanup after sync
- [ ] Sync report generation

### Phase 6: Commands & Interface *(pms-query covers query commands; others are spec-only)*
- [x] `pms-query` skill designed — query routing, wiki reading, source tracing
- [ ] CLI: `sync` command implementation
- [ ] CLI: `status` command
- [ ] CLI: `snapshot` / `rollback` commands
- [ ] CLI: `index` / `report` commands
- [ ] CLI: `validate` / `export` commands (new — see Improvements)

### Phase 7: Downstream Generation *(not started)*
- [ ] Design `pms-export` skill — generate stakeholder output from wiki
- [ ] Draft document templates (markdown)
- [ ] PPT outline generation
- [ ] Report structure generation
- [ ] Refinement workflow

### Phase 8: Agent Instructions & Behavioral Configuration *(new — from DAGI patterns)*
- [ ] Write `.dagi/AGENTS.md` with PMS-specific behavioral instructions
  - "Always check wiki documents before ingesting new raw files"
  - "Use `pms-query` before raw file reads"
  - "Log all decisions to `wiki/decisions.md`"
  - "Prefer append over replace unless source explicitly supersedes"
- [ ] Define agent persona for project management context

### Phase 9: Observability & Self-Improvement *(new — from DAGI session tracking pattern)*
- [ ] Add `.dagi/logs/` to folder structure
- [ ] Integrate session logging (JSONL, aligned with DAGI `agent/session.py` pattern)
- [ ] Apply `self-improve` skill to PMS session logs to identify workflow friction
- [ ] Identify and resolve recurring failure patterns (e.g., query misses, stale wiki entries)

---

## Planned Skills

| Skill | Status | Purpose |
|-------|--------|---------|
| `pms-init` | ✅ Designed | Initialize folder structure + wiki stubs |
| `pms-ingest` | ✅ Designed | Ingest raw files, classify, extract, update wiki |
| `pms-query` | ✅ Designed | Answer questions from wiki + source tracing |
| `pms-report` | ⬜ Planned | Synthesize status across all wiki documents |
| `pms-validate` | ⬜ Planned | Detect conflicts/inconsistencies in wiki (mirrors `memory-lint` pattern) |
| `pms-export` | ⬜ Planned | Generate stakeholder reports and PPT outlines |

---

## Tech Stack (Proposed)

- **Language:** Python 3.x
- **PDF Parsing:** pdfplumber (preferred over PyPDF2 for layout fidelity)
- **DOCX Parsing:** python-docx
- **Email Parsing:** `email` (stdlib) + `extract-msg` for .msg files
- **File Watching:** watchdog (optional, for future continuous mode)
- **Configuration:** YAML-based config
- **CLI:** click (preferred over argparse for composability)

---

## Decisions Required

1. **Python version:** 3.9+ required?
2. **Snapshot retention:** How long to keep snapshots? (7 days? 30 days? Unlimited?)
3. **Index format:** Markdown table? Structured YAML within MD?
4. **Sync trigger:** CLI only, or also file-based watcher?
5. **Error handling:** On parse failure — skip file, pause sync, or log and continue?
6. **Downstream formats:** What document types for drafts? (.md, .docx, .tex?)
7. **Sub-agent parallelism:** For large `raw/` batches, spawn sub-agents per file type? (see DAGI `SubAgentRunner` pattern in `agent/sub_agent.py`)

---

*Last Updated: 2026-04-23*
*Status: In Progress*
