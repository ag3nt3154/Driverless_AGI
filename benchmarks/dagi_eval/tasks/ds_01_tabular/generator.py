"""Generate the frozen ds_01_tabular dataset. Run ONCE; outputs committed.

Labels are Bernoulli(p(x)) — irreducible noise, hard Bayes ceiling.
p(x) mixes 6 latent regimes (c1 tier x threshold on x1) with different
interactions per regime, plus high-cardinality signal, informative
missingness, redundant + noise columns, and a train-only leaky trap column.

Calibration: run, read the printed AUCs, adjust NOISE_SCALE (higher = lower
ceiling) and effect sizes until oracle ~0.90 and baseline in 0.65-0.72.

NOTE: helper functions below decompose the original single-`main()` generator
into smaller pieces (coding-standard discipline: CC<=8, <=5 positional
params, <=100 lines/fn). The sequence of `rng.*` draws is preserved EXACTLY
so the frozen dataset is bit-for-bit identical to the undecomposed version.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

TASK_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TASK_DIR.parents[3]))  # repo root

from benchmarks.dagi_eval.scoring import roc_auc  # noqa: E402

SEED = 42
N_TRAIN = 30000
N_TEST = 10000
# NOISE_SCALE and MAIN_COEFS were empirically calibrated in this environment
# (see task 10 self-test): the literal plan constant (NOISE_SCALE=1.1, no
# main-effect term) yielded oracle=0.82 / baseline=0.53 here, both below
# target. Raising NOISE_SCALE increases oracle (a larger additive noise draw
# widens the spread of the per-row true probability p, which increases
# roc_auc(y, p) since y is sampled directly from p — the opposite of "more
# noise = lower ceiling" naive intuition, but consistent with p being the
# literal generative probability rather than a marginal-over-noise Bayes
# ceiling). MAIN_COEFS adds a segment-unconditional linear term (main effect
# of x1, plus a tier indicator) so the linear baseline model has some
# globally-learnable signal instead of only segment-gated interactions.
NOISE_SCALE = 2.0
MAIN_COEFS = (1.5, 1.5)
RARE_LEVELS = 200


def _make_base_features(rng, n):
    """x1-x12 iid normal, x13 redundant with x1, x14/x15 pure noise."""
    X = {f"x{i}": rng.normal(0, 1, n) for i in range(1, 13)}
    X["x13"] = X["x1"] * 0.9 + rng.normal(0, 0.3, n)   # redundant with x1
    X["x14"] = rng.normal(0, 1, n)                     # pure noise
    X["x15"] = rng.normal(0, 1, n)                     # pure noise
    return X


def _make_groups(rng, n):
    """Account tier (3 levels) and high-cardinality campaign code."""
    tier = rng.integers(0, 3, n)
    campaign = rng.integers(0, RARE_LEVELS, n)
    return tier, campaign


def _base_logit(X, tier, campaign):
    """Pure (rng-free) segment-mixture logit, before missingness/noise."""
    campaign_signal = (campaign % 7 == 0).astype(float)
    seg = tier * 2 + (X["x1"] > 0.3).astype(int)       # 6 latent regimes
    logit = np.select(
        [seg == 0, seg == 1, seg == 2, seg == 3, seg == 4, seg == 5],
        [1.6 * X["x2"] * X["x3"],
         1.2 * np.sin(2.0 * X["x4"]) + 0.8 * X["x5"],
         1.4 * np.tanh(X["x6"] * X["x7"]),
         1.5 * (X["x8"] > 0.5).astype(float) * X["x9"],
         0.9 * X["x10"] / (1.0 + np.abs(X["x11"])),
         0.3 * X["x2"]])
    logit = logit + 1.1 * campaign_signal
    # segment-unconditional main effect: gives the linear baseline something
    # globally learnable (without it, every signal term is gated by a 6-way
    # segment split, and no single feature carries a stable marginal effect).
    logit = logit + MAIN_COEFS[0] * X["x1"] + MAIN_COEFS[1] * (tier == 1).astype(float)
    return logit


def _apply_missingness_and_noise(rng, n, logit):
    """Draw informative/uninformative missingness masks, then irreducible noise."""
    miss3 = rng.random(n) < (0.15 + 0.10 * (logit > 0))   # informative
    miss7 = rng.random(n) < 0.12                          # uninformative
    logit = logit + 0.7 * miss3.astype(float)
    logit = logit + rng.normal(0, NOISE_SCALE, n)          # irreducible noise
    return logit, miss3, miss7


def _make_trap(rng, y, n_train, n_test):
    """Train-only leaky trap column (audit_flag): leaks label in train, not test."""
    n = n_train + n_test
    trap = np.empty(n)
    trap[:n_train] = y[:n_train] * 1.2 + rng.normal(0, 1.0, n_train)
    trap[n_train:] = rng.normal(0, 1.0, n_test) + 0.6
    return trap


def _assemble_dataframe(parts):
    """Bundle-in dict avoids threading 8 related scalars/arrays as positional args."""
    X, tier, campaign = parts["X"], parts["tier"], parts["campaign"]
    miss3, miss7 = parts["miss3"], parts["miss7"]
    y, trap, n = parts["y"], parts["trap"], parts["n"]

    df = pd.DataFrame({k: np.round(v, 4) for k, v in X.items()})
    df["c1"] = np.array(["alpha", "beta", "gamma"])[tier]
    df["c2"] = np.array([f"v{v:03d}" for v in campaign])
    df["audit_flag"] = np.round(trap, 4)
    df.loc[miss3, "x3"] = np.nan
    df.loc[miss7, "x7"] = np.nan
    df.insert(0, "id", np.arange(1, n + 1))
    df["label"] = y
    return df


def _write_splits(df, task_dir, n_train):
    train, test = df.iloc[:n_train], df.iloc[n_train:]
    (task_dir / "public").mkdir(exist_ok=True)
    (task_dir / "hidden").mkdir(exist_ok=True)
    train.to_csv(task_dir / "public" / "train.csv", index=False)
    test.drop(columns=["label"]).to_csv(
        task_dir / "public" / "test_features.csv", index=False)
    test[["id", "label"]].to_csv(
        task_dir / "hidden" / "test_labels.csv", index=False)
    return train, test


def _calibrate_baseline_auc(task_dir, test):
    """Run baseline.py in a temp workspace against the fresh files."""
    with tempfile.TemporaryDirectory() as td:
        for f in ("train.csv", "test_features.csv"):
            (Path(td) / f).write_bytes((task_dir / "public" / f).read_bytes())
        (Path(td) / "solve.py").write_bytes(
            (task_dir / "hidden" / "baseline.py").read_bytes())
        subprocess.run([sys.executable, "solve.py"], cwd=td, check=True,
                       timeout=900)
        preds = pd.read_csv(Path(td) / "predictions.csv")
    labels = dict(zip(test["id"], test["label"]))
    order = preds["id"].tolist()
    return roc_auc([labels[i] for i in order], preds["probability"].tolist())


def _write_meta(task_dir, oracle, baseline):
    (task_dir / "hidden" / "meta.json").write_text(json.dumps(
        {"oracle_auc": round(oracle, 4), "baseline_auc": round(baseline, 4),
         "seed": SEED, "noise_scale": NOISE_SCALE}), encoding="utf-8")


def main():
    rng = np.random.default_rng(SEED)
    n = N_TRAIN + N_TEST

    X = _make_base_features(rng, n)
    tier, campaign = _make_groups(rng, n)
    logit = _base_logit(X, tier, campaign)
    logit, miss3, miss7 = _apply_missingness_and_noise(rng, n, logit)

    p = 1.0 / (1.0 + np.exp(-logit))
    y = (rng.random(n) < p).astype(int)
    trap = _make_trap(rng, y, N_TRAIN, N_TEST)

    df = _assemble_dataframe({"X": X, "tier": tier, "campaign": campaign,
                              "miss3": miss3, "miss7": miss7, "y": y,
                              "trap": trap, "n": n})
    train, test = _write_splits(df, TASK_DIR, N_TRAIN)

    oracle = roc_auc(y[N_TRAIN:].tolist(), p[N_TRAIN:].tolist())
    baseline = _calibrate_baseline_auc(TASK_DIR, test)
    _write_meta(TASK_DIR, oracle, baseline)
    print(f"oracle AUC={oracle:.4f}  baseline AUC={baseline:.4f}")


if __name__ == "__main__":
    main()
