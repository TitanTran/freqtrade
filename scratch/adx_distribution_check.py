"""Structural check of ADX(4h) distribution — informs ADX_REGIME_TARGET_PCTL /
ADX_REGIME_MIN_LO calibration WITHOUT looking at P&L (per project convention:
thresholds calibrated on feature distributions, never P&L). Read-only.

Usage: python scratch/adx_distribution_check.py
"""

import numpy as np
import pandas as pd
import talib.abstract as ta

PAIRS = ["BTC", "ETH", "BNB"]

for p in PAIRS:
    df = pd.read_feather(f"user_data/data/binance/futures/{p}_USDT_USDT-4h-futures.feather")
    df["adx"] = ta.ADX(df, timeperiod=14)
    adx = df["adx"].dropna()

    last_30d = adx.tail(180)   # 30d of 4h bars
    last_14d = adx.tail(84)    # 14d of 4h bars
    last_7d = adx.tail(42)     # 7d of 4h bars

    print(f"\n=== {p} ADX(4h), {len(adx)} bars, {df['date'].iloc[0].date()}..{df['date'].iloc[-1].date()} ===")
    print("  Full-history percentiles:", {
        q: round(np.percentile(adx, q), 1) for q in [10, 25, 45, 50, 65, 75, 90]
    })
    print(f"  Last 30d:  mean={last_30d.mean():.1f}  median={last_30d.median():.1f}  "
          f"p45={np.percentile(last_30d, 45):.1f}  p65={np.percentile(last_30d, 65):.1f}")
    print(f"  Last 14d:  mean={last_14d.mean():.1f}  median={last_14d.median():.1f}  "
          f"p45={np.percentile(last_14d, 45):.1f}  p65={np.percentile(last_14d, 65):.1f}")
    print(f"  Last 7d:   mean={last_7d.mean():.1f}  median={last_7d.median():.1f}  last={adx.iloc[-1]:.1f}")
