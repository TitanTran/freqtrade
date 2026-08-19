"""Follow-up to ab_adx_floor_loosen.py (ADX floor confirmed tapped out,
2026-08-13): sweeps two DIFFERENT untested levers on top of the current
deployed ADX config (50pctl/21d/LO17) to see if either buys real frequency
without breaking PF:

  1. REGIME_PERSIST_BARS: how many 1H bars an up/down regime must hold
     before LONG_USE_CONFIRMED/SHORT_USE_CONFIRMED count it. Currently 6
     (halved from 12 on 2026-07-31 "for faster bull capture"). Live log
     (2026-08-13) shows regime_down_gate OK only ~1% of hours -- testing
     whether the persistence window itself (not just the ADX floor under
     it) is now the binding constraint on the short side.
  2. LONG_VOL_RATIO_TARGET_PCTL / SHORT_VOL_RATIO_TARGET_PCTL: same
     percentile-of-own-history mechanism as the ADX floor, applied to
     volume participation. Currently 55/55. Never swept for loosening.

Usage: PYTHONPATH=. python scratch/ab_other_frequency_levers.py
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

# Baseline = currently deployed ADX config, everything else as-is in the file.
VARIANTS = {
    "baseline":              {},
    "persist_4":             {"REGIME_PERSIST_BARS": 4},
    "persist_3":             {"REGIME_PERSIST_BARS": 3},
    "persist_2":             {"REGIME_PERSIST_BARS": 2},
    "vol_pctl_45":           {"LONG_VOL_RATIO_TARGET_PCTL": 45.0, "SHORT_VOL_RATIO_TARGET_PCTL": 45.0},
    "vol_pctl_35":           {"LONG_VOL_RATIO_TARGET_PCTL": 35.0, "SHORT_VOL_RATIO_TARGET_PCTL": 35.0},
    "persist_3_vol_pctl_45": {"REGIME_PERSIST_BARS": 3, "LONG_VOL_RATIO_TARGET_PCTL": 45.0, "SHORT_VOL_RATIO_TARGET_PCTL": 45.0},
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
            STRATEGY_FILE.write_text(set_flags(original, overrides), encoding="utf-8")
            results[variant] = {}
            for window, spec in WINDOWS.items():
                cell = run_backtest(spec["timerange"])
                cell["trades_per_month"] = round(cell["trades"] / spec["months"], 2)
                results[variant][window] = cell
                print(f">>> {variant:<24} / {window}: profit {cell['profit_pct']:+.1f}%  "
                      f"PF {cell['pf']}  DD {cell['dd_pct']}%  trades {cell['trades']} "
                      f"({cell['trades_per_month']}/mo)")
    finally:
        STRATEGY_FILE.write_text(original, encoding="utf-8")

    Path("scratch/ab_other_frequency_levers_results.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    print("\n=== MATRIX ===")
    header = f"{'variant':<24}" + "".join(f"{w:<38}" for w in WINDOWS)
    print(header)
    for variant, cells in results.items():
        row = f"{variant:<24}"
        for window in WINDOWS:
            c = cells[window]
            row += (f"{c['profit_pct']:+6.1f}% {c['pf']:5.2f} {c['dd_pct']:5.1f}% "
                    f"{c['trades']:2d}t({c['trades_per_month']:.1f}/mo)   ")
        print(row)


if __name__ == "__main__":
    main()
