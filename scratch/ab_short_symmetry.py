"""Follow-up to ab_other_frequency_levers.py: rather than loosening a shared
dial further, this tests the 3 places where the SHORT entry stack is
DELIBERATELY stricter than the mirrored LONG stack (found while auditing
populate_entry_trend, 2026-08-13):

  1. macro_bearish_4h = AND of 3 terms (close<ema50 & ema20<ema50 &
     close<ema200) vs macro_bullish_4h = OR of 2 terms (close>ema50 |
     ema20>ema50). Loosened variant mirrors the long formula exactly
     (drop the ema200 term, AND -> OR).
  2. shark_short requires close < ema_200(1h) as an extra structural
     confirmation with no long-side equivalent. Loosened variant drops it.
  3. SHORT_VOL_RATIO_MIN_LO/HI = 1.0/1.8 vs LONG's 0.8/1.5. Loosened
     variant matches the long range.

Each tested individually and combined, on top of the currently-deployed
baseline (50pctl/21d/LO17 ADX, REGIME_PERSIST_BARS=4).

Usage: PYTHONPATH=. python scratch/ab_short_symmetry.py
"""

import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

STRATEGY_FILE = Path("user_data/strategies/WolfStrategyV1/WolfStrategy.py")
RESULTS_DIR = Path("user_data/backtest_results")
CONFIG = "user_data/strategies/WolfStrategyV1/config.json"
STRATEGY_PATH = "user_data/strategies/WolfStrategyV1"

WINDOWS = {
    "W1_bear2026": {"timerange": "20260101-20260806", "months": 7.17},
    "W2_bull2025": {"timerange": "20250501-20250930", "months": 5.03},
}

MACRO_BEARISH_STRICT = '''        inf_4h["macro_bearish"] = (
            (inf_4h["close"] < inf_4h["ema_50"]) &
            (inf_4h["ema_20"] < inf_4h["ema_50"]) &
            (inf_4h["close"] < inf_4h["ema_200"])
        )'''
MACRO_BEARISH_LOOSE = '''        inf_4h["macro_bearish"] = (
            (inf_4h["close"] < inf_4h["ema_50"]) |
            (inf_4h["ema_20"] < inf_4h["ema_50"])
        )'''

SHARK_SHORT_STRICT = '''        shark_short = (
            has_volume &
            short_bias &
            regime_down_gate &                    # REGIME GATE (sustained or instantaneous)
            (dataframe["below_vwap"]) &           # VWAP RULE: never short above VWAP
            (dataframe["close"] < dataframe["ema_200"]) &        # structural downtrend on 1H
            (dataframe["rsi"] > self.RSI_SHORT_MIN) &            # need a bounce, not chasing
            (dataframe["volume_ratio"] > short_vol_ratio_min) &   # above-average participation (adaptive floor)
            (dataframe["macdhist"] < dataframe["macdhist"].shift(1))  # momentum turning down
        )'''
SHARK_SHORT_LOOSE = '''        shark_short = (
            has_volume &
            short_bias &
            regime_down_gate &                    # REGIME GATE (sustained or instantaneous)
            (dataframe["below_vwap"]) &           # VWAP RULE: never short above VWAP
            (dataframe["rsi"] > self.RSI_SHORT_MIN) &            # need a bounce, not chasing
            (dataframe["volume_ratio"] > short_vol_ratio_min) &   # above-average participation (adaptive floor)
            (dataframe["macdhist"] < dataframe["macdhist"].shift(1))  # momentum turning down
        )'''

VARIANTS = {
    "baseline":            {"flags": {}, "blocks": []},
    "loose_macrobear":     {"flags": {}, "blocks": [(MACRO_BEARISH_STRICT, MACRO_BEARISH_LOOSE)]},
    "loose_ema200":        {"flags": {}, "blocks": [(SHARK_SHORT_STRICT, SHARK_SHORT_LOOSE)]},
    "loose_volfloor":      {"flags": {"SHORT_VOL_RATIO_MIN_LO": 0.8, "SHORT_VOL_RATIO_MIN_HI": 1.5}, "blocks": []},
    "loose_all":           {
        "flags": {"SHORT_VOL_RATIO_MIN_LO": 0.8, "SHORT_VOL_RATIO_MIN_HI": 1.5},
        "blocks": [(MACRO_BEARISH_STRICT, MACRO_BEARISH_LOOSE), (SHARK_SHORT_STRICT, SHARK_SHORT_LOOSE)],
    },
}


