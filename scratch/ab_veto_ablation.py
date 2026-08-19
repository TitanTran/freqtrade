"""Ablation matrix: WHICH of F1/F4/F5 actually drives the frequency gain
seen in scratch/ab_aggressive_entry.py ("no_vetoes"), and which drives the
new deep losers?

Context (2026-07-31): the blunt "all three off" test showed +2.5-4x trade
frequency with PF still >1 in both windows, but also more deep losers (1->4
bear, 1->2 bull). Before deploying "turn off F1+F4+F5" live, decompose that
aggregate result per-filter: maybe only one filter is actually gating most
of the missed trades, letting us keep the other two (kept protections)
instead of an all-or-nothing choice. F4 in particular was built directly
from the live-loss audit signature (entries >3.3 ATR extended) — worth
knowing if IT specifically is what's producing the new deep losers.

8 combinations (2^3: F1, F4, F5) x 2 windows (BTC/ETH only, the live pairs):
  W1 bear2026 : 2026-01-01 -> 2026-07-02
  W2 bull2025 : 2025-05-01 -> 2025-09-30
F3 (concurrency) and retest mode are held at their CURRENT live values in
every cell (isolating just the veto-filter question).

Usage: PYTHONPATH=. python scratch/ab_veto_ablation.py
"""

import itertools
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

# F5 funding + OI toggled together as one "positioning veto" dimension.
DIMENSIONS = {
    "F1": "ENABLE_LONG_SWEEP_VETO",
    "F4": "ENABLE_EXTENSION_VETO",
}
F5_FLAGS = ("ENABLE_FUNDING_VETO", "ENABLE_OI_VETO")


def variant_name(on_flags: tuple[str, ...]) -> str:
    return "+".join(on_flags) if on_flags else "none"


def build_flags(on: set[str]) -> dict:
    flags = {}
    for label, attr in DIMENSIONS.items():
        flags[attr] = label in on
    for attr in F5_FLAGS:
        flags[attr] = "F5" in on
    return flags


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
        "deep_losers": len(deep),
        "zip_name": after.name,
    }


def main() -> None:
    original = STRATEGY_FILE.read_text(encoding="utf-8")
    all_labels = list(DIMENSIONS.keys()) + ["F5"]
    results: dict[str, dict[str, dict]] = {}
    try:
        for r in range(len(all_labels) + 1):
            for combo in itertools.combinations(all_labels, r):
                on = set(combo)
                name = variant_name(tuple(sorted(on))) if on else "all_off"
                flags = build_flags(on)
                STRATEGY_FILE.write_text(set_flags(original, flags), encoding="utf-8")
                results[name] = {}
                for window, spec in WINDOWS.items():
                    cell = run_backtest(spec["timerange"])
                    cell["trades_per_month"] = round(cell["trades"] / spec["months"], 2)
                    results[name][window] = cell
                    print(f">>> {name:<14} / {window}: profit {cell['profit_pct']:+.1f}%  "
                          f"PF {cell['pf']}  DD {cell['dd_pct']}%  trades {cell['trades']} "
                          f"({cell['trades_per_month']}/mo)  deep {cell['deep_losers']}")
    finally:
        STRATEGY_FILE.write_text(original, encoding="utf-8")

    Path("scratch/ab_veto_ablation_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\n=== MATRIX (on-flags = vetoes ACTIVE; 'all_off' = F1+F4+F5 all disabled) ===")
    header = f"{'vetoes ON':<14}" + "".join(f"{w:<40}" for w in WINDOWS)
    print(header)
    for name, cells in results.items():
        row = f"{name:<14}"
        for window in WINDOWS:
            c = cells[window]
            row += (f"{c['profit_pct']:+6.1f}% {c['pf']:5.2f} {c['dd_pct']:5.1f}% "
                    f"{c['trades']:2d}t({c['trades_per_month']:.1f}/mo) {c['deep_losers']:2d}d   ")
        print(row)


if __name__ == "__main__":
    main()
