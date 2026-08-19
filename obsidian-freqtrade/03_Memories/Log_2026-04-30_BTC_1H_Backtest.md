# Backtest Memory Log: BTC 1H Campaign Validation

**Date:** 2026-04-30
**Task:** Backtest WolfGoldenEMA on 1H BTC

## Summary of Changes
- Updated `config.json` to 1H timeframe.
- Set `pair_whitelist` to `["BTC/USDT:USDT"]` only.
- Fixed code errors in `WolfGoldenEMA.py` (missing `populate_exit_trend` and incorrect `custom_exit` signature).

## Backtest Results
- **Timerange:** 2025-11-01 to 2026-04-27 (177 days)
- **Timeframe:** 1H
- **Trades:** 0
- **Profit:** 0.0%

## Technical Analysis of Failure
Diagnostic scripts confirmed that `crossed_above(ema_9, ema_21)` never occurs while the *previous* candle RSI is below 35 on the 1H timeframe. The EMA crossover is too lagging; by the time it confirms a trend shift, RSI has already recovered above the strict 35 threshold.

## Important Decisions & Lessons
- Strict RSI filters (< 35) on higher timeframes (1H) combined with lagging indicators (EMA crosses) lead to 0 trade frequency.
- **Recommendation:** Use a lookback for RSI (e.g. "RSI was below 35 in the last 5 candles") or relax the RSI threshold to < 45-50 for confirmation entries.
