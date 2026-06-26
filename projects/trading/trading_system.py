#!/usr/bin/env python3
"""
SPY Moving Average Crossover Trading System
============================================
A complete backtesting system for the SPY ETF using a dual SMA crossover strategy.
Loads daily OHLCV data, optimizes parameters on a training set, evaluates on a
test set, and produces a performance report.

Usage:
    python projects/trading/trading_system.py
"""

import os
import sys
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).resolve().parent
DATA_PATH = PROJECT_DIR / "data" / "SPY_2026-04-25.csv"
REPORT_PATH = PROJECT_DIR / "report.md"
CHART_PATH = PROJECT_DIR / "equity_curve.png"

INITIAL_CAPITAL = 100_000.0
TRAIN_SPLIT = 0.80

# Grid search parameters
FAST_WINDOWS = [10, 20, 30, 50]
SLOW_WINDOWS = [100, 150, 200]

# Risk-free rate for Sharpe ratio
RF_RATE = 0.0

# Colour palette for charts
COLOUR_STRATEGY = "#1f77b4"
COLOUR_BENCHMARK = "#ff7f0e"


# ═══════════════════════════════════════════════════════════════════════════════
# Subtask 1: Data Loading & Exploration
# ═══════════════════════════════════════════════════════════════════════════════

def load_data(path: Path) -> pd.DataFrame:
    """Load and prepare SPY daily OHLCV data.

    Returns a DataFrame with a monotonic DatetimeIndex and an 'adjclose' column
    used for all return calculations.  Extra columns (dividends, stock_splits,
    capital_gains) are dropped.
    """
    df = pd.read_csv(
        path,
        parse_dates=["Date"],
        index_col="Date",
        dtype={
            "open": np.float64,
            "high": np.float64,
            "low": np.float64,
            "close": np.float64,
            "adjclose": np.float64,
            "volume": np.int64,
        },
    )
    # Sort ascending and ensure monotonic index
    df.sort_index(inplace=True)
    assert df.index.is_monotonic_increasing, "Index must be monotonic"

    # Drop columns we don't need for returns calculations
    drop_cols = [c for c in ["dividends", "stock_splits", "capital_gains"]
                 if c in df.columns]
    df.drop(columns=drop_cols, inplace=True)

    return df


def explore_data(df: pd.DataFrame) -> dict:
    """Compute summary statistics for the loaded data.

    Returns a dictionary of stats for the report.
    """
    stats = {
        "date_range": f"{df.index[0].date()} → {df.index[-1].date()}",
        "trading_days": len(df),
        "years": round((df.index[-1] - df.index[0]).days / 365.25, 1),
        "missing_values": int(df.isna().sum().sum()),
        "adjclose_first": round(float(df["adjclose"].iloc[0]), 2),
        "adjclose_last": round(float(df["adjclose"].iloc[-1]), 2),
        "adjclose_min": round(float(df["adjclose"].min()), 2),
        "adjclose_max": round(float(df["adjclose"].max()), 2),
        "avg_daily_volume": f"{int(df['volume'].mean()):,}",
    }
    return stats


# ── Utility functions ─────────────────────────────────────────────────────────

def compute_sma(series: pd.Series, window: int) -> pd.Series:
    """Compute simple moving average."""
    return series.rolling(window=window).mean()


def compute_daily_returns(prices: pd.Series) -> pd.Series:
    """Compute daily log returns from a price series."""
    return np.log(prices / prices.shift(1))


def compute_cagr(equity_curve: pd.Series, trading_days: int) -> float:
    """Compute Compound Annual Growth Rate.

    Uses 252 trading days per year.
    """
    total_return = equity_curve.iloc[-1] / equity_curve.iloc[0] - 1
    years = trading_days / 252.0
    if years <= 0:
        return 0.0
    return (1 + total_return) ** (1 / years) - 1


def compute_max_drawdown(equity_curve: pd.Series) -> tuple[float, float]:
    """Compute maximum drawdown as a fraction and the peak-to-trough return."""
    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max
    max_dd = float(drawdown.min())
    return max_dd, max_dd


def compute_sharpe(daily_returns: pd.Series, rf: float = RF_RATE) -> float:
    """Compute annualised Sharpe ratio from daily returns."""
    excess = daily_returns - rf / 252.0
    if excess.std() == 0 or excess.mean() == 0:
        return 0.0
    return float(np.sqrt(252) * excess.mean() / excess.std())


