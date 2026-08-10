# BM25 Memory Recall Hook — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A global Claude Code `UserPromptSubmit` hook that runs BM25 retrieval against the
personal memory wiki, displays results to the user (stderr), and injects them into Claude's
context (systemMessage).

**Architecture:** Single Python script invoked by Claude Code on every prompt; substantiveness
heuristic short-circuits non-task messages; fresh BM25Okapi index built per call from all wiki
`.md` files; Reasonix gates applied before output.

**Tech Stack:** Python 3, `rank_bm25` (`BM25Okapi`), Claude Code hooks (`UserPromptSubmit`),
`dagi` conda env (`C:/Users/alexr/miniconda3`).

## Global Constraints

- Script path: `C:\Users\alexr\.claude\hooks\bm25_memory_recall.py`
- Tests path: `C:\Users\alexr\.claude\hooks\tests\test_bm25_memory_recall.py`
- Hook config: `C:\Users\alexr\.claude\settings.json` (merge, never overwrite)
- Wiki root: `G:\My Drive\black_grimoire\dagi-memory\wiki`
- Conda env: `dagi` — use `C:/Users/alexr/miniconda3/Scripts/conda.exe run -n dagi python`
- `rank_bm25` must be installed into the `dagi` env
- Hook must never exit non-zero in a way that blocks a prompt — all failures exit 0 silently
- Line length ≤ 100 chars, functions ≤ 100 lines, cyclomatic complexity ≤ 8

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `C:\Users\alexr\.claude\hooks\bm25_memory_recall.py` | Full hook: filter, load, score, output |
| Create | `C:\Users\alexr\.claude\hooks\tests\test_bm25_memory_recall.py` | Unit + integration tests |
| Modify | `C:\Users\alexr\.claude\settings.json` | Add `hooks.UserPromptSubmit` entry |

---

## Task 1: Install dependency, write tests, implement hook script

**Files:**
- Create: `C:\Users\alexr\.claude\hooks\bm25_memory_recall.py`
- Create: `C:\Users\alexr\.claude\hooks\tests\test_bm25_memory_recall.py`

**Interfaces:**
- Produces:
  - `is_substantive(prompt: str) -> bool`
  - `parse_frontmatter(text: str) -> tuple[dict, str]`
  - `load_docs(wiki_root: Path) -> list[dict]`  — each dict has keys: `path`, `title`, `description`, `snippet`, `combined`
  - `tokenize(text: str) -> list[str]`
  - `retrieve(docs: list[dict], prompt: str) -> list[tuple[float, dict]]`
  - `build_outputs(results: list[tuple[float, dict]], wiki_root: Path) -> tuple[str, str]`
  - `main() -> None`

---

- [ ] **Step 1: Install rank_bm25**

```powershell
C:/Users/alexr/miniconda3/Scripts/conda.exe run -n dagi pip install rank-bm25
```

Expected: `Successfully installed rank-bm25-...`

---

- [ ] **Step 2: Create the test file (all tests initially failing)**

Create `C:\Users\alexr\.claude\hooks\tests\__init__.py` (empty).

Create `C:\Users\alexr\.claude\hooks\tests\test_bm25_memory_recall.py`:

