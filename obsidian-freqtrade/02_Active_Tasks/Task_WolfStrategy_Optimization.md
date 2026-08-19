# TASK: Optimize WolfStrategy for $300 Capital Protection

## Status
- **Priority:** 🔴 CRITICAL
- **Stage:** V6.0 PLANNING — AWAITING IMPLEMENTATION
- **Current Version:** V5.90 (Prophet Wolf) — FAILED IN LIVE
- **Next Version:** V6.0 (Iron Wolf)

## Live Performance Alert (2026-04-27)
- ❌ Win Rate: **45.83%** (Target: >70%)
- ❌ Max Drawdown: **20.64%** (Target: <10%)
- ❌ ROI: **-9.27% Σ** (Target: +30-40%)
- 🔴 **STRATEGY IS IN DRAWDOWN — DO NOT ADD CAPITAL**

## V5.10 Objectives (Completed)
- [x] Reduce Drawdown to < 5%
- [x] Increase Win Rate to > 70%
- [x] Implement Wick Rejection filters
- [x] Implement RSI 1H Floor safety (40%)

## V6.0 Objectives (Iron Wolf)
- [x] FIX: Dead Code Override (long/short_precision_cond redefined)
- [x] FIX: Exit logic harmonized to 15m (not 1H)
- [x] FIX: Panic Sniper reversed Volume Climax logic
- [x] FIX: Stoploss tightened to -3.5% with trailing_stop
- [x] FIX: AI Score threshold raised to 0.02/-0.02
- [x] ADD: Emergency custom_exit when trade goes -2% against direction
- [x] BACKTEST: 01/04 - 27/04 → 7 trades, WinRate 57.1%, DD=4.25%, trailing_stop working!
- [ ] DRY-RUN: 48h on VPS before going live
- [ ] BACKTEST: Longer range 20/03 - 27/04 for full validation
- [ ] ANALYZE why only short entries appear and refine entry filters
## Links
- Post-mortem: [[Log_2026-04-27_V590_PostMortem]]
- V6.0 Plan: [[Plan_WolfStrategy_V6.0]]
- Old Log: [[Log_2026-04-16_Sniper_V5.10_Evolution]]
- Safety Checklist: [[Strategy_Safety_Checklist]]
