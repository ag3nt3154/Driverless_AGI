# SPY 200-Day SMA Momentum Strategy — Backtest Report

**Period:** 1993-01-29 → 2026-04-24 (33.2 years, 8366 trading days)  
**Benchmark:** Buy-and-hold SPY (adjusted close)  
**Strategy:** Long SPY when adjclose > 200-day SMA; hold cash otherwise.  
**Execution lag:** 1 day (signal computed end-of-day, position entered next day).

---

## Performance Comparison

| Metric               | Momentum (200 SMA) | Buy & Hold SPY |
|:---------------------|:------------------:|:--------------:|
| Total Return         |        +1326.24% |        +2849.78% |
| CAGR                 |           +8.33% |          +10.72% |
| Annualized Volatility|          +11.98% |          +18.60% |
| Sharpe Ratio (Rf=0)  |             0.69 |             0.58 |
| Maximum Drawdown     |          -28.00% |          -55.19% |
| Number of Trades     |              216 |       Buy & Hold |

---

## Interpretation

The 200-day SMA rule captures long-run trend exposure while avoiding prolonged
drawdowns — whenever SPY closes below its 200-day average the strategy rotates
to cash, eliminating the worst crash periods at the cost of missing some
recovery rallies. Over the full sample the momentum approach produced
+1326.24% total return (+8.33% CAGR) versus
+2849.78% (+10.72% CAGR) for buy-and-hold, with an
annualized volatility of +11.98% vs +18.60% and a Sharpe ratio
of 0.69 vs 0.58. The maximum drawdown was
-28.00% vs -55.19% for the benchmark.

The strategy executed **216 round-trip trades** over the sample.
All figures use adjusted close prices (dividends and splits incorporated) so
the buy-and-hold series reflects a true total-return benchmark.
