"""Diagnostic funnel: WHY did June-July 2026 produce zero entries?

For each entry model (shark_long, shark_short, breakdown->retest short) print
the per-gate pass rate over the window plus the CUMULATIVE funnel, so the
binding constraint (the gate that kills the entry) is visible instead of
guessed. Read-only analysis — no signals are changed.

Usage: python scratch/funnel_junjul.py
"""

import pandas as pd

from freqtrade.configuration import Configuration
from freqtrade.data.dataprovider import DataProvider
from freqtrade.resolvers import StrategyResolver

CONFIG_PATH = "user_data/strategies/config.json"
STRATEGY_NAME = "WolfStrategy"
STRATEGY_PATH = "user_data/strategies/WolfStrategyV1"
PAIRS = ["BTC/USDT:USDT", "ETH/USDT:USDT"]
WINDOW_START = "2026-06-01"
WINDOW_END = "2026-07-06"


def build(strategy, pair):
    candles = strategy.dp.get_pair_dataframe(pair=pair, timeframe=strategy.timeframe)
    df = strategy.analyze_ticker(candles.copy(), {"pair": pair})
    mask = (df["date"] >= WINDOW_START) & (df["date"] <= WINDOW_END)
    return df.loc[mask].copy()


def funnel(df, strategy, gates):
    """Print individual pass-rate and cumulative funnel for ordered gates."""
    n = len(df)
    cumulative = pd.Series(True, index=df.index)
    print(f"    {'gate':38s} {'solo%':>7s} {'cum%':>7s} {'cum-candles':>12s}")
    for name, series in gates:
        series = series.fillna(False).astype(bool)
        cumulative &= series
        print(f"    {name:38s} {series.mean()*100:6.1f}% {cumulative.mean()*100:6.1f}% {int(cumulative.sum()):12d}")
    return cumulative


def main():
    config = Configuration.from_files([CONFIG_PATH])
    config["strategy"] = STRATEGY_NAME
    config["strategy_path"] = STRATEGY_PATH
    config.setdefault("dataformat_ohlcv", "feather")
    from freqtrade.enums import CandleType
    config.setdefault("candle_type_def", CandleType.get_default(config.get("trading_mode", "spot")))
    strategy = StrategyResolver.load_strategy(config)
    strategy.dp = DataProvider(config, None)

    for pair in PAIRS:
        df = build(strategy, pair)
        n = len(df)
        print(f"\n=== {pair} | {WINDOW_START}..{WINDOW_END} | {n} hourly candles ===")

        rising_macd = df["macdhist"] > df["macdhist"].shift(1)
        falling_macd = df["macdhist"] < df["macdhist"].shift(1)

        print("  -- SHARK LONG funnel --")
        funnel(df, strategy, [
            ("trend_bullish_1d", df["trend_bullish_1d"]),
            ("macro_bullish_4h", df["macro_bullish_4h"]),
            ("rsi_1d < 80", df["rsi_1d"].fillna(50) < strategy.RSI_1D_LONG_MAX),
            ("rsi_4h < 75", df["rsi_4h"].fillna(50) < strategy.RSI_4H_LONG_MAX),
            ("regime_up_confirmed (6 bars)", df["regime_up_confirmed"]),
            ("above_vwap", df["above_vwap"]),
            ("rsi < 72", df["rsi"] < strategy.RSI_LONG_MAX),
            ("volume_ratio > 1.0", df["volume_ratio"] > strategy.LONG_VOL_RATIO_MIN),
            ("macdhist rising", rising_macd),
            ("F1 no bear_sweep_4h", ~df["bear_sweep_4h"].fillna(False).astype(bool)),
            ("F4 extension <= +3 ATR", df["extension_atr"] <= strategy.EXTENSION_MAX_ATR),
            ("side_long_ok (4H switch)", df["side_long_ok"]),
            ("F5 not crowded long", ~(df["funding_crowded_long"] | df["oi_crowded_long"])),
        ])

        print("  -- SHARK SHORT funnel --")
        funnel(df, strategy, [
            ("trend_bearish_1d", df["trend_bearish_1d"]),
            ("macro_bearish_4h", df["macro_bearish_4h"]),
            ("rsi_1d > 20", df["rsi_1d"].fillna(50) > strategy.RSI_1D_SHORT_MIN),
            ("rsi_4h > 25", df["rsi_4h"].fillna(50) > strategy.RSI_4H_SHORT_MIN),
            ("regime_down (instant)", df["regime_down"]),
            ("below_vwap", df["below_vwap"]),
            ("close < ema_200 (1h)", df["close"] < df["ema_200"]),
            ("rsi > 38 (bounce)", df["rsi"] > strategy.RSI_SHORT_MIN),
            ("volume_ratio > 1.3", df["volume_ratio"] > strategy.VOL_RATIO_MIN),
            ("macdhist falling", falling_macd),
            ("F4 extension >= -3 ATR", df["extension_atr"] >= -strategy.EXTENSION_MAX_ATR),
            ("side_short_ok (4H switch)", df["side_short_ok"]),
            ("F5 not crowded short", ~(df["funding_crowded_short"] | df["oi_crowded_short"])),
        ])

        print("  -- BREAKDOWN SHORT funnel (arms the retest) --")
        funnel(df, strategy, [
            ("side_short_ok (4H switch)", df["side_short_ok"]),
            ("regime_down (instant)", df["regime_down"]),
            ("below_vwap", df["below_vwap"]),
            ("close < ema_200 (1h)", df["close"] < df["ema_200"]),
            ("close < recent_low (new low)", df["close"] < df["recent_low"]),
            ("bearish candle", df["close"] < df["open"]),
            ("volume_ratio > 1.3", df["volume_ratio"] > strategy.VOL_RATIO_MIN),
            ("macdhist < 0", df["macdhist"] < 0),
            ("rsi > 35 (not exhausted)", df["rsi"] > strategy.BREAKDOWN_RSI_MIN),
            ("F4 extension >= -3 ATR", df["extension_atr"] >= -strategy.EXTENSION_MAX_ATR),
            ("F5 not crowded short", ~(df["funding_crowded_short"] | df["oi_crowded_short"])),
        ])

        # Context stats for interpretation
        print("  -- window context --")
        print(f"    regime_up any:   {df['regime_up'].mean()*100:5.1f}%   "
              f"regime_down any: {df['regime_down'].mean()*100:5.1f}%   "
              f"(neither = chop: {((~df['regime_up']) & (~df['regime_down'])).mean()*100:5.1f}%)")
        print(f"    adx_4h > 25:     {(df['adx_4h'].fillna(0) > 25).mean()*100:5.1f}%")
        print(f"    price change over window: "
              f"{(df['close'].iloc[-1] / df['close'].iloc[0] - 1)*100:+.1f}%")


if __name__ == "__main__":
    main()
