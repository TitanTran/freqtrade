"""
WOLF V6.0 ENTRY SIGNAL DIAGNOSTIC
Mục tiêu: Tìm ra vì sao bot chỉ short, không long trong tháng 4/2026
"""
import sys
import os
import pandas as pd
import numpy as np
import talib.abstract as ta
from datetime import datetime

# Setup freqtrade path
sys.path.insert(0, 'd:/PYTHON/freqtrade')
os.chdir('d:/PYTHON/freqtrade')

# Load data từ feather cache
DATA_DIR = "d:/PYTHON/freqtrade/user_data/data/binance/futures"

def load_pair(pair_filename, timeframe_suffix):
    import glob
    pattern = os.path.join(DATA_DIR, f"{pair_filename}-{timeframe_suffix}-futures.feather")
    files = glob.glob(pattern)
    if not files:
        print(f"  [!] No data file found: {pattern}")
        return None
    df = pd.read_feather(files[0])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df

print("=" * 60)
print("  WOLF V6.0 ENTRY SIGNAL DIAGNOSTIC")
print("=" * 60)

# ---------- Load 15m BTC data ----------
print("\n[1] Loading BTC/USDT 15m data...")
df = load_pair("BTC_USDT_USDT", "15m")
if df is None:
    print("FAILED - no data")
    sys.exit(1)

# Filter to analysis window
df = df[(df["date"] >= "2026-03-20") & (df["date"] <= "2026-04-27")].copy()
print(f"  Rows: {len(df)}, From {df['date'].iloc[0]} to {df['date'].iloc[-1]}")

# ---------- Load 4H BTC data ----------
print("\n[2] Loading BTC/USDT 4h data...")
df_4h = load_pair("BTC_USDT_USDT", "4h")
if df_4h is None:
    print("FAILED - no 4h data")
    sys.exit(1)

df_4h = df_4h[(df_4h["date"] >= "2026-03-01") & (df_4h["date"] <= "2026-04-27")].copy()

# ---------- Compute 4H Indicators ----------
print("\n[3] Computing 4H macro indicators...")
df_4h["ema_20"]  = ta.EMA(df_4h, timeperiod=20)
df_4h["ema_50"]  = ta.EMA(df_4h, timeperiod=50)
df_4h["ema_200"] = ta.EMA(df_4h, timeperiod=200)

df_4h["macro_bullish"] = (
    (df_4h["close"] > df_4h["ema_50"]) |
    (df_4h["ema_20"] > df_4h["ema_50"])
)
df_4h["macro_bearish"] = (
    (df_4h["close"] < df_4h["ema_50"]) &
    (df_4h["ema_20"] < df_4h["ema_50"]) &
    (df_4h["close"] < df_4h["ema_200"])
)

# Show 4H status in April
print("\n  4H Macro Status — April 2026:")
april_4h = df_4h[df_4h["date"] >= "2026-04-01"][["date","close","ema_20","ema_50","ema_200","macro_bullish","macro_bearish"]].copy()
april_4h["date"] = april_4h["date"].dt.strftime("%m-%d %H:%M")
print(april_4h.tail(20).to_string(index=False))

bull_count  = df_4h[df_4h["date"] >= "2026-04-01"]["macro_bullish"].sum()
bear_count  = df_4h[df_4h["date"] >= "2026-04-01"]["macro_bearish"].sum()
total_4h    = len(df_4h[df_4h["date"] >= "2026-04-01"])
print(f"\n  April: {bull_count}/{total_4h} candles BULLISH ({bull_count/total_4h*100:.0f}%)")
print(f"  April: {bear_count}/{total_4h} candles BEARISH ({bear_count/total_4h*100:.0f}%)")

# ---------- Merge 4H into 15m ----------
print("\n[4] Merging 4H into 15m frame...")
df_4h_merge = df_4h[["date","macro_bullish","macro_bearish","ema_50"]].copy()
df_4h_merge = df_4h_merge.rename(columns={"macro_bullish":"macro_bullish_4h","macro_bearish":"macro_bearish_4h","ema_50":"ema_50_4h","date":"date_4h"})
df_4h_merge["date_4h"] = df_4h_merge["date_4h"].dt.floor("4h")

df["date_4h"] = df["date"].dt.floor("4h")
df = df.merge(df_4h_merge, on="date_4h", how="left")
df[["macro_bullish_4h","macro_bearish_4h"]] = df[["macro_bullish_4h","macro_bearish_4h"]].ffill()

# ---------- Compute 15m Indicators ----------
print("\n[5] Computing 15m indicators...")
df["ema_7"]   = ta.EMA(df, timeperiod=7)
df["ema_25"]  = ta.EMA(df, timeperiod=25)
df["ema_50"]  = ta.EMA(df, timeperiod=50)
df["rsi"]     = ta.RSI(df, timeperiod=14)
df["volume_mean"] = df["volume"].rolling(window=40).mean()

bb = ta.BBANDS(df, timeperiod=20)
df["bb_lowerband"] = bb["lowerband"]
df["bb_upperband"] = bb["upperband"]

df["mfi"] = ta.MFI(df, timeperiod=14)
df["local_low"]  = df["low"].rolling(window=30).min().shift(1)
df["local_high"] = df["high"].rolling(window=30).max().shift(1)
df["candle_body"] = abs(df["close"] - df["open"])

