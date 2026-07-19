# Task: optimize the near-duplicate document detector

`dedup.py` finds clusters of near-duplicate documents. Make
`dedup.run(input_dir)` as fast as possible without changing its output.

## Contract
- Entry point: `dedup.run(input_dir: str) -> dict` (module name and signature
  fixed; internals free). Allowed: stdlib, numpy, pandas, scipy.
- Output must be exactly identical — note the output is canonically sorted, so
  the *order in which you discover pairs may change freely* as long as the
  resulting clusters are the same.

## Input
`<input_dir>/docs.tsv` — one document per line: `ID<TAB>TEXT`. Blank lines
are skipped.

## Definition
- Tokens: lowercase alphanumeric runs (`[a-z0-9]+` on the lowercased text),
  as a set.
- Two documents are near-duplicates when their token-set Jaccard similarity
  (|intersection| / |union|) is >= 0.6. Two documents with an empty union are
  NOT near-duplicates.
- Clusters: connected components of the near-duplicate relation with at
  least 2 members. Output: each cluster as a sorted ID list, clusters sorted;
  plus the document count.

## Scoring
Hidden inputs of the same format (larger). Score = baseline_runtime /
your_runtime. Any output mismatch = 0.