def set_flags(text: str, flags: dict) -> str:
    for name, value in flags.items():
        text, count = re.subn(rf"{name} = [^\s#\n]+", f"{name} = {value}", text)
        if count != 1:
            raise RuntimeError(f"flag {name}: expected 1 substitution, got {count}")
    return text


def set_blocks(text: str, blocks: list) -> str:
    for old, new in blocks:
        count = text.count(old)
        if count != 1:
            raise RuntimeError(f"block substitution: expected 1 match, got {count}")
        text = text.replace(old, new)
    return text


def latest_zip() -> Path | None:
    zips = sorted(RESULTS_DIR.glob("backtest-result-*.zip"), key=lambda p: p.stat().st_mtime)
    return zips[-1] if zips else None


def run_backtest(timerange: str) -> dict:
    before = latest_zip()
    cmd = [sys.executable, "-m", "freqtrade", "backtesting", "--config", CONFIG,
           "--strategy", "WolfStrategy", "--strategy-path", STRATEGY_PATH,
           "--timerange", timerange, "--export", "trades", "--cache", "none"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    after = latest_zip()
    if proc.returncode != 0 or after is None or after == before:
        print(proc.stdout[-3000:])
        print(proc.stderr[-2000:])
        raise RuntimeError(f"backtest failed: {timerange}")
    archive = zipfile.ZipFile(after)
    name = [n for n in archive.namelist()
            if n.endswith(".json") and "config" not in n and "market_change" not in n][0]
    payload = json.loads(archive.read(name))
    stats = payload["strategy"]["WolfStrategy"]
    trades = stats["trades"]
    n_short = sum(1 for t in trades if t.get("is_short"))
    n_long = len(trades) - n_short
    return {
        "profit_pct": round(stats["profit_total"] * 100, 1),
        "pf": round(stats.get("profit_factor") or 0.0, 2),
        "dd_pct": round((stats.get("max_drawdown_account") or 0.0) * 100, 1),
        "trades": len(trades),
        "n_long": n_long,
        "n_short": n_short,
    }


def main() -> None:
    original = STRATEGY_FILE.read_text(encoding="utf-8")
    results: dict[str, dict[str, dict]] = {}
    try:
        for variant, spec in VARIANTS.items():
            text = set_flags(original, spec["flags"])
            text = set_blocks(text, spec["blocks"])
            STRATEGY_FILE.write_text(text, encoding="utf-8")
            results[variant] = {}
            for window, wspec in WINDOWS.items():
                cell = run_backtest(wspec["timerange"])
                cell["trades_per_month"] = round(cell["trades"] / wspec["months"], 2)
                results[variant][window] = cell
                print(f">>> {variant:<18} / {window}: profit {cell['profit_pct']:+.1f}%  "
                      f"PF {cell['pf']}  DD {cell['dd_pct']}%  trades {cell['trades']} "
                      f"(L{cell['n_long']}/S{cell['n_short']}, {cell['trades_per_month']}/mo)")
    finally:
        STRATEGY_FILE.write_text(original, encoding="utf-8")

    Path("scratch/ab_short_symmetry_results.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    print("\n=== MATRIX ===")
    header = f"{'variant':<18}" + "".join(f"{w:<44}" for w in WINDOWS)
    print(header)
    for variant, cells in results.items():
        row = f"{variant:<18}"
        for window in WINDOWS:
            c = cells[window]
            row += (f"{c['profit_pct']:+6.1f}% {c['pf']:5.2f} {c['dd_pct']:5.1f}% "
                    f"L{c['n_long']}/S{c['n_short']}({c['trades_per_month']}/mo)   ")
        print(row)


if __name__ == "__main__":
    main()