# MFI Divergence
df["mfi_low_divergence"] = np.where(
    (df["low"] < df["low"].shift(1)) &
    (df["mfi"] > df["mfi"].shift(1)) &
    (df["mfi"] < 30), 1, 0
)
df["mfi_high_divergence"] = np.where(
    (df["high"] > df["high"].shift(1)) &
    (df["mfi"] < df["mfi"].shift(1)) &
    (df["mfi"] > 70), 1, 0
)

volume_climax_prev = (df["volume"].shift(1) > df["volume_mean"].shift(1) * 3)

# ---------- DIAGNOSE EACH CONDITION ----------
print("\n[6] Diagnosing WHY Long signals are blocked...")

df_apr = df[df["date"] >= "2026-04-01"].copy()
total = len(df_apr)

def pct(mask): return f"{mask.sum()} / {total} ({mask.sum()/total*100:.1f}%)"

print(f"\n  LONG PRECISION CONDITIONS (need ALL true simultaneously):")
c1 = df_apr["mfi_low_divergence"] == 1
c2 = df_apr["low"] < df_apr["local_low"]
c3 = df_apr["close"] > df_apr["open"]
c4 = df_apr["close"] > df_apr["ema_25"]
c5 = df_apr["rsi"] < 45
c6 = df_apr["volume"] > df_apr["volume_mean"]
c7 = df_apr["macro_bullish_4h"] == True

print(f"  C1 mfi_low_divergence==1     : {pct(c1)}")
print(f"  C2 low < local_low (sweep)   : {pct(c2)}")
print(f"  C3 green candle              : {pct(c3)}")
print(f"  C4 close > ema_25            : {pct(c4)}")
print(f"  C5 rsi < 45                  : {pct(c5)}")
print(f"  C6 volume > mean             : {pct(c6)}")
print(f"  C7 macro_bullish_4h          : {pct(c7)}")
print(f"  C1+C2 (core)                 : {pct(c1 & c2)}")
print(f"  C1+C2+C3+C4                  : {pct(c1 & c2 & c3 & c4)}")
print(f"  C1+C2+C3+C4+C5              : {pct(c1 & c2 & c3 & c4 & c5)}")
print(f"  ALL (C1-C7, no AI)           : {pct(c1 & c2 & c3 & c4 & c5 & c6 & c7)}")

print(f"\n  PANIC SNIPER CONDITIONS:")
p1 = volume_climax_prev.reindex(df_apr.index)
p2 = df_apr["volume"] < df_apr["volume_mean"] * 1.5
p3 = df_apr["low"] < df_apr["bb_lowerband"]
p4 = df_apr["close"] > df_apr["open"]
p5 = df_apr["rsi"] < 35
p6 = df_apr["macro_bullish_4h"] == True

print(f"  P1 volume_climax_prev (>3x)  : {pct(p1)}")
print(f"  P2 volume now < 1.5x mean    : {pct(p2)}")
print(f"  P3 low < bb_lower            : {pct(p3)}")
print(f"  P4 green candle              : {pct(p4)}")
print(f"  P5 rsi < 35                  : {pct(p5)}")
print(f"  P6 macro_bullish_4h          : {pct(p6)}")
print(f"  ALL (no AI)                  : {pct(p1 & p2 & p3 & p4 & p5 & p6)}")

print(f"\n  BOS LONG RIDER CONDITIONS:")
b1 = df_apr["ema_7"] > df_apr["ema_25"]
b2 = df_apr["ema_25"] > df_apr["ema_50"]
b3 = df_apr["volume"] > df_apr["volume_mean"] * 1.5
b4 = df_apr["macro_bullish_4h"] == True

print(f"  B1 ema_7 > ema_25            : {pct(b1)}")
print(f"  B2 ema_25 > ema_50           : {pct(b2)}")
print(f"  B3 volume > 1.5x mean        : {pct(b3)}")
print(f"  B4 macro_bullish_4h          : {pct(b4)}")
print(f"  B1+B2 (EMA stacked)          : {pct(b1 & b2)}")
print(f"  B1+B2+B3+B4 (no AI)          : {pct(b1 & b2 & b3 & b4)}")
# Key: if b4 is blocking, it means 4H logic is broken

print(f"\n[7] KEY DIAGNOSTIC: macro_bullish_4h distribution in April...")
np_bull = df_apr["macro_bullish_4h"].fillna(False)
np_bear = df_apr["macro_bearish_4h"].fillna(False)
neither = (~np_bull) & (~np_bear)
print(f"  Candles BULLISH_4H  : {pct(np_bull)}")
print(f"  Candles BEARISH_4H  : {pct(np_bear)}")
print(f"  Candles NEITHER     : {pct(neither)}")

print(f"\n  [!] If NEITHER is high, the 4H column name is wrong (merge bug)!")
print(f"  Checking column names in merged df:")
col_list = [c for c in df.columns if "4h" in c or "macro" in c]
print(f"  {col_list}")

print("\n[8] NaN audit on key columns...")
for col in ["macro_bullish_4h", "macro_bearish_4h", "mfi_low_divergence", "local_low"]:
    nan_count = df_apr[col].isna().sum()
    print(f"  {col}: {nan_count} NaN / {total}")

print("\n[DONE] Diagnostic complete.")
