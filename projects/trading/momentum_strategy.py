#!/usr/bin/env python3
# momentum_strategy.py
# Backtest a 200-day SMA trend-following strategy on SPY,
# compare to buy-and-hold, and emit a Markdown report.

import pandas as pd
import numpy as np

# ── 1. Load & sort data ─────────────────────────────────────────────────────
DATA_PATH = 'data/SPY_2026-04-25.csv'
REPORT_PATH = 'report.md'

df = pd.read_csv(DATA_PATH, parse_dates=['Date'])
df = df.sort_values('Date').reset_index(drop=True)

# ── 2. Compute daily returns and 200-day SMA ────────────────────────────────
df['daily_ret'] = df['adjclose'].pct_change()
df['sma200']    = df['adjclose'].rolling(window=200).mean()

# ── 3. Signal + 1-day execution lag ─────────────────────────────────────────
# raw_signal = 1 when adjclose > SMA200, else 0
df['raw_signal'] = (df['adjclose'] > df['sma200']).astype(int)
# lag by 1 day to avoid lookahead bias
df['position']   = df['raw_signal'].shift(1).fillna(0).astype(int)

# ── 4. Strategy returns ──────────────────────────────────────────────────────
df['strategy_ret'] = df['position'] * df['daily_ret']

# ── 5. Cumulative wealth curves ─────────────────────────────────────────────
df['strategy_cum']  = (1 + df['strategy_ret']).cumprod()
df['buyhold_cum']   = (1 + df['daily_ret']).cumprod()

# ── 6. Performance metrics ───────────────────────────────────────────────────
n = len(df)

total_ret_bh  = df['buyhold_cum'].iloc[-1] - 1
total_ret_str = df['strategy_cum'].iloc[-1] - 1

n_days = (df['Date'].iloc[-1] - df['Date'].iloc[0]).days
years  = n_days / 365.25

cagr_bh       = (1 + total_ret_bh)  ** (1 / years) - 1
cagr_str      = (1 + total_ret_str) ** (1 / years) - 1

vol_bh        = df['daily_ret'].std()  * np.sqrt(252)
vol_str       = df['strategy_ret'].std() * np.sqrt(252)

sharpe_bh     = cagr_bh  / vol_bh  if vol_bh  > 0 else 0.0
sharpe_str    = cagr_str / vol_str if vol_str > 0 else 0.0

max_dd_bh     = (df['buyhold_cum']  / df['buyhold_cum'].cummax() - 1).min()
max_dd_str    = (df['strategy_cum'] / df['strategy_cum'].cummax() - 1).min()

# Trades = number of times position changed
n_trades_str  = int((df['position'].diff() != 0).sum())

start_date = df['Date'].iloc[0].strftime('%Y-%m-%d')
end_date   = df['Date'].iloc[-1].strftime('%Y-%m-%d')

# ── 7. Write report.md ───────────────────────────────────────────────────────
def fmt(x):
    if isinstance(x, float):
        return f'{x:+.2%}'
    return str(x)

report = f'''# SPY 200-Day SMA Momentum Strategy — Backtest Report

**Period:** {start_date} → {end_date} ({years:.1f} years, {n} trading days)  
**Benchmark:** Buy-and-hold SPY (adjusted close)  
**Strategy:** Long SPY when adjclose > 200-day SMA; hold cash otherwise.  
**Execution lag:** 1 day (signal computed end-of-day, position entered next day).

---

## Performance Comparison

| Metric               | Momentum (200 SMA) | Buy & Hold SPY |
|:---------------------|:------------------:|:--------------:|
| Total Return         | {fmt(total_ret_str):>16} | {fmt(total_ret_bh):>16} |
| CAGR                 | {fmt(cagr_str):>16} | {fmt(cagr_bh):>16} |
| Annualized Volatility| {fmt(vol_str):>16} | {fmt(vol_bh):>16} |
| Sharpe Ratio (Rf=0)  | {sharpe_str:>16.2f} | {sharpe_bh:>16.2f} |
| Maximum Drawdown     | {fmt(max_dd_str):>16} | {fmt(max_dd_bh):>16} |
| Number of Trades     | {n_trades_str:>16} | {'Buy & Hold':>16} |

---

## Interpretation

The 200-day SMA rule captures long-run trend exposure while avoiding prolonged
drawdowns — whenever SPY closes below its 200-day average the strategy rotates
to cash, eliminating the worst crash periods at the cost of missing some
recovery rallies. Over the full sample the momentum approach produced
{fmt(total_ret_str)} total return ({fmt(cagr_str)} CAGR) versus
{fmt(total_ret_bh)} ({fmt(cagr_bh)} CAGR) for buy-and-hold, with an
annualized volatility of {fmt(vol_str)} vs {fmt(vol_bh)} and a Sharpe ratio
of {sharpe_str:.2f} vs {sharpe_bh:.2f}. The maximum drawdown was
{fmt(max_dd_str)} vs {fmt(max_dd_bh)} for the benchmark.

The strategy executed **{n_trades_str} round-trip trades** over the sample.
All figures use adjusted close prices (dividends and splits incorporated) so
the buy-and-hold series reflects a true total-return benchmark.
'''

with open(REPORT_PATH, 'w', encoding='utf-8') as f:
    f.write(report.strip() + '\n')

print(f'Report written to {REPORT_PATH}')