"""User request (2026-08-14): apply the "Perfect Entry" 3-timeframe framework
EXACTLY as specified (image), "balanced" tier — Trend=H4, Structure=H1
(Supply/Demand zone, F6), Signal=m15 (Market Structure Shift + Fair Value
Gap) — accepting a full break from the existing shark/breakdown/retest/
Wyckoff entry architecture.

Added ENABLE_PERFECT_ENTRY_MODE (WolfStrategy.py): when True, REPLACES every
other entry path. Verified with a 1-month smoke backtest (2026-06) before
this run: pipeline runs end-to-end, produces a trade, no crashes.

Tests the new mode ON against the current live-deployed OFF baseline (no
other flags touched):
  baseline_shark_system : ENABLE_PERFECT_ENTRY_MODE=False (current production)
  perfect_entry_mode    : ENABLE_PERFECT_ENTRY_MODE=True  (exact 3-TF spec)

Usage: PYTHONPATH=. python scratch/ab_perfect_entry_mode.py
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

VARIANTS = {
    "baseline_shark_system": {"ENABLE_PERFECT_ENTRY_MODE": False},
    "perfect_entry_mode": {"ENABLE_PERFECT_ENTRY_MODE": True},
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
        for variant, flags in VARIANTS.items():
            STRATEGY_FILE.write_text(set_flags(original, flags), encoding="utf-8")
            results[variant] = {}
            for window, spec in WINDOWS.items():
                cell = run_backtest(spec["timerange"])
                cell["trades_per_month"] = round(cell["trades"] / spec["months"], 2)
                results[variant][window] = cell
                print(f">>> {variant:<22} / {window}: profit {cell['profit_pct']:+.1f}%  "
                      f"PF {cell['pf']}  DD {cell['dd_pct']}%  trades {cell['trades']} "
                      f"({cell['trades_per_month']}/mo)  deep {cell['deep_losers']}")
    finally:
        STRATEGY_FILE.write_text(original, encoding="utf-8")

    Path("scratch/ab_perfect_entry_mode_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\n=== MATRIX ===")
    header = f"{'variant':<22}" + "".join(f"{w:<40}" for w in WINDOWS)
    print(header)
    for variant, cells in results.items():
        row = f"{variant:<22}"
        for window in WINDOWS:
            c = cells[window]
            row += (f"{c['profit_pct']:+6.1f}% {c['pf']:5.2f} {c['dd_pct']:5.1f}% "
                    f"{c['trades']:2d}t({c['trades_per_month']:.1f}/mo) {c['deep_losers']:2d}d   ")
        print(row)


if __name__ == "__main__":
    main()
