"""Matplotlib score-over-time graph for prompt optimization history."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path


def plot_history(
    iterations: list[dict],
    output_path: Path,
    title: str = "Prompt Optimization Progress",
) -> None:
    """
    Render score-over-time with per-point change annotations.
    Accepted iterations are green; rejected are grey.
    Saves PNG to output_path.
    """
    import matplotlib
    matplotlib.use("Agg")  # non-interactive backend — safe in scripts and subprocesses
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    if not iterations:
        return

    timestamps = [datetime.fromisoformat(r["timestamp"]) for r in iterations]
    scores = [r["score"] for r in iterations]
    accepted = [r["accepted"] for r in iterations]
    changes = [r["change_description"] or "Initial evaluation" for r in iterations]

    fig, ax = plt.subplots(figsize=(14, 6))

    # Plot accepted (green) and rejected (grey) separately for legend
    acc_x = [t for t, a in zip(timestamps, accepted) if a]
    acc_y = [s for s, a in zip(scores, accepted) if a]
    rej_x = [t for t, a in zip(timestamps, accepted) if not a]
    rej_y = [s for s, a in zip(scores, accepted) if not a]

    ax.plot(timestamps, scores, color="#aaaaaa", linewidth=1, zorder=1)
    if rej_x:
        ax.scatter(rej_x, rej_y, color="#999999", s=60, zorder=2, label="Rejected")
    if acc_x:
        ax.scatter(acc_x, acc_y, color="#2ecc71", s=80, zorder=3, label="Accepted")

    # Best score dashed line
    best_score = max(scores)
    ax.axhline(best_score, linestyle="--", color="#e74c3c", linewidth=1, alpha=0.7,
               label=f"Best: {best_score:.1%}")

    # Annotations — stagger y-offset to reduce overlap
    offsets = [0.04, 0.08]
    for i, (ts, score, change) in enumerate(zip(timestamps, scores, changes)):
        if not change or change == "optimizer_failed":
            continue
        y_off = offsets[i % len(offsets)]
        label = change[:60] + ("…" if len(change) > 60 else "")
        ax.annotate(
            label,
            xy=(ts, score),
            xytext=(0, int(y_off * 100)),
            textcoords="offset points",
            fontsize=6,
            rotation=40,
            ha="left",
            va="bottom",
            color="#444444",
            arrowprops=dict(arrowstyle="-", color="#cccccc", lw=0.5),
        )

    # Formatting
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate(rotation=30)

    ax.set_xlabel("Time")
    ax.set_ylabel("Accuracy")
    ax.set_title(title)
    ax.set_ylim(0, 1.15)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(axis="y", linestyle=":", alpha=0.5)

    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
