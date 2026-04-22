import argparse
import json
from datetime import datetime

import matplotlib.pyplot as plt
import matplotlib.dates as mdates


_MAX_LABEL_LEN = 40


def plot_history(history_path: str, output_path: str | None = None) -> None:
    with open(history_path, "r", encoding="utf-8") as f:
        history = json.load(f)

    # Filter out failed entries (score is None)
    valid = [h for h in history if h["score"] is not None]
    if not valid:
        print("No scored entries found in history.")
        return

    datetimes = [datetime.fromisoformat(h["datetime"]) for h in valid]
    scores = [h["score"] for h in valid]
    iterations = [h["iteration"] for h in valid]
    modifications = [h["modification"] for h in valid]

    best_score = max(scores)

    fig, ax = plt.subplots(figsize=(12, 6))

    # Separate seed from the rest
    seed_mask = [it == 0 for it in iterations]
    iter_mask = [it > 0 for it in iterations]

    seed_dates = [d for d, m in zip(datetimes, seed_mask) if m]
    seed_scores = [s for s, m in zip(scores, seed_mask) if m]
    iter_dates = [d for d, m in zip(datetimes, iter_mask) if m]
    iter_scores = [s for s, m in zip(scores, iter_mask) if m]

    if iter_dates:
        ax.plot(iter_dates, iter_scores, color="#4C72B0", linewidth=1.5, zorder=2)
        ax.scatter(iter_dates, iter_scores, color="#4C72B0", s=60, zorder=3, label="Iteration")

    if seed_dates:
        ax.scatter(
            seed_dates, seed_scores,
            color="white", edgecolors="#4C72B0", s=80, linewidth=2, zorder=4, label="Seed"
        )

    # Best score reference line
    ax.axhline(best_score, color="#DD8452", linestyle="--", linewidth=1, alpha=0.8, label=f"Best: {best_score:.4f}")

    # Annotate each point with truncated modification text
    for dt, score, mod in zip(datetimes, scores, modifications):
        label = mod if len(mod) <= _MAX_LABEL_LEN else mod[:_MAX_LABEL_LEN - 1] + "…"
        ax.annotate(
            label,
            xy=(dt, score),
            xytext=(6, 6),
            textcoords="offset points",
            fontsize=7,
            color="#444444",
            rotation=30,
            va="bottom",
        )

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    fig.autofmt_xdate(rotation=30)
    ax.set_xlabel("Time (UTC)")
    ax.set_ylabel("Score")
    ax.set_title("Prompt Optimization History")
    ax.set_ylim(-0.05, 1.1)
    ax.legend(loc="lower right")
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=150)
        print(f"Plot saved to {output_path}")
    else:
        plt.show()


def main():
    parser = argparse.ArgumentParser(description="Visualize prompt optimization history.")
    parser.add_argument("history", help="Path to history JSON file")
    parser.add_argument("--output", default=None, help="Save plot to this path (e.g. plot.png)")
    args = parser.parse_args()
    plot_history(args.history, args.output)


if __name__ == "__main__":
    main()
