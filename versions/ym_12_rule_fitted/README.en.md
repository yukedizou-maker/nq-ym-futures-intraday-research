# Early Fitted YM Intraday Strategy | ~15-Year Simulated Return +1,384.98%, CAGR 19.71%

**English** · [中文版](README.md) · [Repository home](../../README.en.md)

This is a separate archive of the early **12-rule fitted strategy**, called “V2” in the original code heading. It is distinct from the later five-rule S/A portfolio featured on the repository home page. Their returns must not be combined. The code and result files have been reconciled. **All figures are historical simulations, not live performance or achievable-return claims.**

## Market data, rules and sizing

| Item | Archived specification |
|---|---|
| Instrument and data | CME E-mini Dow futures (YM), continuous-contract one-minute bars; local research materials identify Databento `GLBX.MDP3`, `ohlcv-1m`, `YM.v.0` |
| Period | September 23, 2011 to September 22, 2026; partial first and last years |
| Signals and holding time | Twelve rules (A, B, C, D, E, F, G, I, J, K, M, N5); entries at 09:30 or 09:45 New York time; scheduled exits usually at 09:45, 10:00 or 10:30; source code resolves competing signals |
| Initial equity | $50,000 |
| Main portfolio sizing | Margin budget per trade equals 30% of pre-trade equity; modeled margin per contract equals 9% of YM notional; integer contracts; average 4.11, maximum 9 contracts |
| Cost model | $2.50 commission per contract per side plus one adverse index point on each side; YM is $5 per point per contract, giving $15 round-trip cost per contract |
| Trade count | 1,652 completed portfolio trades across 1,631 distinct trading dates; not a count of broker order messages or fills |

The 30% figure is a **margin budget**, not a maximum-loss rule. The 9% margin rate is a research sizing assumption, not a historical exchange or broker margin schedule. The equity curve compounds net daily P&L; Sharpe and Sortino use daily equity changes. The model does not fully account for market capacity, impact or changing real-world margins.

## Main 30% margin-budget results

| Metric | Result |
|---|---:|
| Completed trades | **1,652** (973 winners, 663 losers, 16 flat) |
| Ending equity / net profit | **$742,490 / $692,490** |
| Total return / CAGR | **+1,384.98% / 19.71%** |
| Win rate / profit factor | 58.90% / 1.69 |
| Annualized daily Sharpe / Sortino | 1.75 / 1.68 |
| Maximum daily close-to-close equity drawdown | −12.76% |
| Average / maximum contracts | 4.11 / 9 |

![Simulated equity curves for four modes](results/backtest_30pct/equity_curves.png)

The same archive includes three comparators: independent one-contract trades across all 12 rules (2,132 trades, $145,730 net profit), one concurrent one-contract position (1,652 trades, $138,445), and one-contract resonance-only signals (167 trades, $19,480). They use different sizing and must not be added to the main portfolio return.

## Files

- [Original backtest code](code/backtest_12_rules_30pct.py): an unchanged extraction of the matching 907-line Notebook code cell, with no download API key. To run it, provide licensed YM one-minute Parquet data and edit `DATA_PATH` near the top. This reproduces the archived logic; it is not a lookahead-corrected production implementation.
- [30% portfolio summary](results/backtest_30pct/portfolio_summary.csv), [trade log](results/backtest_30pct/trades_MARGIN_30PCT.csv), [daily equity](results/backtest_30pct/equity_MARGIN_30PCT.csv), [yearly P&L](results/backtest_30pct/portfolio_yearly_pnl.csv), [monthly P&L](results/backtest_30pct/portfolio_monthly_pnl.csv), and [parameters](results/backtest_30pct/config.json). The folder also contains comparator, signal and diagnostic files.
- [Trade-level MAE/MFE](results/mae_100pct/all_trades_MAE_MFE.csv) and [winning-trade MAE chart](results/mae_100pct/winning_trade_MAE.png). **These MAE files come from a separate 100% margin-budget rerun, not the main 30% account simulation.**

Raw one-minute market data and the daily feature table containing many sampled vendor prices have not been redistributed. Other published files are results from the supplied archives or their matching code. No API key is included.

## Independent reconciliation and limitations

Locally, 3,866 trading-day feature rows were reconstructed from 5,089,241 YM one-minute bars and matched the archived feature table. Replaying the original strategy produced an exact match for all 1,652 main-portfolio trades in date, side, entry/exit times and prices, contract count, and net P&L. Trade-level results also reconcile with the summaries and equity curves across all four modes. The 1,652 MAE/MFE bar extrema matched a separate scan of the minute data. This establishes **arithmetic and archival consistency**, not out-of-sample validity or live executability.

1. `trade_days=1615` in `portfolio_summary.csv` counts dates with **nonzero net daily P&L**. The trade log contains **1,631 distinct dates with trades**; 16 have zero net P&L.
2. Before morning entry, the original code checks `rth_n >= 388` and same-day `current_inst_n == 1`; these use information from later that day. At least **71 days with a rule signal** were excluded by these retrospective checks. The return has not yet been recalculated using strictly pre-entry filters.
3. Archived TRAIN/VALID/TEST labels describe historical date splits. Source comments reference trigger counts from earlier work on the full 2011–2026 sample. There is no documented freeze of rule thresholds, so these labels do not establish independent out-of-sample testing.
4. Conflict resolution iterates over an unordered set. E/N5 attribution can swap on November 9, 2016 and July 1, 2022. Their side, timing and prices are the same, and sizing is not score-scaled, so the financial result in this replay is unaffected.
5. The 100% margin-budget MAE rerun reaches a theoretical **$605,532,880** ending equity and **26,011 contracts** on its largest trade. It has no realistic capacity constraint and is not a tradeable profit estimate. Its rows retain a misleading `MARGIN_30PCT` mode label; interpret this directory using the **100% budget** instead.

Next research steps: remove post-entry information from the valid-day filter, make conflict priority deterministic, and retest on genuinely untouched data with realistic execution capacity.
