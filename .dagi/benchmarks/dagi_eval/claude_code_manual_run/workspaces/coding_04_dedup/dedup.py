"""Near-duplicate document detector. Contract: run(input_dir) -> dict.

Optimized: instead of comparing every pair of documents (O(n^2) tokenizations
and set operations), we build an inverted index mapping each token to the
documents containing it. Only documents that share at least one token can
possibly meet the Jaccard threshold, so we only ever compare "candidate"
pairs drawn from those posting lists, deduplicated so each pair is checked
once. This produces the exact same near-duplicate relation (and therefore
identical connected components / clusters) as the naive all-pairs approach,
since any true near-duplicate pair with similarity >= THRESHOLD > 0 must
share at least one token (a nonzero intersection is required to reach a
positive Jaccard score), and pairs sharing no tokens always have
intersection 0 and are correctly excluded either way.
"""
import re
from collections import defaultdict
from pathlib import Path

THRESHOLD = 0.6

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text):
    return set(_TOKEN_RE.findall(text.lower()))


def _parse_docs(input_dir):
    docs = []
    for line in Path(input_dir, "docs.tsv").read_text(
            encoding="utf-8").splitlines():
        if line.strip():
            doc_id, text = line.split("\t", 1)
            docs.append((doc_id, text))
    return docs


def _candidate_pairs(token_sets):
    """Yield index pairs (i, j) with i < j that share at least one token."""
    postings = defaultdict(list)
    for idx, toks in enumerate(token_sets):
        for tok in toks:
            postings[tok].append(idx)

    candidates = set()
    for idx_list in postings.values():
        m = len(idx_list)
        if m < 2:
            continue
        for a in range(m):
            i = idx_list[a]
            for b in range(a + 1, m):
                j = idx_list[b]
                candidates.add((i, j) if i < j else (j, i))
    return candidates


def _build_adjacency(docs):
    adj = {doc_id: set() for doc_id, _ in docs}
    n = len(docs)
    if n < 2:
        return adj

    token_sets = [_tokens(text) for _, text in docs]

    for i, j in _candidate_pairs(token_sets):
        a = token_sets[i]
        b = token_sets[j]
        union = len(a | b)
        if union and len(a & b) / union >= THRESHOLD:
            id_i = docs[i][0]
            id_j = docs[j][0]
            adj[id_i].add(id_j)
            adj[id_j].add(id_i)
    return adj


def _connected_components(adj, min_size=2):
    seen = set()
    clusters = []
    for doc_id in sorted(adj):
        if doc_id in seen:
            continue
        stack = [doc_id]
        comp = []
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            comp.append(cur)
            stack.extend(adj[cur] - seen)
        if len(comp) >= min_size:
            clusters.append(sorted(comp))
    return sorted(clusters)


def run(input_dir):
    docs = _parse_docs(input_dir)
    adj = _build_adjacency(docs)
    clusters = _connected_components(adj)
    return {"clusters": clusters, "n_docs": len(docs)}
