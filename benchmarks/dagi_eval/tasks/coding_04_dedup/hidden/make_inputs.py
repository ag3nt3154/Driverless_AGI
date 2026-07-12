"""Generate hidden inputs for coding_04_dedup. Seeded — deterministic."""
import random
import sys
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TASK_DIR.parents[3]))  # repo root

from benchmarks.dagi_eval._genutil import write_expected  # noqa: E402

SEED = 404
# Calibration knobs — naive cost is quadratic in N_DOCS (pairwise, with
# per-pair re-tokenization). Keep VOCAB >= N_DOCS*AVG_LEN/20 so the gold
# inverted index stays selective.
N_DOCS = 3000
VOCAB = 4000
AVG_LEN = 14


def _doc(rng, vocab_size, length):
    return " ".join(f"w{rng.randrange(vocab_size):05d}" for _ in range(length))


def _mutate(rng, text, n_edits):
    toks = text.split()
    for _ in range(n_edits):
        toks[rng.randrange(len(toks))] = f"w{rng.randrange(VOCAB):05d}"
    return " ".join(toks)


def _gen(rng, n_docs):
    lines = []
    i = 0
    while i < n_docs:
        base = _doc(rng, VOCAB, rng.randint(AVG_LEN - 4, AVG_LEN + 6))
        lines.append((f"doc{i:06d}", base))
        i += 1
        # ~30% of docs get 1-3 near-duplicate variants (1-2 token edits)
        if rng.random() < 0.3:
            for _ in range(rng.randint(1, 3)):
                if i >= n_docs:
                    break
                lines.append((f"doc{i:06d}", _mutate(rng, base, rng.randint(1, 2))))
                i += 1
    rng.shuffle(lines)
    return lines


def _write(path, lines):
    path.mkdir(parents=True, exist_ok=True)
    (path / "docs.tsv").write_text(
        "\n".join(f"{d}\t{t}" for d, t in lines) + ("\n" if lines else ""),
        encoding="utf-8")


def main():
    data = TASK_DIR / "hidden" / "data"
    cor = data / "correctness"

    _write(cor / "case_01_empty", [])
    _write(cor / "case_02_exact_dupes", [
        ("a", "the quick brown fox"), ("b", "the quick brown fox"),
        ("c", "totally different words here"),
    ])
    # threshold boundary: 3 shared / 5 union = 0.6 (edge IS a duplicate)
    _write(cor / "case_03_boundary", [
        ("a", "alpha beta gamma delta"), ("b", "alpha beta gamma epsilon"),
        ("c", "alpha beta gamma"),
    ])
    # transitive chain a~b, b~c but a!~c -> one 3-cluster
    _write(cor / "case_04_chain", [
        ("a", "t1 t2 t3 t4 t5"), ("b", "t1 t2 t3 t4 t6"),
        ("c", "t1 t2 t3 t6 t7"),
    ])
    _write(cor / "case_05_empty_docs", [
        ("a", "!!! ???"), ("b", "..."), ("c", "real words here"),
    ])
    _write(cor / "case_06_medium", _gen(random.Random(SEED + 6), 150))

    _write(data / "timing", _gen(random.Random(SEED), N_DOCS))

    write_expected(TASK_DIR)
    print("dedup data written")


if __name__ == "__main__":
    main()