def compute_profit_factor(returns: pd.Series) -> float:
    """Profit factor = gross_profit / abs(gross_loss)."""
    gains = returns[returns > 0].sum()
    losses = returns[returns < 0].sum()
    if losses >= 0:
        return float("inf")
    return float(gains / abs(losses))


# ═══════════════════════════════════════════════════════════════════════════════
# Subtask 2: Strategy Implementation (MA Crossover)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_signals(prices: pd.Series, fast: int, slow: int) -> pd.Series:
    """Generate trading signals for a fast/slow MA crossover.

    Returns a Series with values:
        1 → long (fast MA > slow MA)
        0 → flat (fast MA <= slow MA)

    First ``slow`` periods are NaN because both MAs need to initialise.
    """
    assert fast < slow, f"fast ({fast}) must be < slow ({slow})"

    sma_fast = compute_sma(prices, fast)
    sma_slow = compute_sma(prices, slow)

    signals = pd.Series(np.where(sma_fast > sma_slow, 1.0, 0.0), index=prices.index)
    # NaN where either MA is NaN
    signals[sma_fast.isna() | sma_slow.isna()] = np.nan
    return signals


def apply_position_lag(signals: pd.Series) -> pd.Series:
    """Shift signals by 1 day to prevent lookahead bias.

    The position for day T is based on the signal at day T-1.
    """
    positions = signals.shift(1)
    # Forward-fill to handle NaN at the very start
    positions.ffill(inplace=True)
    positions.fillna(0, inplace=True)
    return positions


# ═══════════════════════════════════════════════════════════════════════════════
# Subtask 3: Backtesting Engine
# ═══════════════════════════════════════════════════════════════════════════════

def run_backtest(
    prices: pd.Series, positions: pd.Series
) -> dict:
    """Run a full backtest given price series and daily positions (0 or 1).

    Returns a dictionary with:
        - equity_curve: Series of portfolio value
        - daily_returns: Series of daily portfolio returns
        - trades: list of dicts (entry_date, exit_date, trade_return)
        - metrics: dict of performance metrics
    """
    # Daily strategy returns = position * asset return
    asset_returns = compute_daily_returns(prices)
    strategy_returns = positions.shift(0) * asset_returns  # already lagged

    # Equity curve
    equity = (1 + strategy_returns).cumprod() * INITIAL_CAPITAL
    equity.iloc[0] = INITIAL_CAPITAL

    # Extract individual trades
    trades = []
    in_trade = False
    entry_date = None
    entry_price = None

    for i in range(len(positions)):
        pos = positions.iloc[i]
        date = positions.index[i]

        if not in_trade and pos == 1:
            # Enter long
            in_trade = True
            entry_date = date
            entry_price = prices.iloc[i]
        elif in_trade and (pos == 0 or i == len(positions) - 1):
            # Exit long
            exit_date = date
            exit_price = prices.iloc[i]
            trade_return = (exit_price / entry_price) - 1
            trades.append({
                "entry_date": entry_date,
                "exit_date": exit_date,
                "trade_return": trade_return,
            })
            in_trade = False

    # Metrics
    trading_days = len(prices)
    n_trades = len(trades)
    winning_trades = [t for t in trades if t["trade_return"] > 0]
    losing_trades = [t for t in trades if t["trade_return"] <= 0]
    win_rate = len(winning_trades) / n_trades if n_trades > 0 else 0.0

    total_return = (equity.iloc[-1] / equity.iloc[0]) - 1
    cagr = compute_cagr(equity, trading_days)
    ann_vol = float(strategy_returns.std() * np.sqrt(252))
    sharpe = compute_sharpe(strategy_returns)
    max_dd, _ = compute_max_drawdown(equity)

    gross_profit = sum(t["trade_return"] for t in winning_trades)
    gross_loss = abs(sum(t["trade_return"] for t in losing_trades))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    metrics = {
        "total_return": total_return,
        "cagr": cagr,
        "annual_volatility": ann_vol,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "num_trades": n_trades,
        "trading_days": trading_days,
    }

    return {
        "equity_curve": equity,
        "daily_returns": strategy_returns,
        "trades": trades,
        "metrics": metrics,
    }


def run_buy_and_hold(prices: pd.Series) -> dict:
    """Run a buy-and-hold benchmark for comparison."""
    positions = pd.Series(1.0, index=prices.index)
    return run_backtest(prices, positions)


