"""Diagnostic: snapshot entry-candle indicators for every backtest trade.

Purpose: separate deep losers (<= -12% margin ROI) from the rest on candidate
veto dimensions (opposing sweep, ATR-normalized extension below VWAP/EMA,
regime age) so filter thresholds are picked from data, not guessed.

Usage: python scratch/diag_entry_snapshots.py <backtest-result-zip> [<zip2> ...]
"""

import json
import sys
import zipfile
from pathlib import Path

import pandas as pd

from freqtrade.configuration import Configuration
from freqtrade.data.dataprovider import DataProvider
from freqtrade.resolvers import StrategyResolver

DEEP_LOSS_THRESHOLD = -0.12
CONFIG_PATH = "user_data/strategies/config.json"
STRATEGY_NAME = "WolfStrategy"
STRATEGY_PATH = "user_data/strategies/WolfStrategyV1"
SIGNAL_TIMEFRAME_OFFSET = pd.Timedelta(hours=1)  # entry fills 1 candle after signal

SNAPSHOT_COLUMNS = [
    "bull_sweep_recent", "bull_sweep_4h", "bear_sweep_recent", "bear_sweep_4h",
    "rsi", "rsi_4h", "rsi_1d", "volume_ratio", "macdhist", "adx",
]


def load_trades(zip_path: str) -> pd.DataFrame:
    archive = zipfile.ZipFile(zip_path)
    name = [n for n in archive.namelist()
            if n.endswith(".json") and "config" not in n and "meta" not in n][0]
    payload = json.loads(archive.read(name))
    trades = pd.DataFrame(payload["strategy"][STRATEGY_NAME]["trades"])
    trades["open_date"] = pd.to_datetime(trades["open_date"], utc=True)
    trades["source"] = Path(zip_path).stem
    return trades


def build_analyzed_dataframes(pairs: list[str]) -> dict[str, pd.DataFrame]:
    config = Configuration.from_files([CONFIG_PATH])
    config["strategy"] = STRATEGY_NAME
    config["strategy_path"] = STRATEGY_PATH
    config.setdefault("dataformat_ohlcv", "feather")
    from freqtrade.enums import CandleType
    config.setdefault("candle_type_def", CandleType.get_default(config.get("trading_mode", "spot")))
    strategy = StrategyResolver.load_strategy(config)
    strategy.dp = DataProvider(config, None)
    analyzed = {}
    for pair in pairs:
        candles = strategy.dp.get_pair_dataframe(pair=pair, timeframe=strategy.timeframe)
        if candles is None or candles.empty:
            print(f"!! no data for {pair}")
            continue
        df = strategy.analyze_ticker(candles.copy(), {"pair": pair})
        # Age of the down/up regime in bars at each candle (consecutive True run).
        for col in ("regime_down", "regime_up"):
            grp = (~df[col]).cumsum()
            df[f"{col}_age"] = df.groupby(grp)[col].cumsum()
        # ATR-normalized extension: how far price sits below VWAP / below EMA50.
        df["ext_below_vwap_atr"] = (df["vwap"] - df["close"]) / df["atr"]
        df["ext_below_ema50_atr"] = (df["ema_50"] - df["close"]) / df["atr"]
        analyzed[pair] = df.set_index("date")
    return analyzed


def main() -> None:
    zips = sys.argv[1:]
    if not zips:
        raise SystemExit("pass at least one backtest-result zip")
    trades = pd.concat([load_trades(z) for z in zips], ignore_index=True)
    analyzed = build_analyzed_dataframes(sorted(trades["pair"].unique()))

    rows = []
    for _, trade in trades.iterrows():
        df = analyzed.get(trade["pair"])
        if df is None:
            continue
        signal_time = trade["open_date"] - SIGNAL_TIMEFRAME_OFFSET
        if signal_time not in df.index:
            print(f"!! signal candle missing: {trade['pair']} {signal_time}")
            continue
        candle = df.loc[signal_time]
        row = {
            "pair": trade["pair"].split("/")[0],
            "signal_time": signal_time,
            "tag": trade["enter_tag"],
            "profit": trade["profit_ratio"],
            "exit": trade["exit_reason"],
            "deep_loser": trade["profit_ratio"] <= DEEP_LOSS_THRESHOLD,
            "regime_down_age": int(candle["regime_down_age"]),
            "regime_up_age": int(candle["regime_up_age"]),
            "ext_vwap": round(float(candle["ext_below_vwap_atr"]), 2),
            "ext_ema50": round(float(candle["ext_below_ema50_atr"]), 2),
        }
        for col in SNAPSHOT_COLUMNS:
            value = candle.get(col)
            row[col] = round(float(value), 2) if pd.api.types.is_number(value) else bool(value)
        rows.append(row)

    snap = pd.DataFrame(rows).sort_values("signal_time")
    out_path = Path("scratch/entry_snapshots.csv")
    snap.to_csv(out_path, index=False)
    print(f"saved {len(snap)} rows -> {out_path}\n")

    shorts = snap[snap["tag"].str.contains("short")]
    pd.set_option("display.width", 250)
    print("=== SHORT trades: deep losers vs rest (median) ===")
    numeric = ["profit", "ext_vwap", "ext_ema50", "rsi", "rsi_4h", "rsi_1d",
               "volume_ratio", "adx", "regime_down_age"]
    print(shorts.groupby("deep_loser")[numeric].median().T)
    print("\n=== SHORT sweep flags: share with opposing (bull) sweep active ===")
    flags = ["bull_sweep_recent", "bull_sweep_4h"]
    print(shorts.groupby("deep_loser")[flags].mean().T)
    print("\n=== SHORT deep losers detail ===")
    detail_cols = ["pair", "signal_time", "tag", "profit", "exit", "ext_vwap",
                   "ext_ema50", "rsi", "rsi_4h", "regime_down_age",
                   "bull_sweep_recent", "bull_sweep_4h"]
    print(shorts[shorts["deep_loser"]][detail_cols].to_string(index=False))

    longs = snap[snap["tag"].str.contains("long")]
    if not longs.empty:
        print("\n=== LONG trades: deep losers vs rest (median) ===")
        numeric_long = ["profit", "ext_vwap", "ext_ema50", "rsi", "rsi_4h",
                        "volume_ratio", "adx", "regime_up_age"]
        print(longs.groupby("deep_loser")[numeric_long].median().T)
        print("\n=== LONG sweep flags ===")
        print(longs.groupby("deep_loser")[["bear_sweep_recent", "bear_sweep_4h"]].mean().T)


if __name__ == "__main__":
    main()
