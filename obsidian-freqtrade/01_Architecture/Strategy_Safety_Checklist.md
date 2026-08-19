# STRATEGY SAFETY CHECKLIST (ANTI-FAILURE PROTOCOL)

Before deploying or finalizing any Freqtrade strategy, perform this 5-point audit to ensure real-world reliability.

## 1. Anti-Lookahead Audit
- [ ] Are there any `.shift(-X)` where X is negative? (Instant Red Flag).
- [ ] Are labels for AI training only used in `set_freqai_targets` and NOT in `populate_indicators`?
- [ ] Does the backtest performance seem "too good to be true" (e.g., 100% win rate)? If so, re-check for lookahead.

## 2. Liquidity & Execution (The Reality Gap)
- [ ] Is the `stoploss` realistic for 5x leverage? (Current: ATR-based, V5.10).
- [ ] Are we trading pairs with high volume only (BTC, BNB)? 
- [ ] Have we accounted for 0.1% fee per side?

## 3. Market Regime Defense
- [ ] **V-Shape Reversal:** Is there a filter for RSI 1H < 40 for Shorts?
- [ ] **Flash Crash:** Is there a Wick Rejection filter (`wick > body`)?
- [ ] **Exhaustion:** Is there a Volume Climax filter (> 3x average)?

## 4. Coding Standards (Persona V2.0)
- [ ] Is all logic vectorized? (No `iterrows` or `for` loops in signals).
- [ ] Are Informative Pairs (1H) merged correctly using `ffill=True`?
- [ ] Are all custom indicators decoupled and modular?

## 5. Account Protection ($300 Benchmark)
- [ ] Max Drawdown in backtest must be < 10% for total safety.
- [ ] Is `leverage` hard-coded or dynamic with a safe cap? (Current: 5x).
- [ ] Is `CooldownPeriod` active after a stop-loss?

---
**Last Updated:** 2026-04-22
**Current Standard:** Sniper V5.10 Survivor Armor
