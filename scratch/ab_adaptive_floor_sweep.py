"""Follow-up sweep after ab_adaptive_floor_tuning.py: the first tuned
candidate (45th pctl / 14d window / LO=14) flipped W1_bear2026 PF to 0.92
(below 1.0) despite gaining frequency — user's stated priority is PF
stability over max frequency, so that candidate is rejected. This sweeps
intermediate points on the (percentile, window, LO) frontier to find the
loosest setting that still keeps PF >= 1.0 in both canonical windows.

Usage: PYTHONPATH=. python scratch/ab_adaptive_floor_sweep.py
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

# (pctl, window_bars_4h, min_periods_4h, lo)
VARIANTS = {
    "mid_a_55_21d_17":  {"ADX_REGIME_TARGET_PCTL": 55.0, "ADAPTIVE_WINDOW_BARS_4H": 126, "ADAPTIVE_MIN_PERIODS_4H": 63, "ADX_REGIME_MIN_LO": 17.0},
    "mid_b_50_21d_17":  {"ADX_REGIME_TARGET_PCTL": 50.0, "ADAPTIVE_WINDOW_BARS_4H": 126, "ADAPTIVE_MIN_PERIODS_4H": 63, "ADX_REGIME_MIN_LO": 17.0},
    "mid_c_55_14d_17":  {"ADX_REGIME_TARGET_PCTL": 55.0, "ADAPTIVE_WINDOW_BARS_4H": 84,  "ADAPTIVE_MIN_PERIODS_4H": 42, "ADX_REGIME_MIN_LO": 17.0},
    "mid_d_50_14d_17":  {"ADX_REGIME_TARGET_PCTL": 50.0, "ADAPTIVE_WINDOW_BARS_4H": 84,  "ADAPTIVE_MIN_PERIODS_4H": 42, "ADX_REGIME_MIN_LO": 17.0},
    "mid_e_45_21d_17":  {"ADX_REGIME_TARGET_PCTL": 45.0, "ADAPTIVE_WINDOW_BARS_4H": 126, "ADAPTIVE_MIN_PERIODS_4H": 63, "ADX_REGIME_MIN_LO": 17.0},
    "mid_f_50_14d_14":  {"ADX_REGIME_TARGET_PCTL": 50.0, "ADAPTIVE_WINDOW_BARS_4H": 84,  "ADAPTIVE_MIN_PERIODS_4H": 42, "ADX_REGIME_MIN_LO": 14.0},
}
COMMON = {"ENABLE_ADAPTIVE_THRESHOLDS": True}


def set_flags(text: str, flags: dict) -> str:
    for name, value in flags.items():
        text, count = re.subn(rf"{name} = [^\s#\n]+", f"{name} = {value}", text)
        if count != 1:
            raise RuntimeError(f"flag {name}: expected 1 substitution, got {count}")
    return text


def latest_zip() -> Path | None:
    zips = sorted(RESULTS_DIR.glob("backtest-result-*.zip"), key=lambda p: p.stat().st_mtime)
    return zips[-1] if zips else None


def run_backtest(timerange: str) -> dict:
    before = latest_zip()
    cmd = [sys.executable, "-m", "freqtrade", "backtesting", "--config", CONFIG,
           "--strategy", "WolfStrategy", "--strategy-path", STRATEGY_PATH,
           "--timerange", timerange, "--export", "trades"]
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
    return {
        "profit_pct": round(stats["profit_total"] * 100, 1),
        "pf": round(stats.get("profit_factor") or 0.0, 2),
        "dd_pct": round((stats.get("max_drawdown_account") or 0.0) * 100, 1),
        "trades": len(trades),
    }


def main() -> None:
    original = STRATEGY_FILE.read_text(encoding="utf-8")
    results: dict[str, dict[str, dict]] = {}
    try:
        for variant, overrides in VARIANTS.items():
            flags = {**COMMON, **overrides}
            STRATEGY_FILE.write_text(set_flags(original, flags), encoding="utf-8")
            results[variant] = {}
            for window, spec in WINDOWS.items():
                cell = run_backtest(spec["timerange"])
                cell["trades_per_month"] = round(cell["trades"] / spec["months"], 2)
                results[variant][window] = cell
                print(f">>> {variant:<18} / {window}: profit {cell['profit_pct']:+.1f}%  "
                      f"PF {cell['pf']}  DD {cell['dd_pct']}%  trades {cell['trades']} "
                      f"({cell['trades_per_month']}/mo)")
    finally:
        STRATEGY_FILE.write_text(original, encoding="utf-8")

    Path("scratch/ab_adaptive_floor_sweep_results.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    print("\n=== MATRIX ===")
    header = f"{'variant':<18}" + "".join(f"{w:<38}" for w in WINDOWS)
    print(header)
    for variant, cells in results.items():
        row = f"{variant:<18}"
        for window in WINDOWS:
            c = cells[window]
            row += (f"{c['profit_pct']:+6.1f}% {c['pf']:5.2f} {c['dd_pct']:5.1f}% "
                    f"{c['trades']:2d}t({c['trades_per_month']:.1f}/mo)   ")
        print(row)


if __name__ == "__main__":
    main()
