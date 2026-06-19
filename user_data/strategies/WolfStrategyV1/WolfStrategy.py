import logging
import os
import sys
from freqtrade.strategy import IStrategy, merge_informative_pair
from freqtrade.enums import RunMode
from pandas import DataFrame
import pandas as pd
import talib.abstract as ta
from datetime import datetime
from freqtrade.persistence import Trade
import numpy as np

# Make the sibling approval_queue module importable regardless of CWD.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import approval_queue  # noqa: E402

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
    ALLOWED_PAIRS = {"BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT"}

    # ------------------------------------------------------------------
    # HUMAN-IN-THE-LOOP APPROVAL
    # When True (live/dry-run only), automatic signals are NOT executed
    # directly. They are queued for Telegram approval (Gemini gives an
    # advisory opinion, the human presses Approve/Reject). Backtesting and
    # hyperopt always run fully automatic so research is unaffected.
    # ------------------------------------------------------------------
    MANUAL_APPROVAL_REQUIRED = True
    AUTO_SIGNAL_TAGS = {"shark_long_1h", "shark_short_1h"}

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
    # Macro side-switch: 1D structure picks WHICH side may trade at all, so the
    # bot is long-only in a sustained daily uptrend and short-only in a daily
    # downtrend, instead of shorting bull pullbacks / longing bear bounces.
    MACRO_SIDE_SWITCH = True
    VOL_RATIO_MIN = 1.3             # was 1.5
    RSI_LONG_MAX = 62.0
    RSI_SHORT_MIN = 38.0
    RSI_1D_LONG_MAX = 80.0
    RSI_4H_LONG_MAX = 75.0
    RSI_1D_SHORT_MIN = 20.0
    RSI_4H_SHORT_MIN = 25.0
    # Regime classifier (consensus: structure + slope + DMI direction + ADX)
    ADX_REGIME_MIN = 25.0
    DMI_PERIOD = 14
    REGIME_SLOPE_BARS = 24          # 1H bars (~6x 4H candles) for 4H EMA200 slope

    # --- LONG calibration -----------------------------------------------
    # Counter-intuitive finding (2026-06-18): TIGHTENING the long entry made the
    # bot blind to bull markets (0 longs taken during the 2025-05..09 +40%/mo
    # ETH bull). The long entry is therefore kept LOOSE so it can catch uptrends;
    # the discrimination is done by REGIME PERSISTENCE instead — an up-regime
    # must hold for several bars to count, which keeps the real 2025 bull but
    # rejects the flickering fake-ups of the 2026 chop. Shorts are unchanged.
    LONG_REQUIRE_SWEEP = False
    LONG_ADX_MIN = 0.0              # rely on the regime gate, not a 1H ADX floor
    LONG_VOL_RATIO_MIN = 1.3
    LONG_RSI_MIN = 0.0
    REGIME_PERSIST_BARS = 12        # up-regime must hold this many 1H bars to confirm a real trend
    # With MACRO_SIDE_SWITCH on, the 1D structure already confirms the regime, so
    # the long entry can use the instantaneous up-regime (faster bull capture)
    # instead of the slower persistence-confirmed one. Tested False (instantaneous)
    # = great bull capture (+13%) but bleeds in non-bull (FULL -6%); the confirmed
    # gate is the robust choice on predominantly non-bull data.
    LONG_USE_CONFIRMED = True
    # LONG earlier profit-taking (bank the move before the market reverses)
    LONG_TP_ROI = 0.12              # primary target (~2.4% price move at x5), was 0.25
    LONG_TP_EARLY_ROI = 0.06        # early exit floor when overbought
    LONG_TP_RSI = 68.0              # overbought threshold for early exit, was 82
    LONG_TP_FLIP_ROI = 0.04         # exit fast if 4H flips bearish while in profit

    # --- Dynamic ATR stoploss (CLAUDE.md #4) -----------------------------
    # Replaces the old static 5-7% price stop (~7-10x ATR, far too wide) with a
    # volatility-scaled stop fixed at the entry candle (static, not trailing):
    # tighter in calm markets, wider in storms. Clamped so x5 leverage never
    # risks more than SL_MAX_PCT*5 of margin per trade.
    ATR_STOP_MULT = 4.5             # stop distance = N x ATR at entry (robust 3.5-4.5 plateau)
    SL_MIN_PCT = 0.015              # floor: 1.5% price move (=7.5% margin at x5)
    SL_MAX_PCT = 0.10               # ceiling: 10% price move (storm room to ride volatile trends)

    # V9.0: SMC CORRECTED (x5 Leverage)
    # Target: 15-20% ROI per trade (Price move 3-4%)
    # Stoploss: 2-3% price move (10-15% margin risk)
    stoploss = -0.99  # Safety net. Set wide so custom_stoploss can work correctly.
    use_custom_stoploss = True
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False

    # Futures Leverage Configuration
    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: str,
                 side: str, **kwargs) -> float:
        return 5.0  # HARD-CODE X5 LEVERAGE

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
    def leverage(self, pair, current_time, current_rate, proposed_leverage,
                 max_leverage, entry_tag, side, **kwargs):
        return 5.0

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

        # 2) Backtest / hyperopt: keep fully automatic so research is unaffected.
        if self.dp is None or self.dp.runmode.value not in ("live", "dry_run"):
            return True
        if not self.MANUAL_APPROVAL_REQUIRED:
            return True

        # 3) Force entries (human pressed Approve -> REST /forceenter) carry no
        #    dataframe signal tag, so they bypass the queue and execute.
        if entry_tag not in self.AUTO_SIGNAL_TAGS:
            logger.info(f"[APPROVAL] {pair} {side} manual/force entry accepted.")
            return True

        # 4) Automatic dataframe signal -> never trade directly; queue for approval.
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
        fallback = self.SL_MAX_PCT
        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe is None or len(dataframe) == 0:
                return fallback
            entry_time = getattr(trade, "open_date_utc", trade.open_date)
            at_entry = dataframe.loc[dataframe["date"] <= entry_time]
            if len(at_entry) == 0:
                return fallback
            atr = at_entry["atr"].iloc[-1]
            if pd.isna(atr) or trade.open_rate <= 0:
                return fallback
            sl_pct = self.ATR_STOP_MULT * (float(atr) / float(trade.open_rate))
            return float(min(max(sl_pct, self.SL_MIN_PCT), self.SL_MAX_PCT))
        except Exception as exc:  # noqa: BLE001 - never let SL plumbing crash the bot
            logger.error(f"[ATR-SL] {pair} fallback to {fallback}: {exc}")
            return fallback

    # ==========================================
    # CUSTOM EXIT: SMC Wave Profit Maximizer
    # Philosophy: Let the wave run, exit when SM distributes
    # ==========================================
    def custom_exit(self, pair: str, trade: "Trade", current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs):
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or len(dataframe) == 0:
            return False

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
            # === EMERGENCY EXIT ===
            # 4H turned bearish while we're losing: cut immediately (1.5% price move = 7.5% ROI)
            if current_profit < -0.075 and macro_bear and rsi < 38:
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
            # Emergency: 4H turned bullish while losing — cut FAST, don't wait
            # for a deep loss + extreme RSI (that confirmation arrives too late
            # and turned -7% shorts into -13/-18% in the June 2026 reversal).
            if current_profit < -0.04 and macro_bull:
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
            [(pair, "1h") for pair in pairs]
        )

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
        inf_4h["ema_50"]  = ta.EMA(inf_4h, timeperiod=50)
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
        #   1. STRUCTURE : 4H EMA50 vs EMA200 + price on the correct side.
        #   2. SLOPE     : 4H EMA200 actually moving (not flat/ranging).
        #   3. DIRECTION : DMI +DI vs -DI — the directional info ADX lacks.
        #   4. STRENGTH  : 4H ADX above the trend floor.
        # No lookahead: slope uses past EMA values; DMI/ADX use closed candles.
        # ------------------------------------------------------------------
        plus_di  = ta.PLUS_DI(dataframe, timeperiod=self.DMI_PERIOD)
        minus_di = ta.MINUS_DI(dataframe, timeperiod=self.DMI_PERIOD)
        ema_50_4h_col  = dataframe["ema_50_4h"]  if "ema_50_4h"  in dataframe.columns else dataframe["ema_50"]
        ema_200_4h_col = dataframe["ema_200_4h"] if "ema_200_4h" in dataframe.columns else dataframe["ema_200"]
        adx_4h_col     = dataframe["adx_4h"]     if "adx_4h"     in dataframe.columns else dataframe["adx"]

        struct_up = (ema_50_4h_col > ema_200_4h_col) & (dataframe["close"] > ema_50_4h_col)
        struct_dn = (ema_50_4h_col < ema_200_4h_col) & (dataframe["close"] < ema_50_4h_col)
        slope_up  = ema_200_4h_col > ema_200_4h_col.shift(self.REGIME_SLOPE_BARS)
        slope_dn  = ema_200_4h_col < ema_200_4h_col.shift(self.REGIME_SLOPE_BARS)
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

        # ------------------------------------------------------------------
        # X-RAY LOGGING
        # ------------------------------------------------------------------
        last = dataframe.iloc[-1]
        logger.warning(
            f"[V7 SMC] {metadata['pair']} | "
            f"4H: {'BULL' if last.get('macro_bullish_4h') else 'BEAR' if last.get('macro_bearish_4h') else 'NEUT'} | "
            f"Sweep15m: {'BULL' if last.get('bull_sweep_recent') else 'BEAR' if last.get('bear_sweep_recent') else '-'} | "
            f"BOS: {'BULL' if last.get('bos_bullish') else 'BEAR' if last.get('bos_bearish') else '-'} | "
            f"RSI={last['rsi']:.0f} ADX={last['adx']:.0f} Vol={last['volume_ratio']:.1f}x"
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

        # Macro side-switch: only the side aligned with the 1D structure may fire.
        if self.MACRO_SIDE_SWITCH:
            shark_long  &= dataframe["macro_bull_1d"]
            shark_short &= dataframe["macro_bear_1d"]

        # = ::::: ASSIGN ENTRIES ::::: =
        if self.ENABLE_LONG:
            dataframe.loc[shark_long,  ["enter_long",  "enter_tag"]] = (1, "shark_long_1h")
        if self.ENABLE_SHORT:
            dataframe.loc[shark_short, ["enter_short", "enter_tag"]] = (1, "shark_short_1h")

        return dataframe