# ═══════════════════════════════════════════════════════════════════════════════
# Subtask 4: Parameter Optimisation & Benchmark Comparison
# ═══════════════════════════════════════════════════════════════════════════════

def grid_search(
    prices: pd.Series, fast_windows: list, slow_windows: list
) -> tuple[tuple[int, int], dict]:
    """Grid search over fast/slow MA parameters.

    Returns ((best_fast, best_slow), grid_results) where grid_results maps
    (fast, slow) -> metrics dict.
    """
    best_sharpe = -np.inf
    best_params = (None, None)
    grid_results: dict = {}

    for fast in fast_windows:
        for slow in slow_windows:
            if fast >= slow:
                continue
            signals = generate_signals(prices, fast, slow)
            positions = apply_position_lag(signals)
            result = run_backtest(prices, positions)
            sharpe = result["metrics"]["sharpe_ratio"]
            grid_results[(fast, slow)] = result["metrics"]

            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_params = (fast, slow)

    return best_params, grid_results


def plot_equity_curves(
    strategy_equity: pd.Series,
    benchmark_equity: pd.Series,
    fast: int,
    slow: int,
    save_path: Path,
) -> None:
    """Plot and save equity curve comparison."""
    fig, ax = plt.subplots(figsize=(12, 6))

    ax.plot(
        strategy_equity.index,
        strategy_equity.values,
        color=COLOUR_STRATEGY,
        linewidth=1.5,
        label=f"MA Crossover ({fast}/{slow})",
    )
    ax.plot(
        benchmark_equity.index,
        benchmark_equity.values,
        color=COLOUR_BENCHMARK,
        linewidth=1.5,
        alpha=0.8,
        label="Buy & Hold",
    )

    ax.set_title("Equity Curve Comparison (Test Set — Out of Sample)", fontsize=14)
    ax.set_xlabel("Date")
    ax.set_ylabel("Portfolio Value ($)")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)


# ═══════════════════════════════════════════════════════════════════════════════
# Subtask 5: Report Generation
# ═══════════════════════════════════════════════════════════════════════════════

def fmt_pct(value: float) -> str:
    """Format a decimal as a percentage string."""
    return f"{value * 100:.2f}%"


def fmt_float(value: float, decimals: int = 4) -> str:
    """Format a float with given decimals."""
    return f"{value:.{decimals}f}"


