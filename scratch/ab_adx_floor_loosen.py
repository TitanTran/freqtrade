"""Follow-up to ab_adaptive_floor_sweep.py: current deployed setting is
mid_b_50_21d_17 (ADX_REGIME_TARGET_PCTL=50, 21d window, LO=17). Live bot has
gone ~12 days without a trade (last close 2026-08-01) despite that tuning.
This sweeps LOOSER points beyond what's currently deployed -- lower target
percentile and/or lower LO clamp, same 21d window (14d window already
rejected per ab_adaptive_floor_tuning.py: flips bear PF < 1.0 in every
combo) -- to see whether more frequency is available without breaking PF.

Usage: PYTHONPATH=. python scratch/ab_adx_floor_loosen.py
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

# All keep the 21d window (126/63 bars) -- only pctl/LO move.
VARIANTS = {
    "baseline_50_17":  {"ADX_REGIME_TARGET_PCTL": 50.0, "ADX_REGIME_MIN_LO": 17.0},
    "loose_a_45_17":   {"ADX_REGIME_TARGET_PCTL": 45.0, "ADX_REGIME_MIN_LO": 17.0},
    "loose_b_40_17":   {"ADX_REGIME_TARGET_PCTL": 40.0, "ADX_REGIME_MIN_LO": 17.0},
    "loose_c_50_14":   {"ADX_REGIME_TARGET_PCTL": 50.0, "ADX_REGIME_MIN_LO": 14.0},
    "loose_d_45_14":   {"ADX_REGIME_TARGET_PCTL": 45.0, "ADX_REGIME_MIN_LO": 14.0},
    "loose_e_40_12":   {"ADX_REGIME_TARGET_PCTL": 40.0, "ADX_REGIME_MIN_LO": 12.0},
    "loose_f_35_12":   {"ADX_REGIME_TARGET_PCTL": 35.0, "ADX_REGIME_MIN_LO": 12.0},
}
COMMON = {
    "ENABLE_ADAPTIVE_THRESHOLDS": True,
    "ADAPTIVE_WINDOW_BARS_4H": 126,
    "ADAPTIVE_MIN_PERIODS_4H": 63,
}


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

    Path("scratch/ab_adx_floor_loosen_results.json").write_text(
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
