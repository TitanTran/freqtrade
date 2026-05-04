import logging
from freqtrade.strategy import IStrategy, merge_informative_pair
from pandas import DataFrame
import talib.abstract as ta
from datetime import datetime
from freqtrade.persistence import Trade
import numpy as np

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

    # Cooldown after loss
    protections = [
        {"method": "CooldownPeriod", "stop_duration_candles": 4}
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
    # CUSTOM STOPLOSS: ATR-based, below swing low
    # ==========================================
    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:
        
        # V9.1: Fix "Constant Trailing Stop" bug. 
        # Calculate static SL from open_rate.
        # V10.0: SHARK HUNTING (Swing Mode)
        # Wide SL to survive the market volatility: 5% price move = 25% margin risk
        sl_pct = 0.05 if "BTC" in pair else 0.07
        
        # Freqtrade expects the return value relative to current_rate, but divides it by leverage.
        # To maintain a static price-based stop loss, we calculate the exact target price.
        if trade.trade_direction == "short":
            target_sl_price = trade.open_rate * (1 + sl_pct)
            return -trade.leverage * ((target_sl_price / current_rate) - 1)
        else:
            target_sl_price = trade.open_rate * (1 - sl_pct)
            return -trade.leverage * (1 - (target_sl_price / current_rate))

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

            # === TARGET ===
            if current_profit > 0.25:  # 25% ROI = 5% price move
                return "target_25pct_roi"

            # === PROFIT PROTECTION LADDER ===
            # Level 1: RSI extreme overbought (>82) 
            if current_profit > 0.15 and rsi > 82:
                return "smc_rsi_extreme_exit"

            # Level 2: RSI overbought (>75) + MFI high
            if current_profit > 0.20 and rsi > 75 and mfi > 80:
                return "smc_overbought_exit"

            # Level 3: 4H flipped bearish (Gãy trend lớn)
            if macro_bear:
                if current_profit > 0.10:
                    return "smc_4h_trend_flip_profit"

        if trade.trade_direction == "short":
            # Emergency: 4H turned bullish while losing
            if current_profit < -0.075 and macro_bull and rsi > 62:
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

        common_cond = (dataframe["volume"] > 0)

        # ==========================================
        # LONG ENTRIES (SHARK HUNTING)
        # Context: 1D Bullish + 4H Bullish
        # Trigger: 1H Liquidity Sweep + High Volume + MACD Divergence
        # ==========================================
        long_bias = (
            (dataframe["trend_bullish_1d"]) & 
            (dataframe["macro_bullish_4h"]) &
            (dataframe["rsi_1d"] < 75) &     # Không mua khi Daily đã quá mua (đu đỉnh)
            (dataframe["rsi_4h"] < 70)       # Không mua khi 4H đang quá mua
        )

        shark_long = (
            common_cond &
            long_bias &
            (dataframe["bull_sweep_recent"] | dataframe["bull_sweep"]) &
            (dataframe["rsi"] < 60) &            # 1H phải có nhịp chỉnh (RSI < 60), không fomo
            (dataframe["close"] < dataframe["bb_upper"]) & # Không dính vào dải trên Bollinger
            (dataframe["volume_ratio"] > 1.5) &  # Sharks are buying
            (dataframe["macdhist"] > dataframe["macdhist"].shift(1)) # Momentum turning up
        )

        # ==========================================
        # SHORT ENTRIES (SHARK HUNTING)
        # ==========================================
        short_bias = (
            (dataframe["trend_bearish_1d"]) & 
            (dataframe["macro_bearish_4h"]) &
            (dataframe["rsi_1d"] > 25) &     # Không Short khi Daily quá bán (bán đáy)
            (dataframe["rsi_4h"] > 30)       # Không Short khi 4H quá bán
        )

        shark_short = (
            common_cond &
            short_bias &
            (dataframe["bear_sweep_recent"] | dataframe["bear_sweep"]) &
            (dataframe["rsi"] > 40) &            # 1H phải có nhịp hồi (RSI > 40), không bán đuổi
            (dataframe["close"] > dataframe["bb_lower"]) & # Không dính vào dải dưới Bollinger
            (dataframe["volume_ratio"] > 1.5) &  # Sharks are selling
            (dataframe["macdhist"] < dataframe["macdhist"].shift(1)) # Momentum turning down
        )

        # = ::::: ASSIGN ENTRIES ::::: =
        dataframe.loc[shark_long,  ["enter_long",  "enter_tag"]] = (1, "shark_long_1h")
        dataframe.loc[shark_short, ["enter_short", "enter_tag"]] = (1, "shark_short_1h")
        
        return dataframe