def generate_report(
    exploration_stats: dict,
    best_params: tuple[int, int],
    grid_results: dict,
    strategy_result: dict,
    benchmark_result: dict,
    train_start: str,
    train_end: str,
    test_start: str,
    test_end: str,
    save_path: Path,
) -> None:
    """Write the complete performance report to a markdown file."""
    s_m = strategy_result["metrics"]
    b_m = benchmark_result["metrics"]

    lines = []
    lines.append("# SPY Moving Average Crossover — Backtest Report\n")
    lines.append(f"> Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n")

    # ── 1. Executive Summary ──
    lines.append("## Executive Summary\n")
    lines.append(
        f"A dual simple-moving-average (SMA) crossover strategy was backtested on "
        f"SPY daily data from **{exploration_stats['date_range']}** "
        f"({exploration_stats['trading_days']:,} trading days, "
        f"~{exploration_stats['years']} years).\n"
    )
    lines.append(
        f"**Best parameters (selected on training set by Sharpe ratio):** "
        f"Fast SMA = {best_params[0]}, Slow SMA = {best_params[1]}\n"
    )
    lines.append(
        f"**Test period (out-of-sample):** {test_start} → {test_end}\n"
    )
    lines.append(
        f"On the out-of-sample test set, the strategy achieved a "
        f"**Sharpe ratio of {s_m['sharpe_ratio']:.2f}** "
        f"vs **{b_m['sharpe_ratio']:.2f}** for Buy & Hold, "
        f"with a **CAGR of {fmt_pct(s_m['cagr'])}** "
        f"vs **{fmt_pct(b_m['cagr'])}** for the benchmark.\n"
    )

    # ── 2. Data Overview ──
    lines.append("## Data Overview\n")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Date Range | {exploration_stats['date_range']} |")
    lines.append(f"| Trading Days | {exploration_stats['trading_days']:,} |")
    lines.append(f"| ~Years Covered | {exploration_stats['years']} |")
    lines.append(f"| Missing Values | {exploration_stats['missing_values']} |")
    lines.append(f"| Adj Close (First) | ${exploration_stats['adjclose_first']} |")
    lines.append(f"| Adj Close (Last) | ${exploration_stats['adjclose_last']} |")
    lines.append(f"| Adj Close Range | ${exploration_stats['adjclose_min']} – ${exploration_stats['adjclose_max']} |")
    lines.append(f"| Avg Daily Volume | {exploration_stats['avg_daily_volume']} |\n")

    # ── 3. Strategy vs Benchmark ──
    lines.append("## Strategy vs Benchmark (Test Set — Out of Sample)\n")
    lines.append("| Metric | MA Crossover | Buy & Hold | Delta |")
    lines.append("|--------|-------------|------------|-------|")

    def metric_row(name: str, s_val: float, b_val: float, is_pct: bool = False,
                   is_ratio: bool = False) -> str:
        if is_pct:
            s_s = fmt_pct(s_val)
            b_s = fmt_pct(b_val)
            delta = fmt_pct(s_val - b_val)
        elif is_ratio:
            s_s = fmt_float(s_val, 2)
            b_s = fmt_float(b_val, 2)
            delta = fmt_float(s_val - b_val, 2)
        else:
            s_s = fmt_float(s_val, 4)
            b_s = fmt_float(b_val, 4)
            delta = fmt_float(s_val - b_val, 4)
        return f"| {name} | {s_s} | {b_s} | {delta} |"

    lines.append(metric_row("Total Return", s_m["total_return"], b_m["total_return"], is_pct=True))
    lines.append(metric_row("CAGR", s_m["cagr"], b_m["cagr"], is_pct=True))
    lines.append(metric_row("Annual Volatility", s_m["annual_volatility"], b_m["annual_volatility"], is_pct=True))
    lines.append(metric_row("Sharpe Ratio", s_m["sharpe_ratio"], b_m["sharpe_ratio"], is_ratio=True))
    lines.append(metric_row("Max Drawdown", s_m["max_drawdown"], b_m["max_drawdown"], is_pct=True))
    lines.append(metric_row("Win Rate", s_m["win_rate"], b_m["win_rate"], is_pct=True))
    lines.append(metric_row("Profit Factor", s_m["profit_factor"], b_m["profit_factor"], is_ratio=True))
    lines.append(f"| Number of Trades | {s_m['num_trades']} | 1 (buy once) | — |\n")

    # ── 4. Equity Curve Chart ──
    lines.append("## Equity Curve\n")
    rel_chart_path = CHART_PATH.relative_to(PROJECT_DIR)
    lines.append(f"![Equity Curve]({rel_chart_path})\n")

    # ── 5. Parameter Grid ──
    lines.append("## Parameter Grid Results (Training Set — In Sample)\n")
    lines.append("| Fast SMA | Slow SMA | Sharpe Ratio | CAGR | Max DD | Win Rate | # Trades |")
    lines.append("|----------|----------|-------------|------|--------|----------|---------|")

    sorted_params = sorted(grid_results.items(), key=lambda x: x[1]["sharpe_ratio"], reverse=True)
    for (fast, slow), metrics in sorted_params:
        lines.append(
            f"| {fast} | {slow} "
            f"| {fmt_float(metrics['sharpe_ratio'], 2)} "
            f"| {metrics['cagr'] * 100:.1f}% "
            f"| {metrics['max_drawdown'] * 100:.1f}% "
            f"| {metrics['win_rate'] * 100:.0f}% "
            f"| {metrics['num_trades']} |"
        )
    lines.append("")

    # ── 6. Observations & Limitations ──
    lines.append("## Observations & Limitations\n")
    lines.append("- **Lookahead bias avoided:** All positions are lagged by 1 day relative to signals.")
    lines.append("- **No transaction costs:** Slippage and commissions are not modelled; real-world results would be lower.")
    lines.append("- **Long-only strategy:** The strategy only goes long or flat — no shorting.")
    lines.append("- **100% position sizing:** The model assumes full allocation on every signal, no position sizing or risk management.")
    lines.append("- **Single instrument:** Results are for SPY only. Diversification across sectors/asset classes is not considered.")
    lines.append("- **Parameter robustness:** The best parameters on the training set may not persist out of sample. Walk-forward analysis would improve confidence.")
    lines.append(f"- The classic golden cross ({10}/{200}) was included in the grid — the best parameters "
                 f"({best_params[0]}/{best_params[1]}) may differ.")

    report = "\n".join(lines) + "\n"
    save_path.write_text(report, encoding="utf-8")
    print(f"✓ Report saved to {save_path}")


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("SPY Moving Average Crossover — Trading System")
    print("=" * 60)

    # ── Subtask 1: Load & Explore ──
    print("\n[1/5] Loading and exploring data...")
    df = load_data(DATA_PATH)
    stats = explore_data(df)
    print(f"  • Date range: {stats['date_range']}")
    print(f"  • {stats['trading_days']:,} trading days ({stats['years']} years)")
    print(f"  • Adj Close: ${stats['adjclose_first']} → ${stats['adjclose_last']}")

    prices = df["adjclose"]

    # ── Train/Test Split ──
    split_idx = int(len(prices) * TRAIN_SPLIT)
    train_prices = prices.iloc[:split_idx]
    test_prices = prices.iloc[split_idx:]

    train_start = train_prices.index[0].strftime("%Y-%m-%d")
    train_end = train_prices.index[-1].strftime("%Y-%m-%d")
    test_start = test_prices.index[0].strftime("%Y-%m-%d")
    test_end = test_prices.index[-1].strftime("%Y-%m-%d")

    print(f"\n  Training set:   {train_start} → {train_end} ({len(train_prices)} days)")
    print(f"  Test set:       {test_start} → {test_end} ({len(test_prices)} days)")

    # ── Subtask 4 (includes 2 & 3): Grid Search ──
    print("\n[2/5] Running parameter grid search on training set...")
    best_params, grid_results = grid_search(train_prices, FAST_WINDOWS, SLOW_WINDOWS)
    print(f"  • Best: fast={best_params[0]}, slow={best_params[1]} "
          f"(Sharpe={grid_results[best_params]['sharpe_ratio']:.2f})")

    print("\n[3/5] Running MA crossover on test set...")
    test_signals = generate_signals(test_prices, best_params[0], best_params[1])
    test_positions = apply_position_lag(test_signals)
    strategy_result = run_backtest(test_prices, test_positions)

    print("\n[4/5] Running Buy & Hold benchmark...")
    benchmark_result = run_buy_and_hold(test_prices)

    # Print summary
    s_m = strategy_result["metrics"]
    b_m = benchmark_result["metrics"]
    print(f"\n  ┌─ {'Metric':<20} {'Strategy':>12} {'B&H':>12} ─┐")
    print(f"  │ {'Total Return':<20} {fmt_pct(s_m['total_return']):>12} {fmt_pct(b_m['total_return']):>12} │")
    print(f"  │ {'CAGR':<20} {fmt_pct(s_m['cagr']):>12} {fmt_pct(b_m['cagr']):>12} │")
    print(f"  │ {'Sharpe Ratio':<20} {s_m['sharpe_ratio']:>12.2f} {b_m['sharpe_ratio']:>12.2f} │")
    print(f"  │ {'Max DD':<20} {fmt_pct(s_m['max_drawdown']):>12} {fmt_pct(b_m['max_drawdown']):>12} │")
    print(f"  │ {'Win Rate':<20} {fmt_pct(s_m['win_rate']):>12} {fmt_pct(b_m['win_rate']):>12} │")
    print(f"  │ {'Trades':<20} {s_m['num_trades']:>12} {b_m['num_trades']:>12} │")
    print(f"  └─{'─'*46}─┘")

    # ── Chart ──
    print("\n[5/5] Generating equity curve chart and report...")
    plot_equity_curves(
        strategy_result["equity_curve"],
        benchmark_result["equity_curve"],
        best_params[0],
        best_params[1],
        CHART_PATH,
    )
    print(f"  • Chart saved to {CHART_PATH}")

    generate_report(
        exploration_stats=stats,
        best_params=best_params,
        grid_results=grid_results,
        strategy_result=strategy_result,
        benchmark_result=benchmark_result,
        train_start=train_start,
        train_end=train_end,
        test_start=test_start,
        test_end=test_end,
        save_path=REPORT_PATH,
    )

    print("\n" + "=" * 60)
    print("Done. Open report.md for full results.")
    print("=" * 60)


if __name__ == "__main__":
    main()