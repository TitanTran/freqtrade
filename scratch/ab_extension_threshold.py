"""Follow-up to scratch/ab_veto_ablation.py: F4 (extension veto) turned out to
be the ENTIRE driver of the frequency gain, and the 4 new deep losers it lets
through in bear2026 all carry |extension_atr| 4.4-6.9 — exactly the audit
signature F4 was built from (originally >=3.3 ATR in the 3 live losses).

Rather than a binary on/off, treat EXTENSION_MAX_ATR as a dial: does raising
it from 3.0 partially open the frequency gap while still blocking the WORST
extensions (the ones that actually became deep losers)?

F1/F5 held ON (F1 helps for free, F5 is inert in-sample) at every cell.

Usage: PYTHONPATH=. python scratch/ab_extension_threshold.py
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

THRESHOLDS = [3.0, 4.0, 5.0, 6.0, 8.0]  # 8.0 ~= effectively off for this data


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
        for thr in THRESHOLDS:
            flags = {
                "ENABLE_LONG_SWEEP_VETO": True,
                "ENABLE_EXTENSION_VETO": True,
                "ENABLE_FUNDING_VETO": True,
                "ENABLE_OI_VETO": True,
                "EXTENSION_MAX_ATR": thr,
            }
            name = f"MAX_ATR={thr}"
            STRATEGY_FILE.write_text(set_flags(original, flags), encoding="utf-8")
            results[name] = {}
            for window, spec in WINDOWS.items():
                cell = run_backtest(spec["timerange"])
                cell["trades_per_month"] = round(cell["trades"] / spec["months"], 2)
                results[name][window] = cell
                print(f">>> {name:<12} / {window}: profit {cell['profit_pct']:+.1f}%  "
                      f"PF {cell['pf']}  DD {cell['dd_pct']}%  trades {cell['trades']} "
                      f"({cell['trades_per_month']}/mo)  deep {cell['deep_losers']}")
    finally:
        STRATEGY_FILE.write_text(original, encoding="utf-8")

    Path("scratch/ab_extension_threshold_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\n=== MATRIX ===")
    header = f"{'threshold':<12}" + "".join(f"{w:<40}" for w in WINDOWS)
    print(header)
    for name, cells in results.items():
        row = f"{name:<12}"
        for window in WINDOWS:
            c = cells[window]
            row += (f"{c['profit_pct']:+6.1f}% {c['pf']:5.2f} {c['dd_pct']:5.1f}% "
                    f"{c['trades']:2d}t({c['trades_per_month']:.1f}/mo) {c['deep_losers']:2d}d   ")
        print(row)


if __name__ == "__main__":
    main()