```python
import json
import sys
import io
from pathlib import Path
import pytest

# Add parent dir so we can import the hook module
sys.path.insert(0, str(Path(__file__).parent.parent))
import bm25_memory_recall as hook


# ── is_substantive ────────────────────────────────────────────────────────────

def test_substantive_short_prompt_rejected():
    assert hook.is_substantive("hello") is False


def test_substantive_below_word_threshold():
    assert hook.is_substantive("fix the bug in auth") is False  # 5 words


def test_substantive_at_threshold():
    assert hook.is_substantive("fix the authentication bug in the login flow") is True


def test_substantive_skip_opening_single():
    assert hook.is_substantive("thanks for the help with that last task today") is False


def test_substantive_skip_opening_two_words():
    assert hook.is_substantive("sounds good let me know when that is ready") is False


def test_substantive_normal_task():
    assert hook.is_substantive(
        "i want to build a bm25 hook for claude code memory retrieval"
    ) is True


# ── parse_frontmatter ─────────────────────────────────────────────────────────

def test_parse_frontmatter_with_valid_fm():
    text = '---\ntitle: My Title\ntags: foo, bar\n---\n\n# Body here'
    fm, body = hook.parse_frontmatter(text)
    assert fm["title"] == "My Title"
    assert fm["tags"] == "foo, bar"
    assert "Body here" in body


def test_parse_frontmatter_no_fm():
    text = "# Just a body\nNo frontmatter here."
    fm, body = hook.parse_frontmatter(text)
    assert fm == {}
    assert "Just a body" in body


def test_parse_frontmatter_quoted_values():
    text = '---\ntitle: "Quoted Title"\n---\nBody'
    fm, body = hook.parse_frontmatter(text)
    assert fm["title"] == "Quoted Title"


def test_parse_frontmatter_unclosed_returns_empty():
    text = '---\ntitle: Oops\n'  # no closing ---
    fm, body = hook.parse_frontmatter(text)
    assert fm == {}


# ── tokenize ──────────────────────────────────────────────────────────────────

def test_tokenize_lowercases():
    assert hook.tokenize("Hello World") == ["hello", "world"]


def test_tokenize_strips_punctuation():
    assert hook.tokenize("foo, bar!") == ["foo", "bar"]


def test_tokenize_empty():
    assert hook.tokenize("") == []


# ── load_docs ─────────────────────────────────────────────────────────────────

def test_load_docs_skips_dotfiles(tmp_path):
    (tmp_path / ".index.md").write_text("---\ntitle: Hidden\n---\nHidden body")
    (tmp_path / "real.md").write_text("---\ntitle: Real\n---\nReal body")
    docs = hook.load_docs(tmp_path)
    titles = [d["title"] for d in docs]
    assert "Real" in titles
    assert "Hidden" not in titles


def test_load_docs_uses_stem_as_fallback_title(tmp_path):
    (tmp_path / "my-note.md").write_text("No frontmatter here, just body text.")
    docs = hook.load_docs(tmp_path)
    assert docs[0]["title"] == "my-note"


def test_load_docs_doc_has_required_keys(tmp_path):
    (tmp_path / "note.md").write_text("---\ntitle: Note\n---\nBody text here.")
    docs = hook.load_docs(tmp_path)
    assert all(k in docs[0] for k in ("path", "title", "description", "snippet", "combined"))


def test_load_docs_snippet_bounded(tmp_path):
    (tmp_path / "big.md").write_text("---\ntitle: Big\n---\n" + "x" * 1000)
    docs = hook.load_docs(tmp_path)
    assert len(docs[0]["snippet"]) <= hook.SNIPPET_LEN


# ── retrieve ──────────────────────────────────────────────────────────────────

def _make_docs(titles_and_bodies: list[tuple[str, str]]) -> list[dict]:
    return [
        {
            "path": Path(f"/fake/{t}.md"),
            "title": t,
            "description": "",
            "snippet": b[:hook.SNIPPET_LEN],
            "combined": f"{t} {b}",
        }
        for t, b in titles_and_bodies
    ]


def test_retrieve_returns_relevant_result():
    docs = _make_docs([
        ("BM25 retrieval", "bm25 rank scoring information retrieval"),
        ("Cooking recipe", "pasta carbonara eggs bacon cheese"),
    ])
    results = hook.retrieve(docs, "bm25 information retrieval ranking")
    assert results[0][1]["title"] == "BM25 retrieval"


def test_retrieve_relative_cutoff_filters_low_scores():
    docs = _make_docs([
        ("BM25 retrieval", "bm25 rank scoring information retrieval"),
        ("Cooking recipe", "pasta carbonara eggs bacon cheese"),
        ("Another topic", "completely unrelated content about widgets"),
    ])
    results = hook.retrieve(docs, "bm25 bm25 bm25 retrieval retrieval")
    titles = [r[1]["title"] for r in results]
    # Cooking/widgets should be filtered by 24% cutoff
    assert "Cooking recipe" not in titles


def test_retrieve_caps_at_max_results():
    docs = _make_docs([(f"doc{i}", f"python code test {i}") for i in range(20)])
    results = hook.retrieve(docs, "python code test")
    assert len(results) <= hook.MAX_RESULTS


def test_retrieve_empty_corpus_returns_empty():
    results = hook.retrieve([], "any prompt")
    assert results == []


# ── build_outputs ─────────────────────────────────────────────────────────────

def _make_results(n: int, wiki_root: Path) -> list[tuple[float, dict]]:
    return [
        (
            float(n - i),
            {
                "path": wiki_root / f"doc{i}.md",
                "title": f"Title {i}",
                "description": f"Description {i}",
                "snippet": f"Snippet content {i}",
            },
        )
        for i in range(n)
    ]


def test_build_outputs_display_contains_titles(tmp_path):
    results = _make_results(2, tmp_path)
    display, _ = hook.build_outputs(results, tmp_path)
    assert "Title 0" in display
    assert "Title 1" in display


def test_build_outputs_system_message_contains_content(tmp_path):
    results = _make_results(2, tmp_path)
    _, system_msg = hook.build_outputs(results, tmp_path)
    assert "Memory Wiki" in system_msg
    assert "Title 0" in system_msg


def test_build_outputs_respects_char_budget(tmp_path):
    # Create results with large snippets that exceed budget
    large_results = [
        (
            float(10 - i),
            {
                "path": tmp_path / f"doc{i}.md",
                "title": f"Title {i}",
                "description": "desc",
                "snippet": "x" * 500,
            },
        )
        for i in range(8)
    ]
    _, system_msg = hook.build_outputs(large_results, tmp_path)
    assert len(system_msg) <= hook.CHAR_BUDGET + 200  # small tolerance for header


# ── main() integration ────────────────────────────────────────────────────────

def test_main_exits_0_for_short_prompt(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("bm25_memory_recall.WIKI_ROOT", tmp_path)
    stdin_data = json.dumps({"prompt": "hi"})
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_data))
    with pytest.raises(SystemExit) as exc:
        hook.main()
    assert exc.value.code == 0


def test_main_emits_json_for_substantive_prompt(tmp_path, monkeypatch, capsys):
    (tmp_path / "note.md").write_text(
        "---\ntitle: BM25 Info\n---\nbm25 ranking retrieval scoring algorithm"
    )
    monkeypatch.setattr("bm25_memory_recall.WIKI_ROOT", tmp_path)
    prompt = "explain how bm25 ranking and retrieval scoring works in information retrieval"
    stdin_data = json.dumps({"prompt": prompt})
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_data))
    monkeypatch.setattr("sys.stdout", io.StringIO())
    with pytest.raises(SystemExit) as exc:
        hook.main()
    assert exc.value.code == 0
```

