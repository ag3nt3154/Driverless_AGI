"""
BM25 wiki retrieval script for the memory-query skill.

Usage:
    python bm25_query.py --query "your question" --wiki-root "/path/to/dagi-memory" [--top-n 5]

Output: JSON array of {"score": float, "path": str} objects, ranked by relevance.
        If no matches are found, prints an empty array [].

The script uses BM25 scoring across wiki index.md files to surface the most relevant
pages for a given query without reading every file. Pass the output paths to `read`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add dagi root to sys.path so we can import from agent/
_DAGI_ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(_DAGI_ROOT))

from agent.memory_retriever import (
    _bm25_scores,
    _estimate_tokens,
    _parse_index_table,
    _read_safe,
)


def _rank_wiki(wiki_root: Path, query: str, top_n: int) -> list[dict]:
    """Return top-N ranked wiki pages as list of {score, path} dicts."""
    results: list[tuple[float, Path]] = []

    # Pass 1 — score topics in root index
    root_index = _read_safe(wiki_root / "index.md")
    if root_index:
        topic_rows = _parse_index_table(root_index)
        if topic_rows:
            topic_texts = [f"{slug} {desc}" for slug, desc in topic_rows]
            topic_scores = _bm25_scores(query, topic_texts)
            ranked_topics = sorted(zip(topic_scores, [r[0] for r in topic_rows]), reverse=True)

            # Pass 2 — drill into each topic index
            for topic_score, topic_slug in ranked_topics[:top_n]:
                topic_dir = wiki_root / topic_slug
                topic_index = _read_safe(topic_dir / "index.md")
                if not topic_index:
                    continue
                page_rows = _parse_index_table(topic_index)
                if not page_rows:
                    # No page table — treat the topic index itself as a candidate
                    results.append((topic_score, topic_dir / "index.md"))
                    continue
                page_texts = [f"{slug} {desc}" for slug, desc in page_rows]
                page_scores = _bm25_scores(query, page_texts)
                page_ranked = sorted(zip(page_scores, [r[0] for r in page_rows]), reverse=True)
                for page_score, page_slug in page_ranked[:2]:
                    page_path = topic_dir / f"{page_slug}.md"
                    if not page_path.exists():
                        page_path = topic_dir / page_slug / "index.md"
                    if page_path.exists():
                        results.append((page_score, page_path))

    # Pass 3 — grep fallback if too few candidates
    if len(results) < 2:
        all_md = list(wiki_root.rglob("*.md")) if wiki_root.exists() else []
        fallback_texts = [p.stem + " " + (_read_safe(p) or "")[:400] for p in all_md]
        if fallback_texts:
            fb_scores = _bm25_scores(query, fallback_texts)
            seen = {p for _, p in results}
            for fb_score, fb_path in sorted(zip(fb_scores, all_md), reverse=True)[:top_n]:
                if fb_path not in seen:
                    results.append((fb_score, fb_path))

    results.sort(reverse=True)
    return [{"score": round(score, 4), "path": str(path)} for score, path in results[:top_n]]


def main() -> None:
    parser = argparse.ArgumentParser(description="BM25 wiki retrieval for memory-query")
    parser.add_argument("--query", required=True, help="Query string")
    parser.add_argument("--wiki-root", required=True, help="Absolute path to dagi-memory directory")
    parser.add_argument("--top-n", type=int, default=5, help="Maximum results to return (default: 5)")
    args = parser.parse_args()

    wiki_root = Path(args.wiki_root) / "wiki"
    if not wiki_root.exists():
        print(json.dumps([]))
        return

    results = _rank_wiki(wiki_root, args.query, args.top_n)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
