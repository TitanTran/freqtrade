"""
WOLF - MARKET CONTEXT DIAGNOSTIC
Mục tiêu: Xác định market regime trong giai đoạn backtest để hiểu tại sao bot thua tất cả
"""
import sys, os, warnings
warnings.filterwarnings("ignore")
import pandas as pd
import numpy as np
import talib.abstract as ta

DATA_DIR = "d:/PYTHON/freqtrade/user_data/data/binance/futures"

def load_pair(name, tf):
    import glob
    f = glob.glob(os.path.join(DATA_DIR, f"{name}-{tf}-futures.feather"))
    if not f: return None
    df = pd.read_feather(f[0])
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)

print("=" * 70)
print("  MARKET REGIME DIAGNOSTIC (20 Mar - 27 Apr 2026)")
print("=" * 70)

for pair in ["BTC_USDT_USDT", "BNB_USDT_USDT"]:
    df = load_pair(pair, "4h")
    if df is None:
        print(f"{pair}: No data"); continue

    df = df[(df["date"] >= "2026-03-20") & (df["date"] <= "2026-04-27")].copy()
    df["ema_20"]  = ta.EMA(df, timeperiod=20)
    df["ema_50"]  = ta.EMA(df, timeperiod=50)
    df["ema_200"] = ta.EMA(df, timeperiod=200)
    df["atr"]     = ta.ATR(df, timeperiod=14)
    df["rsi"]     = ta.RSI(df, timeperiod=14)
    df["adx"]     = ta.ADX(df, timeperiod=14)
    df["atr_pct"] = df["atr"] / df["close"] * 100

    price_change = (df["close"].iloc[-1] - df["close"].iloc[0]) / df["close"].iloc[0] * 100
    max_dd = ((df["close"] - df["close"].cummax()) / df["close"].cummax()).min() * 100

    print(f"\n{'=' * 40}")
    print(f"  {pair.replace('_USDT_USDT','')}")
    print(f"  Price: {df['close'].iloc[0]:.0f} -> {df['close'].iloc[-1]:.0f}  ({price_change:+.1f}%)")
    print(f"  Max Drawdown in period: {max_dd:.1f}%")
    print(f"  Avg ATR%: {df['atr_pct'].mean():.2f}%  (volatility)")
    print(f"  Avg ADX : {df['adx'].mean():.1f}  (trend strength; >25=trending)")
    print(f"  Avg RSI : {df['rsi'].mean():.1f}")

    # Weekly breakdown
    df["week"] = df["date"].dt.to_period("W")
    print(f"\n  Weekly Price Movement:")
    for wk, grp in df.groupby("week"):
        w_start = grp["close"].iloc[0]
        w_end   = grp["close"].iloc[-1]
        w_chg   = (w_end - w_start) / w_start * 100
        w_hi    = grp["high"].max()
        w_lo    = grp["low"].min()
        w_range = (w_hi - w_lo) / w_start * 100
        direction = "UP  " if w_chg > 1 else ("DOWN" if w_chg < -1 else "FLAT")
        print(f"    {wk}: [{direction}] {w_chg:+6.1f}% | Range: {w_range:.1f}%")

    # Choppiness: count direction changes
    df["dir"] = np.sign(df["close"].diff())
    direction_changes = (df["dir"] != df["dir"].shift(1)).sum()
    choppiness = direction_changes / len(df) * 100
    print(f"\n  Choppiness Index: {choppiness:.0f}% direction changes (>60% = choppy sideways)")
    if choppiness > 60:
        print(f"  [!] MARKET IS CHOPPY — Trend-following strategies will FAIL here!")
    else:
        print(f"  [OK] Market has clear directional moves")

    # Find the 3 golden long opportunities (big up moves)
    df["15m_return_24h"] = df["close"].pct_change(6) * 100  # 6 candles * 4h = 24h return
    big_ups = df[df["15m_return_24h"] > 3.0].sort_values("15m_return_24h", ascending=False)
    print(f"\n  TOP LONG OPPORTUNITIES (>3% in 24h, 4H candles):")
    for _, row in big_ups.head(5).iterrows():
        print(f"    {row['date'].strftime('%m-%d %H:%M')}: +{row['15m_return_24h']:.1f}% | RSI={row['rsi']:.0f} | ADX={row['adx']:.0f}")

print("\n[DONE]")