---

- [ ] **Step 3: Run tests — verify they all fail**

```powershell
C:/Users/alexr/miniconda3/Scripts/conda.exe run -n dagi python -m pytest `
  "C:/Users/alexr/.claude/hooks/tests/test_bm25_memory_recall.py" -v 2>&1 | head -30
```

Expected: `ImportError` or `ModuleNotFoundError` — script doesn't exist yet.

---

- [ ] **Step 4: Create the hook script**

Create `C:\Users\alexr\.claude\hooks\bm25_memory_recall.py`:

```python
"""
Claude Code UserPromptSubmit hook: BM25 memory wiki recall.

On every substantive prompt: globs wiki .md files, builds a BM25Okapi index,
retrieves top results, displays them (stderr), injects as systemMessage (stdout).
"""
import json
import re
import sys
from pathlib import Path

WIKI_ROOT = Path(r"G:\My Drive\black_grimoire\dagi-memory\wiki")
MIN_WORDS = 8
SKIP_OPENINGS = {
    "thanks", "thank you", "ok", "okay", "yes", "no",
    "sure", "got it", "great", "good", "sounds good", "perfect",
}
RELATIVE_CUTOFF = 0.24
MAX_RESULTS = 8
CHAR_BUDGET = 2400
SNIPPET_LEN = 300


