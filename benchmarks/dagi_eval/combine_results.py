"""Combine every run's result.jsonl under benchmarks/dagi_eval/logs/ into a
single spreadsheet for cross-run comparison.

Usage:
    conda run -n dagi python -m benchmarks.dagi_eval.combine_results \
        [--logs-dir PATH] [--out PATH]

Scans benchmarks/dagi_eval/logs/*/result.jsonl (one file per run folder, as
written by run.py's build_task_row/aggregate_row — see harness.new_run_dir())
and writes benchmarks/dagi_eval/logs/combined_result.xlsx with two sheets:

  all_rows        every per-task row + every "__aggregate__" row, from every
                   run, tagged with is_aggregate and source_dir columns.
  aggregates_only  just the "__aggregate__" rows, one per run — the fast
                   cross-run comparison view (coding_score/ds_score/
                   unified_score/tokens/wall_time per run).

Rows from different runs can have different columns (schema has grown over
time, e.g. agent_time_s/baseline_time_s added later) — pandas fills missing
cells with NaN rather than erroring, so older runs' rows just show blank in
newer columns.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

PKG_DIR = Path(__file__).parent
DEFAULT_LOGS_DIR = PKG_DIR / "logs"

# Column order for readability; any columns not listed here (schema drift
# across runs) are appended afterward in whatever order pandas discovers them.
PREFERRED_COLUMNS = [
    "source_dir", "is_aggregate", "run_id", "timestamp", "task", "kind",
    "model", "solver", "label",
    "recorded_score", "baseline_score", "golden_score",
    "agent_time_s", "baseline_time_s",
    "correct", "auc",
    "coding_score", "ds_score",
    "normalized_perf", "normalized_tokens", "unified_score",
    "wall_time_s", "tokens_in", "tokens_out", "tokens_think", "cost_usd",
    "iterations", "timed_out", "error", "errors",
    "dagi_git_commit", "dirty_tree",
]


def load_all_rows(logs_dir: Path) -> list[dict]:
    rows = []
    for result_path in sorted(logs_dir.glob("*/result.jsonl")):
        for line in result_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            row["source_dir"] = result_path.parent.name
            row["is_aggregate"] = row.get("task") == "__aggregate__"
            rows.append(row)
    return rows


def order_columns(df: pd.DataFrame) -> pd.DataFrame:
    known = [c for c in PREFERRED_COLUMNS if c in df.columns]
    rest = [c for c in df.columns if c not in known]
    return df[known + rest]


def build_combined(logs_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = load_all_rows(logs_dir)
    if not rows:
        raise SystemExit(f"no result.jsonl files found under {logs_dir}")
    all_df = order_columns(pd.json_normalize(rows))
    agg_df = order_columns(all_df[all_df["is_aggregate"]].copy())
    return all_df, agg_df


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--logs-dir", type=Path, default=DEFAULT_LOGS_DIR)
    ap.add_argument("--out", type=Path, default=None,
                    help="default: <logs-dir>/combined_result.xlsx")
    args = ap.parse_args()
    out_path = args.out or (args.logs_dir / "combined_result.xlsx")

    all_df, agg_df = build_combined(args.logs_dir)

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        all_df.to_excel(writer, sheet_name="all_rows", index=False)
        agg_df.to_excel(writer, sheet_name="aggregates_only", index=False)

    print(f"wrote {out_path} ({len(all_df)} rows across "
         f"{all_df['source_dir'].nunique()} runs, {len(agg_df)} aggregate rows)")


if __name__ == "__main__":
    main()
