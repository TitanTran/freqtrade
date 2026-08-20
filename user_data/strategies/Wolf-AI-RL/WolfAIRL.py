import logging
from dataclasses import dataclass
from datetime import datetime
from functools import reduce

import numpy as np
import pandas as pd
import talib.abstract as ta
from pandas import DataFrame

from freqtrade.exchange import timeframe_to_minutes
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FeatureConfig:
    """Explicit, named thresholds - no magic numbers scattered through the logic."""

    ATR_PERIOD: int = 14
    ONE_DAY_MINUTES: int = 1440
    MIN_VWAP_WINDOW_CANDLES: int = 20
    VOLUME_MEAN_WINDOW: int = 20

    # ATR-based dynamic stoploss (CLAUDE.md rule #4): widens in storms, tightens in calm.
    ATR_STOP_MULT: float = 4.0
    SL_MIN_PCT: float = 0.015
    SL_MAX_PCT: float = 0.10


class WolfAIRL(IStrategy):
    """
    Wolf-AI-RL: FreqAI Reinforcement Learning strategy.

    The agent (trained via `freqtrade/freqaimodels/WolfReinforcementLearner.py`) decides
    entries/exits directly through the `&-action` column (Base5ActionRLEnv: 0 neutral,
    1 long-enter, 2 long-exit, 3 short-enter, 4 short-exit). The strategy itself only:
      * builds a lean, orthogonal feature set (momentum / volatility / volume / structure)
        for the agent to observe - CLAUDE.md rule #5,
      * enforces the VWAP gate on every entry (never long below VWAP, never short above it)
        - CLAUDE.md rule #3,
      * enforces a dynamic ATR-based stoploss - CLAUDE.md rule #4.

    Run with:
    freqtrade trade --freqaimodel WolfReinforcementLearner --strategy WolfAIRL \
        --strategy-path user_data/strategies/Wolf-AI-RL --config user_data/strategies/Wolf-AI-RL/config.json
    """

    INTERFACE_VERSION = 3

    fc = FeatureConfig()

    timeframe = "15m"
    can_short = True
    process_only_new_candles = True
    use_exit_signal = True
    trailing_stop = False

    # Safety net only - the real stop is the ATR-based custom_stoploss below.
    stoploss = -0.99

    minimal_roi = {"0": 100}

    startup_candle_count: int = 300

    # ==========================================
    # FEATURE ENGINEERING (FreqAI)
    # ==========================================
    def feature_engineering_expand_all(
        self, dataframe: DataFrame, period: int, metadata: dict, **kwargs
    ) -> DataFrame:
        """Period-scaled features: momentum + volatility + volume dimensions."""
        # Momentum: price deviation from its EMA.
        ema = ta.EMA(dataframe, timeperiod=period)
        dataframe[f"%-price-dev-ema-{period}"] = (dataframe["close"] - ema) / ema

        # Volatility: ATR normalized by price (regime-agnostic across pairs/price levels).
        atr = ta.ATR(dataframe, timeperiod=period)
        dataframe[f"%-normalized-atr-{period}"] = atr / dataframe["close"]

        # Volume: current volume relative to its rolling mean.
        vol_mean = dataframe["volume"].rolling(period, min_periods=1).mean().replace(0, np.nan)
        dataframe[f"%-relative-volume-{period}"] = (dataframe["volume"] / vol_mean).fillna(1.0)

        return dataframe

    def feature_engineering_expand_basic(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        """Timeframe-scaled feature: structure dimension (distance to session VWAP)."""
        window = self._vwap_window_for_timeframe(metadata["tf"])
        vwap = self._calculate_vwap(dataframe, window)
        dataframe["%-dist-to-vwap"] = (dataframe["close"] - vwap) / vwap

        return dataframe

    def feature_engineering_standard(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        """Raw OHLC required by the RL environment (not a feature dimension by itself)."""
        dataframe["%-raw_close"] = dataframe["close"]
        dataframe["%-raw_open"] = dataframe["open"]
        dataframe["%-raw_high"] = dataframe["high"]
        dataframe["%-raw_low"] = dataframe["low"]

        return dataframe

    def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        """RL has no direct labels - `&-action` is filled with the neutral placeholder
        until the trained agent emits its own action during predict."""
        dataframe["&-action"] = 0

        return dataframe

    # ==========================================
    # INDICATORS (strategy-level: VWAP gate + ATR stop, not FreqAI features)
    # ==========================================
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        window = self._vwap_window_for_timeframe(self.timeframe)
        dataframe["vwap"] = self._calculate_vwap(dataframe, window)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=self.fc.ATR_PERIOD)

        dataframe = self.freqai.start(dataframe, metadata, self)

        return dataframe

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        # VWAP RULE (CLAUDE.md #3): never long below VWAP, never short above VWAP.
        above_vwap = df["close"] > df["vwap"]
        below_vwap = df["close"] < df["vwap"]

        enter_long_conditions = [df["do_predict"] == 1, df["&-action"] == 1, above_vwap]
        df.loc[reduce(lambda x, y: x & y, enter_long_conditions), ["enter_long", "enter_tag"]] = (
            1,
            "rl_long",
        )

        enter_short_conditions = [df["do_predict"] == 1, df["&-action"] == 3, below_vwap]
        df.loc[reduce(lambda x, y: x & y, enter_short_conditions), ["enter_short", "enter_tag"]] = (
            1,
            "rl_short",
        )

        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        exit_long_conditions = [df["do_predict"] == 1, df["&-action"] == 2]
        df.loc[reduce(lambda x, y: x & y, exit_long_conditions), "exit_long"] = 1

        exit_short_conditions = [df["do_predict"] == 1, df["&-action"] == 4]
        df.loc[reduce(lambda x, y: x & y, exit_short_conditions), "exit_short"] = 1

        return df

    # ==========================================
    # CUSTOM STOPLOSS: ATR-based, static at entry (no hardcoded stoploss - CLAUDE.md #4)
    # ==========================================
    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> float:
        sl_pct = self._atr_stop_pct(pair, trade)

        if trade.trade_direction == "short":
            target_sl_price = trade.open_rate * (1 + sl_pct)
            return -trade.leverage * ((target_sl_price / current_rate) - 1)
        else:
            target_sl_price = trade.open_rate * (1 - sl_pct)
            return -trade.leverage * (1 - (target_sl_price / current_rate))

    def _atr_stop_pct(self, pair: str, trade: Trade) -> float:
        """Volatility-scaled stop distance, fixed at the entry candle's ATR so the stop
        is static and never trails. Widens in high-volatility regimes, tightens in calm
        ones, clamped to [SL_MIN_PCT, SL_MAX_PCT]. Falls back to the ceiling if ATR is
        unavailable so a bad lookup never leaves a trade unprotected."""
        fallback = self.fc.SL_MAX_PCT
        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe is None or len(dataframe) == 0:
                return fallback
            entry_time = getattr(trade, "open_date_utc", trade.open_date)
            at_entry = dataframe.loc[dataframe["date"] <= entry_time]
            if len(at_entry) == 0:
                return fallback
            atr = at_entry["atr"].iloc[-1]
            return self._atr_stop_pct_from_atr(atr, trade.open_rate)
        except Exception as exc:  # noqa: BLE001 - never let SL plumbing crash the bot
            logger.error(f"[ATR-SL] {pair} fallback to {fallback}: {exc}")
            return fallback

    def _atr_stop_pct_from_atr(self, atr: float, price: float) -> float:
        if pd.isna(atr) or price <= 0:
            return self.fc.SL_MAX_PCT
        sl_pct = self.fc.ATR_STOP_MULT * (float(atr) / float(price))
        return float(min(max(sl_pct, self.fc.SL_MIN_PCT), self.fc.SL_MAX_PCT))

    # ==========================================
    # SHARED HELPERS
    # ==========================================
    def _vwap_window_for_timeframe(self, timeframe: str) -> int:
        """Rolling window covering roughly one trading day at the given timeframe."""
        minutes = timeframe_to_minutes(timeframe)
        return max(int(self.fc.ONE_DAY_MINUTES / minutes), self.fc.MIN_VWAP_WINDOW_CANDLES)

    @staticmethod
    def _calculate_vwap(dataframe: DataFrame, window: int) -> pd.Series:
        typical_price = (dataframe["high"] + dataframe["low"] + dataframe["close"]) / 3
        tp_volume = typical_price * dataframe["volume"]
        rolling_tp_volume = tp_volume.rolling(window, min_periods=1).sum()
        rolling_volume = dataframe["volume"].rolling(window, min_periods=1).sum().replace(0, np.nan)
        return (rolling_tp_volume / rolling_volume).fillna(dataframe["close"])
