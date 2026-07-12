"""Gold: tokenize once, inverted-index candidate generation, size-ratio prune.

Only pairs sharing >= 1 token are compared (pairs sharing none have Jaccard 0
< 0.6). Size prune: Jaccard <= min(|A|,|B|)/max(|A|,|B|), so ratio < 0.6 pairs
are safely skipped. Cluster construction is identical to the naive version.
"""
import re
from collections import defaultdict
from pathlib import Path

THRESHOLD = 0.6


def _load_docs_and_tokens(input_dir):
    ids, toks = [], []
    for line in Path(input_dir, "docs.tsv").read_text(
            encoding="utf-8").splitlines():
        if line.strip():
            doc_id, text = line.split("\t", 1)
            ids.append(doc_id)
            toks.append(frozenset(re.findall(r"[a-z0-9]+", text.lower())))
    return ids, toks


def _build_inverted_index(toks):
    index = defaultdict(list)
    for i, ts in enumerate(toks):
        for t in ts:
            index[t].append(i)
    return index


def _candidates_for(i, a, index):
    cands = set()
    for t in a:
        cands.update(index[t])
    return {j for j in cands if j > i}


def _is_near_duplicate(a, b):
    len_a, len_b = len(a), len(b)
    small, big = (len_a, len_b) if len_a <= len_b else (len_b, len_a)
    if small / big < THRESHOLD:
        return False
    inter = len(a & b)
    return inter / (len_a + len_b - inter) >= THRESHOLD


def _link(adj, ids, i, j):
    adj[ids[i]].add(ids[j])
    adj[ids[j]].add(ids[i])


def _build_adjacency(ids, toks, index):
    adj = defaultdict(set)
    for i, a in enumerate(toks):
        if not a:
            continue
        for j in _candidates_for(i, a, index):
            if _is_near_duplicate(a, toks[j]):
                _link(adj, ids, i, j)
    return adj


def _connected_components(adj, ids, min_size=2):
    seen = set()
    clusters = []
    for doc_id in sorted(ids):
        if doc_id in seen or doc_id not in adj:
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
    ids, toks = _load_docs_and_tokens(input_dir)
    index = _build_inverted_index(toks)
    adj = _build_adjacency(ids, toks, index)
    clusters = _connected_components(adj, ids)
    return {"clusters": clusters, "n_docs": len(ids)}
