"""A/B/N matrix: how much entry frequency can we buy by loosening filters,
and what does it cost in PF/DD?

Context (2026-07-31): live is on pace for ~1-1.7 trades/month on BTC/ETH
(current config), meaning the N=8-10 forward-validation gate takes 5-8
months to reach. The user explicitly wants a MORE aggressive campaign —
accept lower per-trade quality in exchange for faster statistical signal —
which is a different ask than the four frequency attempts already rejected
in wolfstrategy-frequency-tradeoff (those tried to add trades WITHOUT
hurting PF/DD and failed; this deliberately spends quality to buy frequency).

Tests combinations of existing, already-validated toggles (no new logic):
  F1  ENABLE_LONG_SWEEP_VETO      (long opposing-sweep veto)
  F4  ENABLE_EXTENSION_VETO       (block entries >3 ATR from slow EMA)
  F5  ENABLE_FUNDING_VETO / ENABLE_OI_VETO (crowd-positioning veto)
  F3  MAX_SAME_DIRECTION_TRADES   (1 = only one of BTC/ETH per side at a time)
  Retest ENTRY_MODE_RETEST        (True = wait for pullback+rejection; False = chase the break)

Windows: BTC/ETH only (the only live-tradeable pairs; OOS pairs don't
generalize per wolfstrategy-overfit, irrelevant to live frequency planning).
  W1 bear2026 : 2026-01-01 -> 2026-07-02 (~6.1 months)
  W2 bull2025 : 2025-05-01 -> 2025-09-30 (~5.0 months)

Usage: PYTHONPATH=. python scratch/ab_aggressive_entry.py
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
    "ENABLE_LONG_SWEEP_VETO": True,
    "ENABLE_EXTENSION_VETO": True,
    "ENABLE_FUNDING_VETO": True,
    "ENABLE_OI_VETO": True,
    "MAX_SAME_DIRECTION_TRADES": 1,
    "ENTRY_MODE_RETEST": True,
}

VARIANTS = {
    "current": {},
    "no_vetoes": {  # F1/F4/F5 off, keep F3 + retest
        "ENABLE_LONG_SWEEP_VETO": False, "ENABLE_EXTENSION_VETO": False,
        "ENABLE_FUNDING_VETO": False, "ENABLE_OI_VETO": False,
    },
    "allow_both_pairs": {"MAX_SAME_DIRECTION_TRADES": 2},  # F3 off
    "chase_breakdown": {"ENTRY_MODE_RETEST": False},        # skip the retest wait
    "aggressive_all": {  # combine everything above
        "ENABLE_LONG_SWEEP_VETO": False, "ENABLE_EXTENSION_VETO": False,
        "ENABLE_FUNDING_VETO": False, "ENABLE_OI_VETO": False,
        "MAX_SAME_DIRECTION_TRADES": 2, "ENTRY_MODE_RETEST": False,
    },
}


def set_flags(text: str, flags: dict) -> str:
    for name, value in flags.items():
        text, count = re.subn(rf"{name} = \w+", f"{name} = {value}", text)
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
        "wins": stats["wins"],
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
                print(f">>> {variant} / {window}")
                cell = run_backtest(spec["timerange"])
                cell["trades_per_month"] = round(cell["trades"] / spec["months"], 2)
                results[variant][window] = cell
                print(f"    profit {cell['profit_pct']:+.1f}%  PF {cell['pf']}  "
                      f"DD {cell['dd_pct']}%  trades {cell['trades']} "
                      f"({cell['trades_per_month']}/mo)  deep {cell['deep_losers']}")
    finally:
        STRATEGY_FILE.write_text(original, encoding="utf-8")

    Path("scratch/ab_aggressive_entry_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\n=== MATRIX (profit% | PF | DD% | trades (t/mo) | deep losers) ===")
    header = f"{'variant':<18}" + "".join(f"{w:<34}" for w in WINDOWS)
    print(header)
    for variant, cells in results.items():
        row = f"{variant:<18}"
        for window in WINDOWS:
            c = cells[window]
            row += f"{c['profit_pct']:+6.1f}% {c['pf']:5.2f} {c['dd_pct']:5.1f}% {c['trades']:2d}t({c['trades_per_month']:.1f}/mo) {c['deep_losers']:2d}d  "
        print(row)


if __name__ == "__main__":
    main()
