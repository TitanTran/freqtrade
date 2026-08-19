"""
WOLF V6.0 AI SCORE DIAGNOSTIC
Mục tiêu: Kiểm tra AI score phân phối và tương quan với giá thực tế
"""
import sys, os, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, 'd:/PYTHON/freqtrade')
os.chdir('d:/PYTHON/freqtrade')

import pandas as pd
import numpy as np

DATA_DIR = "d:/PYTHON/freqtrade/user_data/data/binance/futures"

def load_pair(pair_filename, tf):
    import glob
    p = os.path.join(DATA_DIR, f"{pair_filename}-{tf}-futures.feather")
    files = glob.glob(p)
    if not files: return None
    df = pd.read_feather(files[0])
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)

# --- Load FreqAI predictions from backtest feather ---
import glob

MODELS_DIR = "d:/PYTHON/freqtrade/user_data/models"
print("=" * 60)
print("  WOLF V6.0 AI SCORE DIAGNOSTIC")
print("=" * 60)

# Find the latest backtest prediction file
pred_files = glob.glob(f"{MODELS_DIR}/**/backtesting_predictions/*.feather", recursive=True)
pred_files = sorted(pred_files)
print(f"\n[1] Found {len(pred_files)} prediction file(s):")
for f in pred_files[-5:]:
    print(f"  {os.path.basename(f)}")

if not pred_files:
    print("  No prediction files found. Exiting.")
    sys.exit(0)

# Load all predictions and merge
dfs = []
for f in pred_files:
    try:
        df = pd.read_feather(f)
        df["source"] = os.path.basename(f)
        dfs.append(df)
    except Exception as e:
        print(f"  Error reading {f}: {e}")

if not dfs:
    print("No predictions loaded.")
    sys.exit(0)

pred_df = pd.concat(dfs, ignore_index=True)

print(f"\n[2] Prediction columns: {list(pred_df.columns)}")
print(f"  Total rows: {len(pred_df)}")

# Find the score column
score_col = None
for c in pred_df.columns:
    if "rr_score" in c or "&-" in c:
        score_col = c
        break

if not score_col:
    print("  No score column found! Columns:", pred_df.columns.tolist())
    sys.exit(0)

print(f"\n[3] AI Score Column: '{score_col}'")

# --- Score distribution analysis ---
if "date" in pred_df.columns:
    pred_df["date"] = pd.to_datetime(pred_df["date"])
    april = pred_df[pred_df["date"] >= "2026-04-01"].copy()
else:
    april = pred_df.copy()

scores = april[score_col].dropna()
print(f"\n[4] AI Score Distribution (April 2026):")
print(f"  Count  : {len(scores)}")
print(f"  Mean   : {scores.mean():.4f}")
print(f"  Median : {scores.median():.4f}")
print(f"  Min    : {scores.min():.4f}")
print(f"  Max    : {scores.max():.4f}")
print(f"  Std    : {scores.std():.4f}")

# Distribution buckets
buckets = [(-999, -0.05), (-0.05, -0.02), (-0.02, -0.01), (-0.01, -0.005),
           (-0.005, 0.005), (0.005, 0.01), (0.01, 0.02), (0.02, 0.05), (0.05, 999)]
print(f"\n  Score Bucket Distribution:")
for lo, hi in buckets:
    mask = (scores >= lo) & (scores < hi)
    pct = mask.sum() / len(scores) * 100
    bar = "#" * int(pct / 2)
    print(f"  [{lo:6.3f}, {hi:6.3f}): {mask.sum():4d} ({pct:5.1f}%)  {bar}")

# --- KEY CHECK: How many candles have score > 0.008 (BOS long threshold) ---
long_ok   = (scores > 0.008).sum()
long_ok2  = (scores > 0.02).sum()
short_ok  = (scores < -0.008).sum()
short_ok2 = (scores < -0.02).sum()
neutral   = ((scores >= -0.008) & (scores <= 0.008)).sum()

print(f"\n[5] Threshold Analysis:")
print(f"  Scores > 0.008  (BOS Long new threshold): {long_ok} / {len(scores)} ({long_ok/len(scores)*100:.1f}%)")
print(f"  Scores > 0.020  (Old strict threshold)  : {long_ok2} / {len(scores)} ({long_ok2/len(scores)*100:.1f}%)")
print(f"  Scores < -0.008 (BOS Short threshold)   : {short_ok} / {len(scores)} ({short_ok/len(scores)*100:.1f}%)")
print(f"  Scores < -0.020 (Old strict threshold)  : {short_ok2} / {len(scores)} ({short_ok2/len(scores)*100:.1f}%)")
print(f"  Neutral zone    (-0.008 to 0.008)        : {neutral} / {len(scores)} ({neutral/len(scores)*100:.1f}%)")

# --- Correlation check ---
if "close" in april.columns:
    april["future_return"] = april["close"].pct_change(24).shift(-24)
    valid = april[[score_col, "future_return"]].dropna()
    corr = valid[score_col].corr(valid["future_return"])
    print(f"\n[6] AI Score vs Actual 6h Future Return Correlation: {corr:.4f}")
    if abs(corr) < 0.05:
        print("  [CRITICAL] Correlation near 0 — AI model is NOT predictive!")
        print("  The model needs to be retrained with fresh features.")
    elif corr > 0.05:
        print("  [OK] Positive correlation — AI leans bullish when market goes up.")
    else:
        print("  [WARNING] Negative correlation — AI may be inverted!")

    # Per-period breakdown
    print(f"\n  Per-week avg AI score vs actual return:")
    april["week"] = april["date"].dt.to_period("W")
    weekly = april.groupby("week")[[score_col, "future_return"]].mean()
    print(weekly.to_string())

print("\n[DONE]")
