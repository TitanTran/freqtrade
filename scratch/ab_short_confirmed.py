"""Targeted fix test: with F1/F4/F5 off (per user request), diagnosed bull2025
loss to shark_short_1h (6/7 losers) and specifically a 2025-06-23 BTC+ETH
same-candle double-short (the exact F3 disaster pattern) plus 3 separate
BTC shorts in late Aug 2025 that each got stopped shorting brief 4H dips
inside an ongoing uptrend.

Tests two independent, non-veto fixes against the all-off baseline
(bear2026 PF 1.33 / bull2025 PF 0.94, from scratch/ab_all_filters_off.py):
  short_confirmed    : SHORT_USE_CONFIRMED=True (shorts now require
                       regime_down_confirmed persistence, mirroring longs)
  short_confirmed_f3 : same + MAX_SAME_DIRECTION_TRADES=1 restored (this is
                       a correlation/concentration guard, not a signal-
                       quality veto, so restoring it isn't "turning a filter
                       back on" in the same sense as F1/F4/F5)

F1/F4/F5 stay OFF in both cells (per user's explicit request).

Usage: PYTHONPATH=. python scratch/ab_short_confirmed.py
"""

import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

STRATEGY_FILE = Path("user_data/strategies/WolfStrategyV1/WolfStrategy.py")
RESULTS_DIR = Path("user_data/backtest_results")
CONFIG = "user_data/strategies/config.json"
STRATEGY_PATH = "user_data/strategies/WolfStrategyV1"
DEEP_LOSS_THRESHOLD = -0.12

WINDOWS = {
    "W1_bear2026": {"timerange": "20260101-20260702", "months": 6.07},
    "W2_bull2025": {"timerange": "20250501-20250930", "months": 5.03},
}

BASE_FLAGS = {
    "ENABLE_LONG_SWEEP_VETO": False,
    "ENABLE_EXTENSION_VETO": False,
    "ENABLE_FUNDING_VETO": False,
    "ENABLE_OI_VETO": False,
    "ENTRY_MODE_RETEST": True,
    "SHORT_USE_CONFIRMED": False,
    "MAX_SAME_DIRECTION_TRADES": 0,
}

VARIANTS = {
    "all_off_baseline": {},
    "short_confirmed": {"SHORT_USE_CONFIRMED": True},
    "short_confirmed_f3": {"SHORT_USE_CONFIRMED": True, "MAX_SAME_DIRECTION_TRADES": 1},
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
    deep = [t for t in trades if t["profit_ratio"] <= DEEP_LOSS_THRESHOLD]
    return {
        "profit_pct": round(stats["profit_total"] * 100, 1),
        "pf": round(stats.get("profit_factor") or 0.0, 2),
        "dd_pct": round((stats.get("max_drawdown_account") or 0.0) * 100, 1),
        "trades": len(trades),
        "deep_losers": len(deep),
    }


def main() -> None:
    original = STRATEGY_FILE.read_text(encoding="utf-8")
    results: dict[str, dict[str, dict]] = {}
    try:
        for variant, overrides in VARIANTS.items():
            flags = {**BASE_FLAGS, **overrides}
            STRATEGY_FILE.write_text(set_flags(original, flags), encoding="utf-8")
            results[variant] = {}
            for window, spec in WINDOWS.items():
                cell = run_backtest(spec["timerange"])
                cell["trades_per_month"] = round(cell["trades"] / spec["months"], 2)
                results[variant][window] = cell
                print(f">>> {variant:<20} / {window}: profit {cell['profit_pct']:+.1f}%  "
                      f"PF {cell['pf']}  DD {cell['dd_pct']}%  trades {cell['trades']} "
                      f"({cell['trades_per_month']}/mo)  deep {cell['deep_losers']}")
    finally:
        STRATEGY_FILE.write_text(original, encoding="utf-8")

    Path("scratch/ab_short_confirmed_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\n=== MATRIX ===")
    header = f"{'variant':<20}" + "".join(f"{w:<40}" for w in WINDOWS)
    print(header)
    for variant, cells in results.items():
        row = f"{variant:<20}"
        for window in WINDOWS:
            c = cells[window]
            row += (f"{c['profit_pct']:+6.1f}% {c['pf']:5.2f} {c['dd_pct']:5.1f}% "
                    f"{c['trades']:2d}t({c['trades_per_month']:.1f}/mo) {c['deep_losers']:2d}d   ")
        print(row)


if __name__ == "__main__":
    main()
