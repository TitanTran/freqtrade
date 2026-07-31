import logging
import os
import sys
from freqtrade.strategy import IStrategy, merge_informative_pair
from freqtrade.enums import CandleType, RunMode
from pandas import DataFrame
import pandas as pd
import talib.abstract as ta
from datetime import datetime
from freqtrade.persistence import Trade
import numpy as np

# Make the sibling approval_queue module importable regardless of CWD.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import approval_queue  # noqa: E402
import market_positioning  # noqa: E402

logger = logging.getLogger(__name__)


class WolfStrategy(IStrategy):
    """
    IRON WOLF V7.0 — Smart Money Concept (SMC)

    Philosophy: Think like a Market Maker, NOT a retail trader.
    - LONG when SM sweeps liquidity at the bottom (stop hunt → accumulation)
    - SHORT when SM sweeps liquidity at the top (stop hunt → distribution)
    - Hold through the full wave, exit at structural reversal

    Core Signals:
    1. Liquidity Sweep (stop hunt candle) — PRIMARY signal
    2. Break of Structure (BOS) after sweep — CONFIRMATION
    3. Change of Character (CHoCH) — EARLY aggressive entry
    4. Volume footprint — SM always leaves volume traces

    V7.0 vs V6.0 changes:
    - REMOVED: FreqAI as entry gate (was bearish-biased, blocked all Longs)
    - REMOVED: EMA crossover as primary signal (lagging, follows not leads)
    - REMOVED: 3.5% tight stoploss (was getting stop-hunted by SM)
    - ADDED: Liquidity Sweep detection (the core SMC entry signal)
    - ADDED: Dynamic ATR-based stoploss (below sweep low)
    - ADDED: 4H structure-based exit (hold the full wave)
    - WIDENED: Stoploss to -6% to survive SM stop hunts
    """

    INTERFACE_VERSION = 3
    timeframe = "1h"
    can_short = True

    # ------------------------------------------------------------------
    # STARTUP WARMUP
    # The slowest indicator is the 1D EMA50: 50 daily candles == 1200 base
    # (1h) candles. The 4H EMA200 needs 200*4 == 800. Without enough warmup
    # the long informative EMAs stay NaN, silently disabling every regime
    # gate (struct_up / struct_dn / macro_*) and producing FALSE "0 trades"
    # backtests on short timeranges. 1200 + buffer for EMA convergence and
    # the 24-bar regime slope shift.
    # ------------------------------------------------------------------
    startup_candle_count: int = 1300

    # ------------------------------------------------------------------
    # PAIR WHITELIST GUARD
    # Out-of-sample testing (2026-06-08) proved the parameters are curve-fit to
    # BTC/ETH/BNB: on 8 unseen pairs the SAME logic over the SAME window lost
    # -37% (DD 41%) vs +32% on these three. This strategy is a BTC/ETH/BNB
    # specialist ONLY. The guard below hard-blocks entries on any other pair,
    # even if the config whitelist is changed or a dynamic pairlist is used.
    # ------------------------------------------------------------------
    # BNB removed 2026-06-19: its bearish signal edge is too thin (53% down-rate
    # / -0.76% fwd96h vs ETH 59% / -1.98%); fat-tailed counter-bounces hit the
    # wide ATR stop, dragging its trade win-rate to 31% and net P&L negative.
    # BTC/ETH-only lifts Jan-Jun +75.5%->+87.5% (PF 1.61->2.16, DD 22.8%->17.7%).
    ALLOWED_PAIRS = {"BTC/USDT:USDT", "ETH/USDT:USDT"}

    # ------------------------------------------------------------------
    # HUMAN-IN-THE-LOOP APPROVAL
    # When True (live/dry-run only), automatic signals are NOT executed
    # directly. They are queued for Telegram approval (Gemini gives an
    # advisory opinion, the human presses Approve/Reject). Backtesting and
    # hyperopt always run fully automatic so research is unaffected.
    # ------------------------------------------------------------------
    MANUAL_APPROVAL_REQUIRED = True
    AUTO_SIGNAL_TAGS = {"shark_long_1h", "shark_short_1h", "breakdown_short_1h", "retest_short_1h"}

    # ------------------------------------------------------------------
    # ENTRY FILTER CONFIG (recalibrated 2026-06-18)
    # The original entry stacked ~8 AND-conditions and fired only 1 trade in
    # 6 weeks out-of-sample (signal-starved). It was loosened (sweep no longer
    # mandatory, lower volume floor, wider RSI) and gated by a multi-factor
    # TREND-REGIME classifier so the bot only trades a clean directional regime
    # and sits out chop. All thresholds are named constants (no magic numbers).
    # ------------------------------------------------------------------
    ENABLE_LONG = True              # long side is the weak side; toggle off to go short-only
    ENABLE_SHORT = True
    # Breakdown (continuation) short: enter as price breaks a new low with
    # volume in a daily-bearish, sub-VWAP, sub-EMA200 context — catches the
    # down-leg EARLY instead of waiting for a bounce (rsi>RSI_SHORT_MIN).
    ENABLE_BREAKDOWN_SHORT = True
    BREAKDOWN_RSI_MIN = 35.0        # don't break-short into an already-exhausted bottom
    # Retest mode (phase 2, 2026-07-02): instead of market-entering ON the
    # breakdown candle (worst fill, eats false breakouts), the breakdown only
    # ARMS a level — entry TRIGGERS when price pulls back up to retest the
    # broken low and gets rejected (closes back below it). HTF gates are
    # re-evaluated at the trigger candle. False = legacy chase-the-break.
    # A/B validated (2026-07-02): bear +34%->+45% PF 1.66->1.93 DD 11.6->8.9,
    # bull/OOS unchanged. Deployed live 2026-07-02.
    ENTRY_MODE_RETEST = True
    RETEST_WINDOW_BARS = 12         # wait up to 12x 1H candles for the pullback
    RETEST_TOL_ATR = 0.25           # "touched the level" = high within 0.25 ATR below it
    # Macro side-switch: 1D structure picks WHICH side may trade at all, so the
    # bot is long-only in a sustained daily uptrend and short-only in a daily
    # downtrend, instead of shorting bull pullbacks / longing bear bounces.
    MACRO_SIDE_SWITCH = True
    # Side-switch timeframe. The 1D EMA21/50 structure barely flips (~2-3 weeks
    # lag to confirm a new trend), which made the bot miss the first leg of every
    # wave ("slow vs market"). Switching the side-gate to the faster 4H EMA50/200
    # structure reacts in days instead of weeks, at the cost of more whipsaw in
    # chop. Set False to fall back to the slower-but-cleaner 1D gate (A/B test).
    SIDE_SWITCH_USE_4H = True
    # ASYMMETRIC side-switch option (tested 2026-06-21, kept OFF): forcing longs
    # onto the slow 1D daily-bull gate did NOT clean-separate bull from bear —
    # the recent "bear" window has counter-rallies where the daily turns bull, so
    # 1D longs still fired and lost -24% with worse DD than the 4H gate. There is
    # no macro gate that captures the bull without also catching bear-rally longs.
    LONG_SIDE_USE_1D = False
    VOL_RATIO_MIN = 1.3             # was 1.5
    RSI_LONG_MAX = 72.0             # buy STRENGTH in a confirmed up-regime, not only dips (was 62 → starved longs)
    RSI_SHORT_MIN = 38.0
    # NOTE (2026-06-21): a fast short VWAP-reclaim exit was tested to cut the squeeze
    # losses that drove the Feb-Apr drawdown — it BACKFIRED at every threshold
    # (-3%/-6% loss, vol 1.2/1.5, VWAP margin). In a downtrend price oscillates
    # across VWAP constantly, so the exit churns out shorts that would recover to
    # the +25% target: bear PF 1.46->1.17, profit halved. CONFIRMED: this strategy's
    # short edge REQUIRES riding through rallies; reaction-exits cannot lower DD.
    # The only non-churning DD lever is overall leverage.
    # REJECTED (2026-07-31, scratch/ab_vwap_atr_exit.py): tried the ATR-normalized
    # version of the exact idea above (both long AND short), applied on the live
    # candle instead of waiting for the 4H macro flag. Same churn signature as the
    # 2026-06-21 fixed-% version, on all 3 windows: fewer deep losers but LOWER
    # profit factor everywhere, and W2_bull2025 flips a marginal +0.1%/PF1.05 into
    # -0.6%/PF0.47. CONFIRMED: it isn't the % vs ATR margin that was the problem —
    # ANY exit that reacts faster than the 4H-confirmed flag cuts trades that would
    # have recovered. Kept OFF; do not re-attempt without a genuinely different
    # invalidation signal (not a faster/tighter version of the same reclaim idea).
    ENABLE_VWAP_ATR_EMERGENCY_EXIT = False
    EMERGENCY_VWAP_RECLAIM_ATR = 1.0    # ATR beyond VWAP that counts as "structure lost"
    EMERGENCY_ROI_FLOOR_LONG = -0.075   # margin ROI floor before LONG emergency logic engages
    EMERGENCY_ROI_FLOOR_SHORT = -0.04   # margin ROI floor before SHORT emergency logic engages
    RSI_1D_LONG_MAX = 80.0
    RSI_4H_LONG_MAX = 75.0
    RSI_1D_SHORT_MIN = 20.0
    RSI_4H_SHORT_MIN = 25.0
    # Regime classifier (consensus: structure + slope + DMI direction + ADX)
    ADX_REGIME_MIN = 25.0
    DMI_PERIOD = 14
    REGIME_SLOPE_BARS = 24          # 1H bars (~6x 4H candles) for 4H EMA200 slope
    # Structure speed (2026-07-05): EMA50/EMA200 on 4H has ~33-day memory,
    # confirming trend changes weeks late and missing the first leg of
    # V-shaped recoveries. A/B matrix (scratch/ab_struct_speed.py) tested
    # 50/200 (baseline) vs 20/50 (fast) vs 25/99 (chart-matched) across
    # bear-2026 + bull-2025 + 6-pair OOS. 25/99 won on nearly every axis:
    # bear +45%->+67% PF 1.93->2.35 at the SAME 8.9% DD (20/50 raised bear DD
    # to 12.7%), bull +2.2%->+13.9% PF 1.06->1.37 DD 17.4%->13.6%. OOS stays
    # PF<1 regardless of pair (structural non-generalization, not fixable
    # here). Deployed live 2026-07-05. The fast/slow EMA pair used by both the
    # regime classifier structure check and the 4H side-switch gate stays
    # configurable here for future A/B tests.
    STRUCT_FAST_EMA_PERIOD = 25
    STRUCT_SLOW_EMA_PERIOD = 99

    # --- LONG calibration -----------------------------------------------
    # Counter-intuitive finding (2026-06-18): TIGHTENING the long entry made the
    # bot blind to bull markets (0 longs taken during the 2025-05..09 +40%/mo
    # ETH bull). The long entry is therefore kept LOOSE so it can catch uptrends;
    # the discrimination is done by REGIME PERSISTENCE instead — an up-regime
    # must hold for several bars to count, which keeps the real 2025 bull but
    # rejects the flickering fake-ups of the 2026 chop. Shorts are unchanged.
    LONG_REQUIRE_SWEEP = False
    LONG_ADX_MIN = 0.0              # rely on the regime gate, not a 1H ADX floor
    LONG_VOL_RATIO_MIN = 1.0        # trend continuation doesn't need a volume spike (was 1.3 → starved longs)
    LONG_RSI_MIN = 0.0
    REGIME_PERSIST_BARS = 6         # up-regime must hold this many 1H bars (was 12; halved for faster bull capture)
    # With MACRO_SIDE_SWITCH on, the 1D structure already confirms the regime, so
    # the long entry can use the instantaneous up-regime (faster bull capture)
    # instead of the slower persistence-confirmed one. Tested False (instantaneous)
    # = great bull capture (+13%) but bleeds in non-bull (FULL -6%); the confirmed
    # gate is the robust choice on predominantly non-bull data.
    LONG_USE_CONFIRMED = True       # persistence-confirmed regime kills bear counter-trend longs (instantaneous bloated DD to 33%)
    # LONG earlier profit-taking (bank the move before the market reverses)
    LONG_TP_ROI = 0.20              # ride the bull (~4% price at x5); was 0.12, too tight to capture uptrends
    LONG_TP_EARLY_ROI = 0.06        # early exit floor when overbought
    LONG_TP_RSI = 78.0              # overbought threshold for early exit; raised so a strength-entry (rsi up to 72) doesn't insta-exit
    LONG_TP_FLIP_ROI = 0.04         # exit fast if 4H flips bearish while in profit

    # --- ENTRY VETO FILTERS (diagnosed 2026-07-02) ------------------------
    # Snapshot analysis of every entry candle across 2026 bear + 2025 bull
    # baselines (62 trades, scratch/diag_entry_snapshots.py) — thresholds are
    # data-picked, each flag independent for A/B:
    #
    # F1 LONG opposing-sweep veto: 67% of deep-losing longs (<= -12%) fired
    # while a 4H BEAR sweep was active (SM distributing into the rally) vs 9%
    # of the rest. Veto longs during an active bear_sweep_4h.
    # NOTE: the mirrored SHORT-side veto was tested and REJECTED — 36% of
    # deep-losing shorts had a bull sweep vs 44% of the healthy ones, so it
    # blocks more winners than losers. Long side only.
    # A/B validated: bear-2026 PF 1.34->1.40, bull-2025 -21%->-13%, OOS ~flat.
    ENABLE_LONG_SWEEP_VETO = True
    # F2 SHORT climax-volume veto: REJECTED by full A/B (2026-07-02), kept
    # OFF. The trade-level snapshot looked great (deep-losing shorts entered
    # on climactic vol-2x bars, blocked set summed to a net loss) but in the
    # real sequenced backtest it collapsed the bear-window edge +37%->-2%
    # (PF 1.34->0.98): the same high-volume bars also start the big winning
    # down-legs, and blocking an entry shifts it to a worse later candle.
    # Lesson: per-trade snapshot sums ignore re-entry sequencing — never
    # accept a filter without the full backtest matrix.
    ENABLE_SHORT_CLIMAX_VETO = False
    SHORT_VOL_RATIO_MAX = 2.0
    # F3 same-direction concurrency guard: BTC/ETH are ~0.9 correlated; the
    # 2025-06-23 backtest (-35% & -19%) and 2026-06-29 live (-15% & -15%)
    # disasters were both "same candle, both pairs, same side" double bets.
    # One position per direction at a time. Set to 0 to disable (A/B).
    # A/B validated: the strongest DD lever found so far — bear-2026 DD
    # 21.6%->14.8% (PF 1.34->1.52), bull-2025 flips -21%->+3%, OOS DD 66%->47%.
    # Combined with F1 (final config): bear +34% PF 1.66 DD 11.6%.
    MAX_SAME_DIRECTION_TRADES = 1
    # F4 EXTENSION VETO (designed 2026-07-06 from the live audit): the entry
    # stack is a confluence of LAGGING gates (1D trend + 4H structure + regime
    # persistence + rolling VWAP), so a trade fires the moment the SLOWEST
    # gate opens — i.e. at maximum lag, deep into the leg. All 3 live losses
    # (-19% account) carried this signature: entries sat >= 3.3 x ATR(4h)
    # away from the slow structural EMA (BTC short -3.5, ETH short -3.3,
    # ETH long +3.8). F4 refuses to enter an exhausted leg: longs only while
    # price <= +MAX x ATR(4h) above the slow EMA, shorts only while price
    # >= -MAX x ATR(4h) below it. Threshold 3.0 was chosen A PRIORI as the
    # loosest veto that still blocks the audit signature — deliberately NOT
    # grid-searched (the 2026 backtest window is exhausted; in-sample runs
    # are sanity checks only). Acceptance criterion: forward/dry-run sample.
    #
    # DISABLED 2026-07-31 (deliberate user decision, not a rejection): live
    # was on pace for ~1-1.6 trades/month on BTC/ETH, so the N=8-10 forward-
    # validation gate would take 5-8 months. scratch/ab_veto_ablation.py
    # showed F4 alone gates ~all of that — F1 costs ~0 frequency (and helps
    # PF), F5 is provably inert in-sample (see NOTE below). Disabling F4
    # alone (F1+F5 kept ON) matches turning off all three: bear2026 PF
    # 3.58->2.33, bull2025 PF 1.05->1.19, both still >1, frequency ~3.8-4.2
    # trades/month (N=8 in ~2 months instead of ~5-8). scratch/
    # ab_extension_threshold.py confirmed there is no safe middle threshold
    # (4.0 kills bull PF to 0.61 while fixing bear; noisy, regime-dependent,
    # not a real dial) — this is a binary choice, not a tunable one.
    # KNOWN, ACCEPTED COST: cross-referencing scratch/ab_veto_ablation
    # trades against the signals export, the 4 new deep losers in bear2026
    # all carry |extension_atr| 4.4-6.9 — i.e. disabling F4 reopens exactly
    # the >=3.3 ATR audit signature from the 3 historical live losses this
    # filter was built to block. Accepted in exchange for reaching
    # statistical read-out speed. Re-evaluate once N=8-10 live trades land.
    ENABLE_EXTENSION_VETO = False
    EXTENSION_MAX_ATR = 3.0
    # F5 POSITIONING VETO (designed 2026-07-09): don't JOIN a crowded trade.
    # Market makers hunt the crowd's stops, and the only two crowd-positioning
    # windows retail can read are the FUNDING RATE (freqtrade-native candle
    # type, works in backtest too) and OPEN INTEREST (public API, ~30 days of
    # history -> forward-validation only, per policy). Both flags independent
    # for A/B. Thresholds anchored to Binance's STRUCTURAL baseline (the
    # +0.01%/8h interest component), calibrated only against the FEATURE
    # distribution (2025-26: funding pins at +0.01% in normal bulls, never
    # exceeded +0.01%; negative tail p05 ~ -0.005%) — never against P&L
    # (the 2026 backtest window is exhausted; no grid-search allowed):
    # - LONG veto at >= 2x baseline (+0.02%/8h): true retail-mania premium
    #   (2024-style); has NOT fired in 18 months of data, so it is pure
    #   tail insurance and cannot re-starve the long side.
    # - SHORT veto at <= -1x baseline (-0.01%/8h): the interest component
    #   fully inverted = shorts paying heavily = crowded shorts (squeeze
    #   fuel); ~0.5-2% of hours in 2025-26.
    # - OI: >= 10% rise over 24h WITH price moving the same way = late-crowd
    #   pile-in; entering with them means being squeeze fuel. Majors carry a
    #   huge OI base, so 24h swings are small (20-day observed max +7.8% BTC
    #   / +4.2% ETH, p95 ~ +3-6%); 10% sits above ordinary flow but within
    #   reach of real pile-in events. Price deadband avoids classifying a
    #   flat drift as direction.
    # Fail-open: missing/unavailable data resolves to NEUTRAL (no veto).
    # Acceptance criterion: forward/dry-run sample, NOT in-sample backtests.
    ENABLE_FUNDING_VETO = True
    FUNDING_VETO_LONG_MAX = 0.0002      # veto longs at/above (crowd long)
    FUNDING_VETO_SHORT_MIN = -0.0001    # veto shorts at/below (crowd short)
    ENABLE_OI_VETO = True
    OI_LOOKBACK_BARS = 24               # 24 x 1h = 1 day of OI build-up
    OI_SURGE_PCT = 0.10                 # +10% OI in a day = crowded (majors)
    OI_PRICE_DEADBAND_PCT = 0.005       # <0.5% price move = no clear crowd side

    # --- Dynamic ATR stoploss (CLAUDE.md #4) -----------------------------
    # Replaces the old static 5-7% price stop (~7-10x ATR, far too wide) with a
    # volatility-scaled stop fixed at the entry candle (static, not trailing):
    # tighter in calm markets, wider in storms. Clamped so x5 leverage never
    # risks more than SL_MAX_PCT*5 of margin per trade.
    ATR_STOP_MULT = 4.5             # stop distance = N x ATR at entry (robust 3.5-4.5 plateau)
    SL_MIN_PCT = 0.015              # floor: 1.5% price move (=7.5% margin at x5)
    SL_MAX_PCT = 0.10               # ceiling: 10% price move (storm room to ride volatile trends)
    # NOTE (2026-06-21): a TIGHTER long-specific stop (3.0x/6%) was tested to cut
    # DD and BACKFIRED — bear longs went -12%->-36%, DD 23%->32%. A narrow stop in
    # choppy price gets hit at the bottom of a pullback, then the still-valid entry
    # signal re-enters and gets stopped again (churn). This strategy's edge depends
    # on a WIDE stop to avoid being shaken out; longs share the short stop band.
    LONG_ATR_STOP_MULT = 4.5
    LONG_SL_MAX_PCT = 0.10

    # --- Risk-based position sizing (custom_stake_amount) -----------------
    # config.json stake_amount="unlimited" only splits available balance
    # evenly across max_open_trades slots — it ignores how wide the current
    # ATR stop is, so a trade with a storm-wide stop and a trade with a calm
    # narrow stop risk the same $ amount at very different $ loss-if-stopped.
    # This sizes each trade so the $ loss AT the ATR stop equals a fixed
    # RISK_PER_TRADE_PCT of total equity, independent of volatility regime.
    ENABLE_RISK_BASED_SIZING = True
    RISK_PER_TRADE_PCT = 0.005      # 0.5% of equity risked per trade at the ATR stop

    # REJECTED (2026-07-31, scratch/ab_scaled_entry.py): a different lever
    # than the rejected fast-exit ideas above — instead of trying to CUT a
    # bad trade faster (proven to churn), take LESS risk on the entry itself.
    # Only SCALED_ENTRY_INITIAL_FRACTION fires at the trigger candle; the
    # rest tops up if a closed candle within SCALED_ENTRY_CONFIRM_BARS stays
    # on the correct side of VWAP and closes further in the trade's favor.
    # Also failed, on all 3 windows: bear2026 PF 3.58->2.32 with MORE deep
    # losers (1->2, not fewer), bull2025 PF 1.05->0.14 (near wipeout), OOS2026
    # flat (1.80->1.84) but paying extra entry fees/slippage for nothing.
    # Root cause: the confirmation bar is too easy to clear in a trending
    # market — almost every trade gets topped up to full size within 1
    # candle anyway, so it never actually discriminates a fast-reversal from
    # ordinary continuation. THIRD rejected reaction-based risk lever in a
    # row (with the 2026-06-21 and 2026-07-31 exit-speed ideas above) —
    # confirms the DD here is structural, not fixable by tuning entry/exit
    # reaction speed. Kept OFF; do not re-attempt without a genuinely
    # different mechanism (not faster-exit or smaller-entry).
    ENABLE_SCALED_ENTRY = False
    SCALED_ENTRY_INITIAL_FRACTION = 0.5   # fraction of the full risk-sized stake taken at trigger
    SCALED_ENTRY_CONFIRM_BARS = 2         # add-on must confirm within this many 1H candles

    # --- FAST-WIN conditional time-stop (đánh nhanh thắng nhanh) ---------
    # Trade-data finding (2026-06-21): every deep loser bled for DAYS before the
    # wide ATR stop fired — worst -31%/71h, -27%/66h, -26%/126h, one held 173h.
    # Meanwhile half the gross profit comes from winners that need >24h to mature
    # (some 85-117h), so capping winners would kill the edge. The asymmetric fix:
    # if a trade is STILL underwater after MAX_HOLD_HOURS the thesis has failed —
    # cut it and free the capital. Trades already in profit are never touched, so
    # the fat-tail winners are fully preserved. This shortens time-in-loss without
    # clipping the right tail.
    ENABLE_TIME_STOP = True
    MAX_HOLD_HOURS = 48.0           # give the down-leg time to mature (winners need 38-117h)
    TIME_STOP_MAX_LOSS = -0.12      # only cut DEEP losers (clearly failed), spare near-breakeven trades that recover

    # --- PROFIT-LOCK LADDER (user-requested 2026-07-02) -------------------
    # Stepped trailing floors on margin ROI: once the trade's PEAK profit
    # clears a rung by ARM_MARGIN, that rung becomes a hard floor — profit
    # falling back onto it exits immediately (e.g. peak 4.5% then 3.0% ->
    # exit at rung 3; peak 7.8% then 6.0% -> exit at rung 6). A floor, not a
    # cap: a trade that keeps running never gets touched. Peak comes from
    # trade.min_rate/max_rate which freqtrade updates BEFORE custom_exit in
    # both live and backtest (strategy/interface.py should_exit).
    # REJECTED by A/B (2026-07-02), kept OFF: winners average +21% ROI and
    # retrace through the 3-6% band repeatedly on the way there, so ANY
    # intermediate floor scalps them to ~+2% while losers (which never reach
    # +4.5% to arm a rung) stay untouched — bear PF 1.66->0.26, bull
    # +2%->-22%. Wider rungs 9/15/21 also failed (bear +45%->+4%, PF 1.10).
    # Structure-based profit protection (long_4h_flip, smc_4h_trend_flip_exit)
    # already banks profit at reversals without capping the fat tail.
    ENABLE_PROFIT_LOCK = False
    PROFIT_LOCK_RUNGS = (0.03, 0.06, 0.09)  # margin-ROI floors, ascending
    PROFIT_LOCK_ARM_MARGIN = 0.015          # rung arms once peak >= rung + margin

    # V9.0: SMC CORRECTED (x5 Leverage)
    # Target: 15-20% ROI per trade (Price move 3-4%)
    # Stoploss: 2-3% price move (10-15% margin risk)
    stoploss = -0.99  # Safety net. Set wide so custom_stoploss can work correctly.
    use_custom_stoploss = True
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    # Always on; adjust_trade_position() itself is a no-op unless
    # ENABLE_SCALED_ENTRY is True, so this has no effect while the flag is off.
    position_adjustment_enable = True
    max_entry_position_adjustment = 1   # exactly one top-up (the scaled-entry add-on)

    # Futures Leverage Configuration
    # Longs are the counter-trend regime bet (they bleed in a bear and drive DD);
    # running them at LOWER leverage caps their DD contribution proportionally
    # WITHOUT tightening the churn-prone price stop. Shorts — the robust trend
    # engine — keep full leverage.
    LONG_LEVERAGE = 3.0
    SHORT_LEVERAGE = 5.0

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: str,
                 side: str, **kwargs) -> float:
        lev = self.LONG_LEVERAGE if side == "long" else self.SHORT_LEVERAGE
        return float(min(lev, max_leverage))

    # Risk circuit breakers (cooldown + loss/drawdown guards)
    protections = [
        {"method": "CooldownPeriod", "stop_duration_candles": 4},
        {
            # Halt trading if too many stoplosses hit in a short window.
            "method": "StoplossGuard",
            "lookback_period_candles": 24,
            "trade_limit": 2,
            "stop_duration_candles": 12,
            "only_per_pair": False,
        },
        {
            # Halt all trading if portfolio drawdown breaches the threshold.
            "method": "MaxDrawdown",
            "lookback_period_candles": 48,
            "trade_limit": 4,
            "stop_duration_candles": 12,
            "max_allowed_drawdown": 0.20,
        },
    ]

    plot_config = {
        "main_plot": {
            "ema_20":            {"color": "#ff5733"},
            "ema_50":            {"color": "#335bff"},
            "ema_200":           {"color": "#ffc133"},
            "recent_high":       {"color": "#00ff88"},
            "recent_low":        {"color": "#ff0044"},
        },
        "subplots": {
            "RSI":    {"rsi": {"color": "#9b33ff"}},
            "Volume": {"volume_ratio": {"type": "bar", "color": "#00d2ff"}},
            "ADX":    {"adx": {"color": "#ff8800"}},
            "MFI":    {"mfi": {"color": "#00ffcc"}},
        },
    }

    # ------------------------------------------------------------------
    # ==========================================
    # PAIR GUARD: refuse any entry outside the validated whitelist
    # ==========================================
    def confirm_trade_entry(self, pair: str, order_type: str, amount: float,
                            rate: float, time_in_force: str, current_time: datetime,
                            entry_tag, side: str, **kwargs) -> bool:
        # 1) Pair guard — only the validated whitelist may ever trade.
        if pair not in self.ALLOWED_PAIRS:
            logger.warning(
                f"[PAIR GUARD] Entry on {pair} blocked — strategy is validated "
                f"for {sorted(self.ALLOWED_PAIRS)} only."
            )
            return False

        # 2) F3 concurrency guard — one position per direction. BTC/ETH move
        #    ~0.9 correlated, so two same-side positions are one doubled bet
        #    (both the 2025-06-23 and 2026-06-29 double losses). Runs in
        #    backtest too so its effect is measurable in A/B runs.
        if self.MAX_SAME_DIRECTION_TRADES > 0:
            same_direction_count = sum(
                1 for open_trade in Trade.get_trades_proxy(is_open=True)
                if open_trade.trade_direction == side
            )
            if same_direction_count >= self.MAX_SAME_DIRECTION_TRADES:
                logger.warning(
                    f"[CONCURRENCY GUARD] {pair} {side} blocked — "
                    f"{same_direction_count} open {side} trade(s) already."
                )
                return False

        # 3) Backtest / hyperopt: keep fully automatic so research is unaffected.
        if self.dp is None or self.dp.runmode.value not in ("live", "dry_run"):
            return True
        if not self.MANUAL_APPROVAL_REQUIRED:
            return True

        # 4) Force entries (human pressed Approve -> REST /forceenter) carry no
        #    dataframe signal tag, so they bypass the queue and execute.
        if entry_tag not in self.AUTO_SIGNAL_TAGS:
            logger.info(f"[APPROVAL] {pair} {side} manual/force entry accepted.")
            return True

        # 5) Automatic dataframe signal -> never trade directly; queue for approval.
        try:
            created = approval_queue.request_entry(
                pair, side, self._build_signal_context(pair, side, rate, entry_tag)
            )
            if created:
                logger.warning(f"[APPROVAL] {pair} {side} queued for manual approval.")
            else:
                logger.info(f"[APPROVAL] {pair} {side} already in-flight / cooldown.")
        except Exception as exc:  # noqa: BLE001 - never let approval plumbing crash the bot
            logger.error(f"[APPROVAL] failed to enqueue {pair} {side}: {exc}")
        return False

    def _build_signal_context(self, pair: str, side: str, rate: float,
                              entry_tag) -> dict:
        """Snapshot the lean decision dimensions for the human + Gemini advisor."""
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or len(dataframe) == 0:
            return {"pair": pair, "side": side, "rate": float(rate), "entry_tag": entry_tag}
        last = dataframe.iloc[-1]

        def num(col):
            value = last.get(col, None)
            return None if value is None or pd.isna(value) else float(value)

        def flag(col):
            return bool(last.get(col, False))

        return {
            "pair": pair,
            "side": side,
            "rate": float(rate),
            "entry_tag": entry_tag,
            # Momentum
            "rsi": num("rsi"), "rsi_4h": num("rsi_4h"), "rsi_1d": num("rsi_1d"),
            "macdhist": num("macdhist"),
            # Volatility
            "atr": num("atr"), "adx": num("adx"),
            # Volume
            "volume_ratio": num("volume_ratio"),
            # Structure (VWAP referee)
            "close": num("close"), "vwap": num("vwap"),
            "above_vwap": flag("above_vwap"), "below_vwap": flag("below_vwap"),
            "ema_200": num("ema_200"),
            # Higher-timeframe bias
            "macro_bullish_4h": flag("macro_bullish_4h"),
            "macro_bearish_4h": flag("macro_bearish_4h"),
            "trend_bullish_1d": flag("trend_bullish_1d"),
            "trend_bearish_1d": flag("trend_bearish_1d"),
            # F5 positioning (crowd read for the human + Gemini advisor)
            "funding_rate": num("funding_rate"),
            "oi_change_24h_pct": num("oi_change_pct"),
            "oi_crowded_long": flag("oi_crowded_long"),
            "oi_crowded_short": flag("oi_crowded_short"),
        }

    # ==========================================
    # CUSTOM STOPLOSS: ATR-based, below swing low
    # ==========================================
    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:

        # Dynamic ATR-based stop distance, fixed at the entry candle so the stop
        # stays static (no trailing) — see _atr_stop_pct.
        sl_pct = self._atr_stop_pct(pair, trade)

        # Freqtrade expects the return value relative to current_rate, but divides it by leverage.
        # To maintain a static price-based stop loss, we calculate the exact target price.
        if trade.trade_direction == "short":
            target_sl_price = trade.open_rate * (1 + sl_pct)
            return -trade.leverage * ((target_sl_price / current_rate) - 1)
        else:
            target_sl_price = trade.open_rate * (1 - sl_pct)
            return -trade.leverage * (1 - (target_sl_price / current_rate))

    def _atr_stop_pct(self, pair: str, trade: Trade) -> float:
        """Volatility-scaled stop distance as a fraction of price.

        Uses the ATR of the ENTRY candle (not the current one) so the stop is
        static and never trails. Tightens when ATR is small (calm market) and
        widens when ATR is large (volatility storm), clamped to a safe band so
        x5 leverage can never risk more than SL_MAX_PCT*leverage of margin.
        Falls back to the ceiling if ATR is unavailable.
        """
        # Long is the dangerous counter-trend side -> tighter multiple + ceiling.
        is_long = trade.trade_direction != "short"
        stop_ceil = self.LONG_SL_MAX_PCT if is_long else self.SL_MAX_PCT
        fallback = stop_ceil
        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe is None or len(dataframe) == 0:
                return fallback
            entry_time = getattr(trade, "open_date_utc", trade.open_date)
            at_entry = dataframe.loc[dataframe["date"] <= entry_time]
            if len(at_entry) == 0:
                return fallback
            atr = at_entry["atr"].iloc[-1]
            return self._atr_stop_pct_from_atr(atr, trade.open_rate, is_long)
        except Exception as exc:  # noqa: BLE001 - never let SL plumbing crash the bot
            logger.error(f"[ATR-SL] {pair} fallback to {fallback}: {exc}")
            return fallback

    def _atr_stop_pct_from_atr(self, atr: float, price: float, is_long: bool) -> float:
        """Shared ATR-stop-% math, given an already-looked-up ATR value.

        Factored out of _atr_stop_pct so custom_stake_amount can compute the
        SAME stop distance BEFORE the trade exists (no Trade object yet),
        keeping risk-based sizing consistent with the stop that will actually
        be set once the position opens.
        """
        stop_mult = self.LONG_ATR_STOP_MULT if is_long else self.ATR_STOP_MULT
        stop_ceil = self.LONG_SL_MAX_PCT if is_long else self.SL_MAX_PCT
        if pd.isna(atr) or price <= 0:
            return stop_ceil
        sl_pct = stop_mult * (float(atr) / float(price))
        return float(min(max(sl_pct, self.SL_MIN_PCT), stop_ceil))

    # ==========================================
    # CUSTOM STAKE AMOUNT: fixed %-equity risk at the ATR stop
    # ==========================================
    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                            proposed_stake: float, min_stake: float | None, max_stake: float,
                            leverage: float, entry_tag: str | None, side: str,
                            **kwargs) -> float:
        """Size the trade so $ loss AT the ATR stop == RISK_PER_TRADE_PCT of equity.

        margin_stake * sl_pct * leverage is the margin lost if the ATR stop
        fires; solving for margin_stake against a fixed $ risk budget makes
        realized risk constant across volatility regimes, instead of the
        default equal-split sizing where a storm-wide stop silently risks
        far more than a calm-market narrow stop for the same stake.
        """
        if not self.ENABLE_RISK_BASED_SIZING:
            return proposed_stake
        try:
            is_long = side != "short"
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe is None or len(dataframe) == 0 or leverage <= 0:
                return proposed_stake
            atr = dataframe["atr"].iloc[-1]
            sl_pct = self._atr_stop_pct_from_atr(atr, current_rate, is_long)
            if sl_pct <= 0:
                return proposed_stake
            equity = self.wallets.get_total_stake_amount()
            risk_amount = equity * self.RISK_PER_TRADE_PCT
            margin_stake = risk_amount / (sl_pct * leverage)
            if self.ENABLE_SCALED_ENTRY:
                # Only the initial slice fires here; adjust_trade_position()
                # tops up the rest if the next candle(s) confirm continuation.
                margin_stake *= self.SCALED_ENTRY_INITIAL_FRACTION
            if min_stake is not None:
                margin_stake = max(margin_stake, min_stake)
            return float(min(margin_stake, max_stake))
        except Exception as exc:  # noqa: BLE001 - never let sizing plumbing crash the bot
            logger.error(f"[RISK-SIZE] {pair} fallback to proposed_stake: {exc}")
            return proposed_stake

    # ==========================================
    # SCALED ENTRY: top up the partial initial stake once the setup confirms
    # ==========================================
    def adjust_trade_position(self, trade: Trade, current_time: datetime, current_rate: float,
                               current_profit: float, min_stake: float | None, max_stake: float,
                               current_entry_rate: float, current_exit_rate: float,
                               current_entry_profit: float, current_exit_profit: float,
                               **kwargs) -> float | None:
        """Add the remaining stake once a closed candle confirms continuation.

        No-op unless ENABLE_SCALED_ENTRY is True. custom_stake_amount() only
        fired SCALED_ENTRY_INITIAL_FRACTION of the full risk-sized stake at
        entry; this tops it up to full size, but ONLY if, within
        SCALED_ENTRY_CONFIRM_BARS candles, a closed candle both (a) stays on
        the correct side of VWAP (rule #3 applies to the add-on too) and
        (b) closes further in the trade's favor than the entry price. A setup
        that stalls or reverses within the confirmation window never gets the
        second half, capping the loss at the partial size instead of full.
        """
        if not self.ENABLE_SCALED_ENTRY or trade.nr_of_successful_entries != 1:
            return None
        try:
            hold_hours = (current_time - trade.open_date_utc).total_seconds() / 3600.0
            if hold_hours > self.SCALED_ENTRY_CONFIRM_BARS:
                return None  # confirmation window expired; stay at partial size

            dataframe, _ = self.dp.get_analyzed_dataframe(trade.pair, self.timeframe)
            if dataframe is None or len(dataframe) == 0:
                return None
            last = dataframe.iloc[-1]
            if last["date"] <= trade.open_date_utc:
                return None  # no new closed candle since entry yet

            vwap = float(last.get("vwap", current_rate) or current_rate)
            is_short = trade.trade_direction == "short"
            if is_short:
                confirmed = (last["close"] < vwap and last["close"] < trade.open_rate
                             and last["close"] < last["open"])
            else:
                confirmed = (last["close"] > vwap and last["close"] > trade.open_rate
                             and last["close"] > last["open"])
            if not confirmed:
                return None

            add_stake = trade.stake_amount * ((1.0 / self.SCALED_ENTRY_INITIAL_FRACTION) - 1.0)
            if min_stake is not None:
                add_stake = max(add_stake, min_stake)
            return float(min(add_stake, max_stake))
        except Exception as exc:  # noqa: BLE001 - never let sizing plumbing crash the bot
            logger.error(f"[SCALED-ENTRY] {trade.pair} top-up skipped: {exc}")
            return None

    def _profit_lock_floor(self, trade: Trade) -> float | None:
        """Highest armed profit-lock rung (margin ROI), or None if unarmed.

        A rung arms once the trade's PEAK profit cleared it by ARM_MARGIN.
        Peak is derived from the best rate seen (min_rate for shorts,
        max_rate for longs) so no extra state is needed; falls back to the
        open rate (peak 0) when the extremes are not yet recorded.
        """
        try:
            best_rate = trade.min_rate if trade.trade_direction == "short" else trade.max_rate
            if best_rate is None or pd.isna(best_rate):
                return None
            peak_profit = trade.calc_profit_ratio(best_rate)
        except Exception as exc:  # noqa: BLE001 - never let exit plumbing crash the bot
            logger.error(f"[PROFIT-LOCK] {trade.pair} peak calc failed: {exc}")
            return None
        armed = [rung for rung in self.PROFIT_LOCK_RUNGS
                 if peak_profit >= rung + self.PROFIT_LOCK_ARM_MARGIN]
        return max(armed) if armed else None

    # ==========================================
    # CUSTOM EXIT: SMC Wave Profit Maximizer
    # Philosophy: Let the wave run, exit when SM distributes
    # ==========================================
    def custom_exit(self, pair: str, trade: "Trade", current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs):
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or len(dataframe) == 0:
            return False

        # === FAST-WIN time-stop (both sides) ===
        # If the trade is still underwater after the hold window, the directional
        # thesis has not played out — free the capital instead of bleeding for
        # days. Profitable trades are exempt so the fat-tail winners run on.
        if self.ENABLE_TIME_STOP:
            hold_hours = (current_time - trade.open_date_utc).total_seconds() / 3600.0
            if hold_hours > self.MAX_HOLD_HOURS and current_profit < self.TIME_STOP_MAX_LOSS:
                return "fast_timestop"

        # === PROFIT-LOCK LADDER (both sides) ===
        # Highest armed rung is a hard floor; falling back onto it banks the
        # profit instead of round-tripping the whole move.
        if self.ENABLE_PROFIT_LOCK:
            lock_floor = self._profit_lock_floor(trade)
            if lock_floor is not None and current_profit <= lock_floor:
                return f"profit_lock_{lock_floor * 100:.0f}"

        last = dataframe.iloc[-1]
        bear_sweep   = bool(last.get("bear_sweep", False))
        bull_sweep   = bool(last.get("bull_sweep", False))
        macro_bear   = bool(last.get("macro_bearish_4h", False))
        macro_bull   = bool(last.get("macro_bullish_4h", False))
        rsi          = float(last.get("rsi", 50) or 50)
        mfi          = float(last.get("mfi", 50) or 50)
        rsi_4h       = float(last.get("rsi_4h", 50) or 50)
        volume_ratio = float(last.get("volume_ratio", 1.0) or 1.0)

        if trade.trade_direction == "long":
            # === VWAP-ATR EMERGENCY EXIT (A/B candidate, 2026-07-31) ===
            # Structure-invalidation exit that reacts on the CURRENT candle
            # instead of waiting for the 4H macro flag to close its candle.
            # NOTE: a fixed-%-margin version of this exact idea (short side)
            # was tested 2026-06-21 and REJECTED — see the NOTE above
            # RSI_SHORT_MIN: it churned out shorts that would have recovered
            # to the +25% target (bear PF 1.46->1.17). This ATR-normalized
            # variant is gated OFF by default; only flip ENABLE_VWAP_ATR_
            # EMERGENCY_EXIT on for the A/B script, never assume it wins.
            if self.ENABLE_VWAP_ATR_EMERGENCY_EXIT:
                vwap = float(last.get("vwap", current_rate) or current_rate)
                atr_1h = float(last.get("atr", 0.0) or 0.0)
                if (current_profit < self.EMERGENCY_ROI_FLOOR_LONG and atr_1h > 0
                        and current_rate < vwap - self.EMERGENCY_VWAP_RECLAIM_ATR * atr_1h):
                    logger.warning(f"[V9.1] {pair} LONG emergency: VWAP lost by "
                                    f"{(vwap - current_rate) / atr_1h:.2f} ATR")
                    return "smc_emergency_exit_vwap_atr"

            # === EMERGENCY EXIT ===
            # 4H turned bearish while we're losing: cut immediately (1.5% price move = 7.5% ROI)
            if current_profit < self.EMERGENCY_ROI_FLOOR_LONG and macro_bear and rsi < 38:
                logger.warning(f"[V9.0] {pair} LONG emergency: 4H bearish, RSI={rsi:.0f}")
                return "smc_emergency_exit"

            # === PRIMARY TARGET (banked early; market can reverse any time) ===
            if current_profit > self.LONG_TP_ROI:
                return "long_target_roi"

            # === EARLY OVERBOUGHT EXIT ===
            # Take profit on the first sign of exhaustion instead of waiting for
            # an extreme RSI that often never comes before the reversal.
            if current_profit > self.LONG_TP_EARLY_ROI and rsi > self.LONG_TP_RSI:
                return "long_overbought_early"

            # === 4H TREND FLIP: get out fast while still green ===
            if macro_bear and current_profit > self.LONG_TP_FLIP_ROI:
                return "long_4h_flip"

        if trade.trade_direction == "short":
            # === VWAP-ATR EMERGENCY EXIT (A/B candidate, see LONG side note) ===
            if self.ENABLE_VWAP_ATR_EMERGENCY_EXIT:
                vwap = float(last.get("vwap", current_rate) or current_rate)
                atr_1h = float(last.get("atr", 0.0) or 0.0)
                if (current_profit < self.EMERGENCY_ROI_FLOOR_SHORT and atr_1h > 0
                        and current_rate > vwap + self.EMERGENCY_VWAP_RECLAIM_ATR * atr_1h):
                    logger.warning(f"[V9.1] {pair} SHORT emergency: VWAP reclaimed by "
                                    f"{(current_rate - vwap) / atr_1h:.2f} ATR")
                    return "smc_emergency_exit_vwap_atr"

            # Emergency: 4H turned bullish while losing — cut FAST, don't wait
            # for a deep loss + extreme RSI (that confirmation arrives too late
            # and turned -7% shorts into -13/-18% in the June 2026 reversal).
            if current_profit < self.EMERGENCY_ROI_FLOOR_SHORT and macro_bull:
                logger.warning(f"[V9.0] {pair} SHORT emergency: 4H bullish, RSI={rsi:.0f}")
                return "smc_emergency_exit"

            # === TARGET ===
            if current_profit > 0.25:  # 25% ROI
                return "target_25pct_roi"

            # RSI extreme oversold (< 20) = SM accumulating at bottom
            if current_profit > 0.15 and rsi < 20:
                return "smc_rsi_extreme_exit"

            # RSI oversold + MFI low = distribution finished
            if current_profit > 0.20 and rsi < 28 and mfi < 25:
                return "smc_oversold_exit"

            # Bullish sweep at support = SM buying back in
            if current_profit > 0.10 and bull_sweep and rsi < 35:
                return "smc_sm_accumulation_exit"

            # 4H flipped bullish while profitable
            if current_profit > 0.10 and macro_bull:
                return "smc_4h_trend_flip_exit"

        return False

    # ==========================================
    # INFORMATIVE PAIRS
    # ==========================================
    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return (
            [(pair, "1d") for pair in pairs] +
            [(pair, "4h") for pair in pairs] +
            [(pair, "1h") for pair in pairs] +
            # F5: funding-rate candles (freqtrade-native candle type; the
            # rate value lands in the 'open' column). Binance stores funding
            # on the 1h grid (funding_fee_timeframe).
            [(pair, "1h", CandleType.FUNDING_RATE) for pair in pairs]
        )

    # ==========================================
    # F5 POSITIONING DATA (funding rate + open interest)
    # ==========================================
    def _merge_positioning(self, dataframe: DataFrame, pair: str) -> DataFrame:
        """Merge crowd-positioning series and derive the F5 crowd flags.

        Both series merge backward-asof (last value KNOWN at candle time —
        no lookahead) and default to NEUTRAL (0.0 / False) whenever data is
        missing, so the veto fails open instead of blocking or crashing.
        """
        # --- FUNDING RATE (native candle type; also available in backtest
        # because funding history ships with futures OHLCV downloads).
        funding = None
        try:
            funding = self.dp.get_pair_dataframe(
                pair=pair, candle_type=CandleType.FUNDING_RATE
            )
        except Exception as exc:  # noqa: BLE001 - positioning data must never crash the bot
            logger.warning(f"[F5] {pair} funding candles unavailable (veto neutral): {exc}")
        if funding is not None and len(funding) > 0:
            funding_series = funding[["date", "open"]].rename(
                columns={"open": "funding_rate"}
            )
            dataframe = pd.merge_asof(
                dataframe, funding_series, on="date", direction="backward"
            )
        else:
            dataframe["funding_rate"] = 0.0
        dataframe["funding_rate"] = dataframe["funding_rate"].fillna(0.0)

        # --- OPEN INTEREST (public exchange API; live/dry-run only — the
        # exchange keeps ~30 days, matching the forward-validation policy).
        oi_frame = pd.DataFrame()
        if self.dp is not None and self.dp.runmode.value in ("live", "dry_run"):
            oi_frame = market_positioning.oi_history(pair)
        if len(oi_frame) > 0:
            dataframe = pd.merge_asof(
                dataframe, oi_frame, on="date", direction="backward"
            )
        else:
            dataframe["open_interest"] = np.nan

        # 24h build-up of positioning and the price move that accompanied it.
        lookback = self.OI_LOOKBACK_BARS
        oi_prev = dataframe["open_interest"].shift(lookback)
        dataframe["oi_change_pct"] = (
            (dataframe["open_interest"] - oi_prev) / oi_prev.replace(0, np.nan)
        ).fillna(0.0)
        price_prev = dataframe["close"].shift(lookback)
        price_change = (
            (dataframe["close"] - price_prev) / price_prev.replace(0, np.nan)
        ).fillna(0.0)

        # Crowd flags: OI surged AND price moved with it -> the crowd piled
        # onto that side; entering WITH them is being squeeze fuel.
        oi_surge = dataframe["oi_change_pct"] >= self.OI_SURGE_PCT
        dataframe["oi_crowded_long"] = (
            oi_surge & (price_change > self.OI_PRICE_DEADBAND_PCT)
        ).fillna(False)
        dataframe["oi_crowded_short"] = (
            oi_surge & (price_change < -self.OI_PRICE_DEADBAND_PCT)
        ).fillna(False)

        dataframe["funding_crowded_long"] = (
            dataframe["funding_rate"] >= self.FUNDING_VETO_LONG_MAX
        ).fillna(False)
        dataframe["funding_crowded_short"] = (
            dataframe["funding_rate"] <= self.FUNDING_VETO_SHORT_MIN
        ).fillna(False)
        return dataframe

    # ==========================================
    # INDICATORS — SMC Framework
    # ==========================================
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:

        # ------------------------------------------------------------------
        # 0. DAILY BIAS (1D) — The Supreme Filter
        # Only LONG when Daily trend is UP. Only SHORT when Daily trend is DOWN.
        # This single filter prevents false longs during March 2026 downtrend.
        # ------------------------------------------------------------------
        inf_1d = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe="1d")
        inf_1d["ema_9"]   = ta.EMA(inf_1d, timeperiod=9)  # Faster response
        inf_1d["ema_21"]  = ta.EMA(inf_1d, timeperiod=21)
        inf_1d["ema_50"]  = ta.EMA(inf_1d, timeperiod=50)
        inf_1d["rsi"]     = ta.RSI(inf_1d, timeperiod=14)   # -> rsi_1d after merge

        # Daily bullish: price ABOVE daily EMA9 (Faster trend response)
        inf_1d["trend_bullish"] = (
            (inf_1d["close"] > inf_1d["ema_9"]) &
            (
                inf_1d["ema_21"].isna() |
                (inf_1d["ema_9"] > inf_1d["ema_21"])
            )
        )
        # Daily bearish: price BELOW daily EMA9
        inf_1d["trend_bearish"] = (
            (inf_1d["close"] < inf_1d["ema_9"]) &
            (
                inf_1d["ema_21"].isna() |
                (inf_1d["ema_9"] < inf_1d["ema_21"])
            )
        )
        dataframe = merge_informative_pair(dataframe, inf_1d, self.timeframe, "1d", ffill=True)
        # After merge: trend_bullish_1d, trend_bearish_1d, rsi_1d

        inf_4h = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe="4h")
        inf_4h["ema_20"]  = ta.EMA(inf_4h, timeperiod=20)
        inf_4h["ema_25"]  = ta.EMA(inf_4h, timeperiod=25)
        inf_4h["ema_50"]  = ta.EMA(inf_4h, timeperiod=50)
        inf_4h["ema_99"]  = ta.EMA(inf_4h, timeperiod=99)
        inf_4h["ema_200"] = ta.EMA(inf_4h, timeperiod=200)
        inf_4h["rsi"]     = ta.RSI(inf_4h, timeperiod=14)   # -> rsi_4h after merge
        inf_4h["adx"]     = ta.ADX(inf_4h, timeperiod=14)   # -> adx_4h after merge
        inf_4h["atr"]     = ta.ATR(inf_4h, timeperiod=14)   # -> atr_4h after merge

        # 4H Market Bias
        inf_4h["macro_bullish"] = (
            (inf_4h["close"] > inf_4h["ema_50"]) |
            (inf_4h["ema_20"] > inf_4h["ema_50"])
        )
        inf_4h["macro_bearish"] = (
            (inf_4h["close"] < inf_4h["ema_50"]) &
            (inf_4h["ema_20"] < inf_4h["ema_50"]) &
            (inf_4h["close"] < inf_4h["ema_200"])
        )

        # 4H Key Levels (Liquidity Pools — where retail stops cluster)
        sw4h = 8
        inf_4h["recent_high_4h_src"] = inf_4h["high"].rolling(sw4h, min_periods=1).max().shift(1)
        inf_4h["recent_low_4h_src"]  = inf_4h["low"].rolling(sw4h, min_periods=1).min().shift(1)

        # 4H Liquidity Sweep Detection
        # Bullish: price wicks below key low, closes back above = SM bought
        inf_4h["bull_sweep"] = (
            (inf_4h["low"]   < inf_4h["recent_low_4h_src"])  &
            (inf_4h["close"] > inf_4h["recent_low_4h_src"])  &
            (inf_4h["close"] > inf_4h["open"])
        )
        # Bearish: price wicks above key high, closes back below = SM sold
        inf_4h["bear_sweep"] = (
            (inf_4h["high"]  > inf_4h["recent_high_4h_src"]) &
            (inf_4h["close"] < inf_4h["recent_high_4h_src"]) &
            (inf_4h["close"] < inf_4h["open"])
        )
        # Keep 4H sweep signal for 3 candles (12H window)
        inf_4h["bull_sweep"] = inf_4h["bull_sweep"].rolling(3).max().fillna(0).astype(bool)
        inf_4h["bear_sweep"] = inf_4h["bear_sweep"].rolling(3).max().fillna(0).astype(bool)

        dataframe = merge_informative_pair(dataframe, inf_4h, self.timeframe, "4h", ffill=True)
        # merge_informative_pair renames: bull_sweep -> bull_sweep_4h, bear_sweep -> bear_sweep_4h
        # rsi_4h -> rsi_4h, adx_4h -> adx_4h, macro_bullish -> macro_bullish_4h, macro_bearish -> macro_bearish_4h
        # These are already correct — no alias needed.

        # ------------------------------------------------------------------
        # 2. WAVE STRUCTURE (1H) — Entry Zone Identification
        # ------------------------------------------------------------------
        inf_1h = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe="1h")
        inf_1h["ema_20"]         = ta.EMA(inf_1h, timeperiod=20)
        inf_1h["rsi_1h"]         = ta.RSI(inf_1h, timeperiod=14)
        inf_1h["adx_1h"]         = ta.ADX(inf_1h, timeperiod=14)
        inf_1h["volume_mean_1h"] = inf_1h["volume"].rolling(40, min_periods=1).mean()

        sw1h = 6
        inf_1h["recent_high_1h"] = inf_1h["high"].rolling(sw1h, min_periods=1).max().shift(1)
        inf_1h["recent_low_1h"]  = inf_1h["low"].rolling(sw1h, min_periods=1).min().shift(1)

        # 1H Liquidity Sweep
        inf_1h["bull_sweep_1h_src"] = (
            (inf_1h["low"]   < inf_1h["recent_low_1h"])  &
            (inf_1h["close"] > inf_1h["recent_low_1h"])  &
            (inf_1h["close"] > inf_1h["open"])
        )
        inf_1h["bear_sweep_1h_src"] = (
            (inf_1h["high"]  > inf_1h["recent_high_1h"]) &
            (inf_1h["close"] < inf_1h["recent_high_1h"]) &
            (inf_1h["close"] < inf_1h["open"])
        )
        # Keep 1H sweep for 4 candles (4H window)
        inf_1h["bull_sweep_1h_src"] = inf_1h["bull_sweep_1h_src"].rolling(4).max().fillna(0).astype(bool)
        inf_1h["bear_sweep_1h_src"] = inf_1h["bear_sweep_1h_src"].rolling(4).max().fillna(0).astype(bool)

        dataframe = merge_informative_pair(dataframe, inf_1h, self.timeframe, "1h", ffill=True)
        # merge_informative_pair renames: bull_sweep_1h_src -> bull_sweep_1h_src_1h
        # Create clean aliases:
        dataframe["bull_sweep_1h"] = dataframe["bull_sweep_1h_src_1h"].fillna(False).astype(bool)
        dataframe["bear_sweep_1h"] = dataframe["bear_sweep_1h_src_1h"].fillna(False).astype(bool)

        # ------------------------------------------------------------------
        # 3. MICRO EXECUTION (15m) — Precision Entry
        # ------------------------------------------------------------------
        dataframe["ema_9"]   = ta.EMA(dataframe, timeperiod=9)
        dataframe["ema_20"]  = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema_21"]  = ta.EMA(dataframe, timeperiod=21)  # Added for V8.1
        dataframe["ema_50"]  = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema_200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["rsi"]     = ta.RSI(dataframe, timeperiod=14)
        dataframe["atr"]     = ta.ATR(dataframe, timeperiod=14)
        dataframe["adx"]     = ta.ADX(dataframe, timeperiod=14)
        dataframe["mfi"]     = ta.MFI(dataframe, timeperiod=14)

        macd = ta.MACD(dataframe)
        dataframe["macd"]       = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"]   = macd["macdhist"]

        bb = ta.BBANDS(dataframe, timeperiod=20)
        dataframe["bb_upper"]  = bb["upperband"]
        dataframe["bb_lower"]  = bb["lowerband"]
        dataframe["bb_middle"] = bb["middleband"]

        # Volume
        dataframe["volume_mean"]  = dataframe["volume"].rolling(40, min_periods=1).mean()
        dataframe["volume_ratio"] = dataframe["volume"] / dataframe["volume_mean"].replace(0, 1)
        dataframe["volume_surge"] = dataframe["volume_ratio"] > 2.0  # 2x average = SM activity

        # ------------------------------------------------------------------
        # VWAP — Institutional referee (CLAUDE.md Rule #3).
        # Rolling session VWAP (no cumulative-from-start, no lookahead).
        # NEVER long below VWAP, NEVER short above VWAP.
        # ------------------------------------------------------------------
        vwap_window = 24  # 1 day on the 1h timeframe
        typical_price = (dataframe["high"] + dataframe["low"] + dataframe["close"]) / 3.0
        tp_volume = typical_price * dataframe["volume"]
        rolling_tp_volume = tp_volume.rolling(vwap_window, min_periods=1).sum()
        rolling_volume = dataframe["volume"].rolling(vwap_window, min_periods=1).sum().replace(0, np.nan)
        dataframe["vwap"] = (rolling_tp_volume / rolling_volume).fillna(dataframe["close"])
        dataframe["above_vwap"] = dataframe["close"] > dataframe["vwap"]
        dataframe["below_vwap"] = dataframe["close"] < dataframe["vwap"]

        # OBV — Smart Money footprint
        dataframe["obv"]        = ta.OBV(dataframe["close"], dataframe["volume"])
        dataframe["obv_ema_20"] = ta.EMA(dataframe["obv"], timeperiod=20)
        dataframe["obv_rising"] = dataframe["obv"] > dataframe["obv_ema_20"]

        # Candle anatomy
        dataframe["body_size"]  = abs(dataframe["close"] - dataframe["open"])
        dataframe["lower_wick"] = np.where(
            dataframe["close"] > dataframe["open"],
            dataframe["open"]  - dataframe["low"],
            dataframe["close"] - dataframe["low"]
        )
        dataframe["upper_wick"] = np.where(
            dataframe["close"] > dataframe["open"],
            dataframe["high"] - dataframe["close"],
            dataframe["high"] - dataframe["open"]
        )

        # ------------------------------------------------------------------
        # 4. SMC: 1H SWING LEVELS & LIQUIDITY SWEEPS (Main TF)
        # ------------------------------------------------------------------
        sw1h = 10
        dataframe["recent_high"] = dataframe["high"].rolling(sw1h, min_periods=1).max().shift(1)
        dataframe["recent_low"]  = dataframe["low"].rolling(sw1h, min_periods=1).min().shift(1)
 
        # Bullish Sweep (1h)
        dataframe["bull_sweep"] = (
            (dataframe["low"]   < dataframe["recent_low"])    &
            (dataframe["close"] > dataframe["recent_low"])    &
            (dataframe["close"] > dataframe["open"])          &
            (dataframe["lower_wick"] > dataframe["body_size"] * 0.3)
        )
 
        # Bearish Sweep (1h)
        dataframe["bear_sweep"] = (
            (dataframe["high"]  > dataframe["recent_high"])   &
            (dataframe["close"] < dataframe["recent_high"])   &
            (dataframe["close"] < dataframe["open"])          &
            (dataframe["upper_wick"] > dataframe["body_size"] * 0.3)
        )
 
        # Recent sweeps (within last 12 candles = 3H window)
        dataframe["bull_sweep_recent"] = dataframe["bull_sweep"].rolling(12).max().fillna(0).astype(bool)
        dataframe["bear_sweep_recent"] = dataframe["bear_sweep"].rolling(12).max().fillna(0).astype(bool)

        # ------------------------------------------------------------------
        # 5. BREAK OF STRUCTURE (BOS) — Trend Shift Confirmed
        # ------------------------------------------------------------------
        # Bullish BOS: After sweep, price breaks ABOVE recent high → trend flipped UP
        dataframe["bos_bullish"] = (
            (dataframe["close"] > dataframe["recent_high"]) &
            (dataframe["close"] > dataframe["open"])        &
            (dataframe["bull_sweep_recent"] | dataframe["bull_sweep_4h"]) &
            (dataframe["volume_ratio"] > 1.0)
        )

        # Bearish BOS: After sweep, price breaks BELOW recent low → trend flipped DOWN
        dataframe["bos_bearish"] = (
            (dataframe["close"] < dataframe["recent_low"])  &
            (dataframe["close"] < dataframe["open"])        &
            (dataframe["bear_sweep_recent"] | dataframe["bear_sweep_4h"]) &
            (dataframe["volume_ratio"] > 1.0)
        )

        # ------------------------------------------------------------------
        # 6. CHANGE OF CHARACTER (CHoCH) — Early Reversal Signal
        # ------------------------------------------------------------------
        prev_high_5 = dataframe["high"].rolling(5, min_periods=1).max().shift(2)
        prev_low_5  = dataframe["low"].rolling(5, min_periods=1).min().shift(2)

        dataframe["choch_bullish"] = (
            (dataframe["high"] > prev_high_5)       &
            (dataframe["close"] > dataframe["open"]) &
            (dataframe["bull_sweep_recent"] | dataframe["bull_sweep_4h"]) &
            (dataframe["volume_ratio"] > 1.2)  # Added Volume Filter to kill CHoCH noise
        )

        dataframe["choch_bearish"] = (
            (dataframe["low"]  < prev_low_5)         &
            (dataframe["close"] < dataframe["open"]) &
            (dataframe["bear_sweep_recent"] | dataframe["bear_sweep_4h"]) &
            (dataframe["volume_ratio"] > 1.2)  # Added Volume Filter to kill CHoCH noise
        )

        # ------------------------------------------------------------------
        # 7. TREND REGIME CLASSIFIER (consensus) — more accurate up/down.
        # A regime is only called UP (or DOWN) when ALL four orthogonal checks
        # agree, which sharply reduces false-trend calls during chop:
        #   1. STRUCTURE : 4H EMA pair (STRUCT_FAST_EMA_PERIOD/STRUCT_SLOW_EMA_PERIOD)
        #                  + price on the correct side.
        #   2. SLOPE     : the slow 4H EMA actually moving (not flat/ranging).
        #   3. DIRECTION : DMI +DI vs -DI — the directional info ADX lacks.
        #   4. STRENGTH  : 4H ADX above the trend floor.
        # No lookahead: slope uses past EMA values; DMI/ADX use closed candles.
        # ------------------------------------------------------------------
        plus_di  = ta.PLUS_DI(dataframe, timeperiod=self.DMI_PERIOD)
        minus_di = ta.MINUS_DI(dataframe, timeperiod=self.DMI_PERIOD)
        fast_col_name = f"ema_{int(self.STRUCT_FAST_EMA_PERIOD)}_4h"
        slow_col_name = f"ema_{int(self.STRUCT_SLOW_EMA_PERIOD)}_4h"
        ema_fast_4h_col = dataframe[fast_col_name] if fast_col_name in dataframe.columns else dataframe["ema_50"]
        ema_slow_4h_col = dataframe[slow_col_name] if slow_col_name in dataframe.columns else dataframe["ema_200"]
        adx_4h_col = dataframe["adx_4h"] if "adx_4h" in dataframe.columns else dataframe["adx"]

        struct_up = (ema_fast_4h_col > ema_slow_4h_col) & (dataframe["close"] > ema_fast_4h_col)
        struct_dn = (ema_fast_4h_col < ema_slow_4h_col) & (dataframe["close"] < ema_fast_4h_col)
        slope_up  = ema_slow_4h_col > ema_slow_4h_col.shift(self.REGIME_SLOPE_BARS)
        slope_dn  = ema_slow_4h_col < ema_slow_4h_col.shift(self.REGIME_SLOPE_BARS)
        trending  = adx_4h_col.fillna(0) > self.ADX_REGIME_MIN

        dataframe["regime_up"]   = (struct_up & slope_up & (plus_di > minus_di) & trending).fillna(False)
        dataframe["regime_down"] = (struct_dn & slope_dn & (minus_di > plus_di) & trending).fillna(False)

        # Persistence-confirmed regime: the gate must hold continuously for
        # REGIME_PERSIST_BARS bars. This separates a real, sustained trend from
        # chop that briefly flickers into an up/down reading. No lookahead
        # (rolling window only looks back).
        persist = self.REGIME_PERSIST_BARS
        dataframe["regime_up_confirmed"] = (
            dataframe["regime_up"].astype(int).rolling(persist, min_periods=persist).min().fillna(0).astype(bool)
        )
        dataframe["regime_down_confirmed"] = (
            dataframe["regime_down"].astype(int).rolling(persist, min_periods=persist).min().fillna(0).astype(bool)
        )

        # ------------------------------------------------------------------
        # EXTENSION (leg maturity) — ATR(4h)-normalized distance of price
        # from the slow structural EMA. Feeds the F4 extension veto: a large
        # positive value = up-leg already mature (late long = buying the top),
        # a large negative value = down-leg exhausted (late short = selling
        # the bottom). NaN-safe: unknown ATR (warmup) resolves to 0 = no veto;
        # the regime gates are NaN-gated during warmup anyway.
        # ------------------------------------------------------------------
        atr_4h_ext = dataframe["atr_4h"] if "atr_4h" in dataframe.columns else dataframe["atr"]
        dataframe["extension_atr"] = (
            (dataframe["close"] - ema_slow_4h_col) / atr_4h_ext.replace(0, np.nan)
        ).fillna(0.0)

        # ------------------------------------------------------------------
        # MACRO SIDE-SWITCH (1D structure) — decides which SIDE may trade.
        # Slow daily EMA21/EMA50 structure rarely flips (unlike the EMA9 cross),
        # so the bot stays long-only in a sustained daily uptrend and short-only
        # in a sustained daily downtrend, never fighting itself on pullbacks.
        # ------------------------------------------------------------------
        ema_21_1d_col = dataframe["ema_21_1d"] if "ema_21_1d" in dataframe.columns else dataframe["ema_21"]
        ema_50_1d_col = dataframe["ema_50_1d"] if "ema_50_1d" in dataframe.columns else dataframe["ema_50"]
        close_1d_col  = dataframe["close_1d"]  if "close_1d"  in dataframe.columns else dataframe["close"]
        dataframe["macro_bull_1d"] = (
            (close_1d_col > ema_50_1d_col) & (ema_21_1d_col > ema_50_1d_col)
        ).fillna(False)
        dataframe["macro_bear_1d"] = (
            (close_1d_col < ema_50_1d_col) & (ema_21_1d_col < ema_50_1d_col)
        ).fillna(False)

        # Faster 4H side-switch (structure EMA pair, speed set by
        # STRUCT_FAST_EMA_PERIOD/STRUCT_SLOW_EMA_PERIOD) — same directional
        # role as the 1D switch but confirms in days instead of weeks. Reuses
        # the 4H EMA columns already resolved for the regime classifier above.
        dataframe["macro_bull_4h_sw"] = (
            (ema_fast_4h_col > ema_slow_4h_col) & (dataframe["close"] > ema_fast_4h_col)
        ).fillna(False)
        dataframe["macro_bear_4h_sw"] = (
            (ema_fast_4h_col < ema_slow_4h_col) & (dataframe["close"] < ema_fast_4h_col)
        ).fillna(False)

        # Unified side gate — pick the timeframe per SIDE_SWITCH_USE_4H so the
        # entry logic stays agnostic and A/B switching is a one-line flag change.
        if self.SIDE_SWITCH_USE_4H:
            dataframe["side_short_ok"] = dataframe["macro_bear_4h_sw"]
            # Longs optionally forced onto the stricter 1D daily-bull gate.
            dataframe["side_long_ok"] = (
                dataframe["macro_bull_1d"] if self.LONG_SIDE_USE_1D
                else dataframe["macro_bull_4h_sw"]
            )
        else:
            dataframe["side_long_ok"]  = dataframe["macro_bull_1d"]
            dataframe["side_short_ok"] = dataframe["macro_bear_1d"]

        # ------------------------------------------------------------------
        # F5 POSITIONING (funding rate + open interest crowd flags)
        # ------------------------------------------------------------------
        dataframe = self._merge_positioning(dataframe, metadata["pair"])

        # ------------------------------------------------------------------
        # X-RAY LOGGING
        # ------------------------------------------------------------------
        last = dataframe.iloc[-1]
        logger.warning(
            f"[V7 SMC] {metadata['pair']} | "
            f"4H: {'BULL' if last.get('macro_bullish_4h') else 'BEAR' if last.get('macro_bearish_4h') else 'NEUT'} | "
            f"Sweep15m: {'BULL' if last.get('bull_sweep_recent') else 'BEAR' if last.get('bear_sweep_recent') else '-'} | "
            f"BOS: {'BULL' if last.get('bos_bullish') else 'BEAR' if last.get('bos_bearish') else '-'} | "
            f"RSI={last['rsi']:.0f} ADX={last['adx']:.0f} Vol={last['volume_ratio']:.1f}x | "
            f"Fund={last.get('funding_rate', 0.0) * 100:.4f}% "
            f"OI24h={last.get('oi_change_pct', 0.0) * 100:+.1f}% "
            f"Crowd: {'LONG' if last.get('oi_crowded_long') or last.get('funding_crowded_long') else 'SHORT' if last.get('oi_crowded_short') or last.get('funding_crowded_short') else '-'}"
        )

        return dataframe

    # ==========================================
    # EXIT TREND — Structure-based exit
    # ==========================================
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"]  = 0
        dataframe["exit_short"] = 0
        return dataframe

    # ==========================================
    # ENTRY TREND — SMC: Bias (HTF) + Trigger (LTF)
    # ==========================================
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"]  = 0
        dataframe["enter_short"] = 0

        has_volume = dataframe["volume"] > 0

        # ==========================================
        # LONG ENTRIES (SHARK HUNTING)
        # Context: 1D Bullish + 4H Bullish, gated by the UP trend-regime.
        # Trigger: VWAP-aligned pullback + volume + MACD turning up.
        # ==========================================
        long_bias = (
            (dataframe["trend_bullish_1d"]) &
            (dataframe["macro_bullish_4h"]) &
            (dataframe["rsi_1d"].fillna(50) < self.RSI_1D_LONG_MAX) &  # not buying the daily top
            (dataframe["rsi_4h"].fillna(50) < self.RSI_4H_LONG_MAX)    # not buying the 4H top
        )

        regime_up_gate = (
            dataframe["regime_up_confirmed"] if self.LONG_USE_CONFIRMED else dataframe["regime_up"]
        )
        shark_long = (
            has_volume &
            long_bias &
            regime_up_gate &                      # REGIME GATE (sustained or instantaneous)
            (dataframe["above_vwap"]) &           # VWAP RULE: never long below VWAP
            (dataframe["rsi"] < self.RSI_LONG_MAX) &              # need a pullback, not FOMO
            (dataframe["rsi"] > self.LONG_RSI_MIN) &              # but not a deep reversal dip
            (dataframe["adx"] > self.LONG_ADX_MIN) &              # real 1H trend strength
            (dataframe["volume_ratio"] > self.LONG_VOL_RATIO_MIN) &  # stronger volume proof
            (dataframe["macdhist"] > dataframe["macdhist"].shift(1))  # momentum turning up
        )
        if self.LONG_REQUIRE_SWEEP:
            # Precision trigger: only long when a liquidity sweep printed.
            shark_long &= (dataframe["bull_sweep_recent"] | dataframe["bull_sweep"])
        if self.ENABLE_LONG_SWEEP_VETO:
            # F1: an active 4H bear sweep = SM distributing into this rally;
            # longing here is buying the trap (see ENTRY VETO FILTERS above).
            shark_long &= ~dataframe["bear_sweep_4h"].fillna(False).astype(bool)

        # ==========================================
        # SHORT ENTRIES (SHARK HUNTING)
        # Context: 1D Bearish + 4H Bearish, gated by the DOWN trend-regime.
        # ==========================================
        short_bias = (
            (dataframe["trend_bearish_1d"]) &
            (dataframe["macro_bearish_4h"]) &
            (dataframe["rsi_1d"].fillna(50) > self.RSI_1D_SHORT_MIN) &  # not shorting the daily bottom
            (dataframe["rsi_4h"].fillna(50) > self.RSI_4H_SHORT_MIN)    # not shorting the 4H bottom
        )

        shark_short = (
            has_volume &
            short_bias &
            (dataframe["regime_down"]) &          # REGIME GATE: only a clean down-regime
            (dataframe["below_vwap"]) &           # VWAP RULE: never short above VWAP
            (dataframe["close"] < dataframe["ema_200"]) &        # structural downtrend on 1H
            (dataframe["rsi"] > self.RSI_SHORT_MIN) &            # need a bounce, not chasing
            (dataframe["volume_ratio"] > self.VOL_RATIO_MIN) &   # above-average participation
            (dataframe["macdhist"] < dataframe["macdhist"].shift(1))  # momentum turning down
        )

        # ==========================================
        # BREAKDOWN SHORT (continuation) — short the down-leg as price breaks a
        # new low with volume, instead of waiting for a bounce (rsi>RSI_SHORT_MIN
        # like shark_short does). Still gated by a CONFIRMED regime_down to kill
        # fakeouts; the RSI floor avoids break-shorting an exhausted bottom that
        # V-reverses (which, with the wide ATR stop, caused -30%+ tail losses).
        # ==========================================
        breakdown_short = (
            has_volume &
            (dataframe["side_short_ok"]) &                       # HTF structure bearish (4h/1d per flag)
            (dataframe["regime_down"]) &                         # confirmed down-regime (kill noise)
            (dataframe["below_vwap"]) &                          # VWAP RULE
            (dataframe["close"] < dataframe["ema_200"]) &        # 1H downtrend
            (dataframe["close"] < dataframe["recent_low"]) &     # NEW LOW = breakdown
            (dataframe["close"] < dataframe["open"]) &           # bearish candle
            (dataframe["volume_ratio"] > self.VOL_RATIO_MIN) &   # participation
            (dataframe["macdhist"] < 0) &                        # momentum already down
            (dataframe["rsi"] > self.BREAKDOWN_RSI_MIN)          # not the exhausted bottom
        )

        if self.ENABLE_SHORT_CLIMAX_VETO:
            # F2: refuse to short a climactic (blow-off) volume bar — that bar
            # tends to END the down-leg, not extend it (see ENTRY VETO FILTERS).
            not_climax = dataframe["volume_ratio"] <= self.SHORT_VOL_RATIO_MAX
            shark_short &= not_climax
            breakdown_short &= not_climax

        # F4: extension veto — refuse to enter an exhausted leg (see ENTRY
        # VETO FILTERS). Applied to breakdown BEFORE retest derivation so an
        # over-extended breakdown never arms a retest level either.
        not_extended_up = dataframe["extension_atr"] <= self.EXTENSION_MAX_ATR
        not_extended_dn = dataframe["extension_atr"] >= -self.EXTENSION_MAX_ATR
        if self.ENABLE_EXTENSION_VETO:
            shark_long &= not_extended_up
            shark_short &= not_extended_dn
            breakdown_short &= not_extended_dn

        # F5: positioning veto — never JOIN a crowded side (see ENTRY VETO
        # FILTERS). Applied to breakdown BEFORE retest derivation so a
        # crowded breakdown never arms a retest level either.
        not_crowded_long = pd.Series(True, index=dataframe.index)
        not_crowded_short = pd.Series(True, index=dataframe.index)
        if self.ENABLE_FUNDING_VETO:
            not_crowded_long &= ~dataframe["funding_crowded_long"]
            not_crowded_short &= ~dataframe["funding_crowded_short"]
        if self.ENABLE_OI_VETO:
            not_crowded_long &= ~dataframe["oi_crowded_long"]
            not_crowded_short &= ~dataframe["oi_crowded_short"]
        shark_long &= not_crowded_long
        shark_short &= not_crowded_short
        breakdown_short &= not_crowded_short

        # ==========================================
        # RETEST SHORT (phase 2) — the breakdown above only ARMS the broken
        # level; the actual entry fires on the pullback candle that touches
        # the level from below and gets rejected (closes back under it).
        # ffill(limit=...) only looks back — no lookahead.
        # ==========================================
        breakdown_level = dataframe["recent_low"].where(breakdown_short)
        retest_level = breakdown_level.ffill(limit=self.RETEST_WINDOW_BARS)
        retest_short = (
            has_volume &
            retest_level.notna() &
            (~breakdown_short) &                                 # not the breakdown candle itself
            (dataframe["high"] >= retest_level - self.RETEST_TOL_ATR * dataframe["atr"]) &
            (dataframe["close"] < retest_level) &                # rejected: closed back below the level
            (dataframe["close"] < dataframe["open"]) &           # bearish rejection candle
            (dataframe["side_short_ok"]) &                       # HTF gates re-checked at trigger
            (dataframe["regime_down"]) &
            (dataframe["below_vwap"])
        )
        if self.ENABLE_EXTENSION_VETO:
            # F4 re-checked at the retest trigger candle, like the HTF gates.
            retest_short &= not_extended_dn
        # F5 re-checked at the retest trigger candle as well.
        retest_short &= not_crowded_short

        # Macro side-switch: only the side aligned with the HTF structure may fire
        # (4H or 1D per SIDE_SWITCH_USE_4H).
        if self.MACRO_SIDE_SWITCH:
            shark_long  &= dataframe["side_long_ok"]
            shark_short &= dataframe["side_short_ok"]

        # = ::::: ASSIGN ENTRIES ::::: =
        if self.ENABLE_LONG:
            dataframe.loc[shark_long,  ["enter_long",  "enter_tag"]] = (1, "shark_long_1h")
        if self.ENABLE_SHORT and self.ENABLE_BREAKDOWN_SHORT:
            if self.ENTRY_MODE_RETEST:
                dataframe.loc[retest_short, ["enter_short", "enter_tag"]] = (1, "retest_short_1h")
            else:
                dataframe.loc[breakdown_short, ["enter_short", "enter_tag"]] = (1, "breakdown_short_1h")
        if self.ENABLE_SHORT:
            dataframe.loc[shark_short, ["enter_short", "enter_tag"]] = (1, "shark_short_1h")

        return dataframe
