# Project Intelligence Agent — TODO

## Overview

**Purpose:** Create an intelligent project management system that:
- Ingests raw data sources (emails, documents, PDFs, meeting minutes) from a `/raw` folder
- Collates and organises information into a structured wiki
- Generates drafts for downstream output (presentations, reports)

**Core Principle:** DAGI (the AI agent) manages collation logic — reading existing wiki entries and deciding the best approach for integrating new information.

---

## Folder Structure

```
project_intelligence_agent/
├── /raw          ← Ingestion point (raw data sources)
├── /wiki         ← Single source of truth
│   ├── schedule.md
│   ├── todo.md
│   ├── readme.md
│   ├── open_questions.md
│   └── ... (additional docs as needed)
├── /archive      ← Processed raw files (for reference)
├── /snapshots    ← Versioned wiki states (before each update)
├── /processing   ← Temp workspace for parsing
└── index.md      ← Meta-structure (source → wiki entry mapping)
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

### todo.md
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
- meeting_notes.md — collated meeting summaries
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

---

## Implementation Phases

### Phase 1: Foundation
- [ ] Create folder structure (raw, wiki, archive, snapshots, processing)
- [ ] Implement file scanning and detection
- [ ] Build basic text file parsing
- [ ] Create initial wiki documents (schedule.md, todo.md, readme.md, open_questions.md)

### Phase 2: Parsing Engine
- [ ] PDF text extraction
- [ ] DOCX text extraction
- [ ] Email parsing (.eml)
- [ ] Metadata identification (dates, tags, entities)

### Phase 3: Collation Intelligence
- [ ] Wiki reading and comparison logic
- [ ] Merge strategy decision engine
- [ ] Cross-document linking
- [ ] Conflict detection and resolution

### Phase 4: Versioning & Index
- [ ] Snapshot creation on wiki updates
- [ ] Index.md management
- [ ] Source tracking and mapping

### Phase 5: Archive & Cleanup
- [ ] File archival with timestamp
- [ ] Processing folder cleanup
- [ ] Sync report generation

### Phase 6: Commands & Interface
- [ ] CLI command implementation
- [ ] User-facing sync trigger
- [ ] Status and reporting commands

### Phase 7: Downstream Generation
- [ ] Draft document templates
- [ ] PPT outline generation
- [ ] Report structure generation
- [ ] Refinement workflow

---

## Tech Stack (Proposed)

- **Language:** Python 3.x
- **PDF Parsing:** PyPDF2 or pdfplumber
- **DOCX Parsing:** python-docx
- **Email Parsing:** email (stdlib) + python-sigle or extract-msg
- **File Watching:** watchdog (optional, for future continuous mode)
- **Configuration:** YAML-based config
- **CLI:** argparse or click

---

## Decisions Required

1. **Python version:** 3.9+ required?
2. **Dependencies:** Which libraries for PDF/DOCX parsing?
3. **Snapshot retention:** How long to keep snapshots? (7 days? 30 days? Unlimited?)
4. **Index format:** Markdown table? Structured YAML within MD?
5. **Sync trigger:** CLI only, or also file-based watcher?
6. **Error handling:** On parse failure — skip file, pause sync, or log and continue?
7. **Downstream formats:** What document types for drafts? (.md, .docx, .tex?)

---

*Last Updated: [timestamp]*
*Status: Planning*