def is_substantive(prompt: str) -> bool:
    words = prompt.lower().split()
    if len(words) < MIN_WORDS:
        return False
    lead = " ".join(words[:2])
    return words[0] not in SKIP_OPENINGS and lead not in SKIP_OPENINGS


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    fm: dict = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, text[end + 3:].strip()


def load_docs(wiki_root: Path) -> list[dict]:
    docs = []
    for path in wiki_root.rglob("*.md"):
        if path.name.startswith("."):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            fm, body = parse_frontmatter(text)
            title = fm.get("title") or path.stem
            tags = fm.get("tags", "")
            description = fm.get("description", "")
            docs.append({
                "path": path,
                "title": title,
                "description": description,
                "snippet": body[:SNIPPET_LEN].strip(),
                "combined": f"{title} {tags} {description} {body}",
            })
        except Exception:
            continue
    return docs


def tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def retrieve(docs: list[dict], prompt: str) -> list[tuple[float, dict]]:
    if not docs:
        return []
    from rank_bm25 import BM25Okapi
    bm25 = BM25Okapi([tokenize(d["combined"]) for d in docs])
    scores = bm25.get_scores(tokenize(prompt))
    top = float(scores.max()) if len(scores) > 0 else 0.0
    if top == 0.0:
        return []
    cutoff = top * RELATIVE_CUTOFF
    ranked = sorted(
        [(float(s), d) for s, d in zip(scores, docs) if float(s) >= cutoff],
        key=lambda x: -x[0],
    )
    return ranked[:MAX_RESULTS]


def build_outputs(
    results: list[tuple[float, dict]], wiki_root: Path
) -> tuple[str, str]:
    display = [f"[memory-recall] {len(results)} item(s) retrieved:"]
    context = ["[Memory Wiki — Retrieved Context]\n"]
    char_used = 0
    for _score, doc in results:
        rel = doc["path"].relative_to(wiki_root)
        display.append(f"  • {doc['title']}")
        display.append(f"    ({rel})")
        entry = f"### {doc['title']}\n"
        if doc["description"]:
            entry += f"{doc['description']}\n"
        if doc["snippet"]:
            entry += f"{doc['snippet']}\n"
        entry += "\n"
        if char_used + len(entry) > CHAR_BUDGET:
            break
        context.append(entry)
        char_used += len(entry)
    return "\n".join(display), "".join(context)


def main() -> None:
    try:
        data = json.load(sys.stdin)
        prompt = data.get("prompt", "")
        if not is_substantive(prompt):
            sys.exit(0)
        if not WIKI_ROOT.exists():
            sys.exit(0)
        docs = load_docs(WIKI_ROOT)
        if not docs:
            sys.exit(0)
        try:
            results = retrieve(docs, prompt)
        except ImportError:
            sys.exit(0)
        if not results:
            sys.exit(0)
        display, system_message = build_outputs(results, WIKI_ROOT)
        print(display, file=sys.stderr)
        json.dump({"systemMessage": system_message}, sys.stdout)
        sys.exit(0)
    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
```

---

- [ ] **Step 5: Run tests — verify they all pass**

```powershell
C:/Users/alexr/miniconda3/Scripts/conda.exe run -n dagi python -m pytest `
  "C:/Users/alexr/.claude/hooks/tests/test_bm25_memory_recall.py" -v
```

Expected: all green. Fix any failures before continuing.

---

- [ ] **Step 6: Commit**

```powershell
git -C "C:/Users/alexr/.claude" add `
  hooks/bm25_memory_recall.py `
  hooks/tests/__init__.py `
  hooks/tests/test_bm25_memory_recall.py
