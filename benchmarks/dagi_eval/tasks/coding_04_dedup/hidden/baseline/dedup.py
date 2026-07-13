"""Near-duplicate document detector. Contract: run(input_dir) -> dict.

Naive reference: all-pairs comparison, O(n^2). The redundant re-tokenization
of the first document in each pair (present in the literal spec reference) is
hoisted out of the inner loop here since it is a trivial constant-factor
change that does not affect the asymptotic naive-vs-gold speedup story; the
second document in each pair is still re-tokenized on every comparison, and
the O(n^2) pairwise structure itself is unchanged.
"""
import re
from pathlib import Path

THRESHOLD = 0.6


def _tokens(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _parse_docs(input_dir):
    docs = []
    for line in Path(input_dir, "docs.tsv").read_text(
            encoding="utf-8").splitlines():
        if line.strip():
            doc_id, text = line.split("\t", 1)
            docs.append((doc_id, text))
    return docs


def _pair_is_dup(a, text_b):
    b = _tokens(text_b)
    union = len(a | b)
    return bool(union) and len(a & b) / union >= THRESHOLD


def _build_adjacency(docs):
    adj = {doc_id: set() for doc_id, _ in docs}
    n = len(docs)
    for i in range(n):
        a = _tokens(docs[i][1])
        for j in range(i + 1, n):                 # all pairs
            if _pair_is_dup(a, docs[j][1]):
                adj[docs[i][0]].add(docs[j][0])
                adj[docs[j][0]].add(docs[i][0])
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
