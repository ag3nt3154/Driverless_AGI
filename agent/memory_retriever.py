from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

_STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
    "her", "was", "one", "our", "out", "day", "get", "has", "him", "his",
    "how", "its", "may", "new", "now", "old", "see", "two", "way", "who",
    "did", "let", "put", "say", "she", "too", "use", "with", "that", "this",
    "from", "they", "been", "have", "will", "when", "what", "which", "also",
}


def _tokenize(text: str) -> list[str]:
    return [
        w for w in re.findall(r"[a-z0-9]+", text.lower())
        if len(w) >= 3 and w not in _STOPWORDS
    ]


def _bm25_scores(query: str, docs: list[str], k1: float = 1.2, b: float = 0.5) -> list[float]:
    """BM25 score for each doc string given a query string. Tuned for short docs (topic descriptions)."""
    q_terms = _tokenize(query)
    if not q_terms or not docs:
        return [0.0] * len(docs)

    tokenized = [_tokenize(d) for d in docs]
    N = len(docs)
    avgdl = sum(len(t) for t in tokenized) / N if N else 1

    scores: list[float] = []
    for doc_tokens in tokenized:
        tf = Counter(doc_tokens)
        dl = len(doc_tokens)
        score = 0.0
        for term in q_terms:
            n_q = sum(1 for t in tokenized if term in t)
            idf = math.log((N - n_q + 0.5) / (n_q + 0.5) + 1)
            denom = tf[term] + k1 * (1 - b + b * dl / avgdl) if avgdl else 1
            tf_score = tf[term] * (k1 + 1) / denom if denom else 0
            score += idf * tf_score
        scores.append(score)
    return scores


def _read_safe(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


def _parse_index_table(content: str) -> list[tuple[str, str]]:
    """Extract (slug, description) pairs from a markdown table in an index.md file."""
    rows: list[tuple[str, str]] = []
    for line in content.splitlines():
        line = line.strip()
        if not line.startswith("|") or line.startswith("| ---") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 2 and cells[0] and not cells[0].startswith("---"):
            # Strip markdown link syntax: [text](url) → text
            slug = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cells[0]).strip()
            desc = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cells[1]).strip()
            if slug and not slug.startswith("-"):
                rows.append((slug, desc))
    return rows


def build_memory_context(
    memory_root: Path,
    task: str,
    max_tokens: int = 4_000,
    max_topics: int = 3,
    max_pages_per_topic: int = 2,
) -> str | None:
    """
    Retrieve relevant wiki pages for a task using BM25 topic scoring +
    memory-query traversal logic (Steps 3–6). Returns a formatted injection
    block or None if the wiki is empty, missing, or nothing matches.
    """
    wiki_root = memory_root / "wiki"
    root_index_content = _read_safe(wiki_root / "index.md")

    candidate_pages: list[tuple[float, Path]] = []  # (score, path)

    # ── Pass 1: BM25 topic scoring against root index ─────────────────────
    if root_index_content:
        topic_rows = _parse_index_table(root_index_content)
        if topic_rows:
            topic_slugs = [slug for slug, _ in topic_rows]
            topic_texts = [f"{slug} {desc}" for slug, desc in topic_rows]
            scores = _bm25_scores(task, topic_texts)
            ranked = sorted(zip(scores, topic_slugs), reverse=True)
            top_topics = [slug for _, slug in ranked[:max_topics]]

            # ── Pass 2: Drill into each topic index (memory-query Step 4) ─
            for topic_slug in top_topics:
                topic_index_path = wiki_root / topic_slug / "index.md"
                topic_index = _read_safe(topic_index_path)
                if not topic_index:
                    continue
                page_rows = _parse_index_table(topic_index)
                if not page_rows:
                    # No page table — treat the topic index itself as a candidate
                    topic_score = next((s for s, sl in ranked if sl == topic_slug), 0.0)
                    candidate_pages.append((topic_score, topic_index_path))
                    continue
                page_slugs = [slug for slug, _ in page_rows]
                page_texts = [f"{slug} {desc}" for slug, desc in page_rows]
                page_scores = _bm25_scores(task, page_texts)
                page_ranked = sorted(zip(page_scores, page_slugs), reverse=True)
                for page_score, page_slug in page_ranked[:max_pages_per_topic]:
                    page_path = wiki_root / topic_slug / f"{page_slug}.md"
                    if not page_path.exists():
                        # Try as a subdirectory index
                        page_path = wiki_root / topic_slug / page_slug / "index.md"
                    if page_path.exists():
                        candidate_pages.append((page_score, page_path))

    # ── Pass 3: Grep fallback if too few candidates (memory-query Step 5) ─
    if len(candidate_pages) < 2:
        all_md = list(wiki_root.rglob("*.md")) if wiki_root.exists() else []
        fallback_texts = [
            p.stem + " " + (_read_safe(p) or "")[:400]
            for p in all_md
        ]
        if fallback_texts:
            fb_scores = _bm25_scores(task, fallback_texts)
            fb_ranked = sorted(zip(fb_scores, all_md), reverse=True)
            seen = {p for _, p in candidate_pages}
            for fb_score, fb_path in fb_ranked[:3]:
                if fb_path not in seen:
                    candidate_pages.append((fb_score, fb_path))

    if not candidate_pages:
        return None

    # ── Pass 4: Read pages within token budget (memory-query Step 6) ──────
    candidate_pages.sort(reverse=True)
    budget = max_tokens
    sections: list[str] = []

    for _, page_path in candidate_pages:
        content = _read_safe(page_path)
        if not content:
            continue
        cost = _estimate_tokens(content)
        if cost > budget:
            continue
        budget -= cost
        sections.append(f"## {page_path}\n\n{content.strip()}")

    if not sections:
        return None

    body = "\n\n---\n\n".join(sections)
    return (
        "[MEMORY CONTEXT — wiki pages retrieved at session start via BM25]\n\n"
        "Relevant context from your wiki. Use this knowledge to ground your response.\n"
        'Invoke skill("memory-query") if you need deeper synthesis or cross-topic search.\n\n'
        "---\n\n"
        f"{body}\n\n"
        "[END MEMORY CONTEXT]"
    )