git -C "C:/Users/alexr/.claude" commit -m "feat: BM25 memory recall UserPromptSubmit hook"
```

If `~/.claude` is not a git repo, skip the commit step — the files are still in place.

---

## Task 2: Register hook in settings.json and smoke test

**Files:**
- Modify: `C:\Users\alexr\.claude\settings.json`

**Interfaces:**
- Consumes: `bm25_memory_recall.py` from Task 1 (must exist at its path before registering)

---

- [ ] **Step 1: Merge the hook entry into settings.json**

Read the current `C:\Users\alexr\.claude\settings.json`, add the `hooks` key, and write back.
Use this Python one-liner to do the merge safely:

```powershell
C:/Users/alexr/miniconda3/Scripts/conda.exe run -n dagi python -c "
import json
from pathlib import Path
p = Path(r'C:/Users/alexr/.claude/settings.json')
cfg = json.loads(p.read_text(encoding='utf-8'))
cfg['hooks'] = {
    'UserPromptSubmit': [{
        'matcher': '',
        'hooks': [{
            'type': 'command',
            'command': 'C:/Users/alexr/miniconda3/Scripts/conda.exe run -n dagi python C:/Users/alexr/.claude/hooks/bm25_memory_recall.py',
            'timeout': 30
        }]
    }]
}
p.write_text(json.dumps(cfg, indent=2), encoding='utf-8')
print('Done')
"
```

Expected output: `Done`

---

- [ ] **Step 2: Verify settings.json looks correct**

```powershell
C:/Users/alexr/miniconda3/Scripts/conda.exe run -n dagi python -c "
import json
from pathlib import Path
cfg = json.loads(Path(r'C:/Users/alexr/.claude/settings.json').read_text())
print(json.dumps(cfg.get('hooks'), indent=2))
"
```

Expected: prints the `UserPromptSubmit` hook entry. All other existing keys (`permissions`,
`enabledPlugins`, etc.) must still be present — check the full output if unsure.

---

- [ ] **Step 3: Smoke test — run the script manually against a real prompt**

```powershell
echo '{"prompt": "i want to build a bm25 hook for claude code memory retrieval passive recall"}' | `
  C:/Users/alexr/miniconda3/Scripts/conda.exe run -n dagi python `
  "C:/Users/alexr/.claude/hooks/bm25_memory_recall.py"
```

Expected:
- stderr: `[memory-recall] N item(s) retrieved:` followed by bullet list of titles
- stdout: JSON `{"systemMessage": "[Memory Wiki — Retrieved Context]\n..."}` with actual wiki content

---

- [ ] **Step 4: Smoke test — verify non-substantive prompt is a no-op**

```powershell
echo '{"prompt": "ok thanks"}' | `
  C:/Users/alexr/miniconda3/Scripts/conda.exe run -n dagi python `
  "C:/Users/alexr/.claude/hooks/bm25_memory_recall.py"
```

Expected: no output, exit 0.

---

- [ ] **Step 5: Commit settings.json**

```powershell
git -C "C:/Users/alexr/.claude" add settings.json
git -C "C:/Users/alexr/.claude" commit -m "feat: register BM25 memory recall hook in global settings"
```

If `~/.claude` is not a git repo, skip — the change is already saved.

---

## Self-Review

**Spec coverage:**
- [x] `UserPromptSubmit` hook — Task 2 Step 1 registers it
- [x] BM25 retrieval with `rank_bm25` — Task 1 Step 4 `retrieve()`
- [x] Substantiveness heuristic (word count + skip openings) — Task 1 Step 4 `is_substantive()`
- [x] Full display to user (stderr, titles + relative paths) — Task 1 Step 4 `build_outputs()`
- [x] Inject as `systemMessage` — Task 1 Step 4 `main()` stdout JSON
- [x] Reasonix gates (24% cutoff, 8 results, 2400 chars, 300-char snippet) — Task 1 Step 4 `retrieve()` + `build_outputs()`
- [x] Graceful degradation on missing `rank_bm25` — Task 1 Step 4 `main()` ImportError catch
- [x] `rank_bm25` install — Task 1 Step 1
- [x] settings.json merge (not overwrite) — Task 2 Step 1

**Placeholder scan:** No TBDs, TODOs, or vague steps found.

**Type consistency:** All function signatures used in tests match implementations exactly.
`retrieve()` returns `list[tuple[float, dict]]` in both Task 1 tests and implementation.
`build_outputs()` takes `list[tuple[float, dict]]` consistently throughout.
