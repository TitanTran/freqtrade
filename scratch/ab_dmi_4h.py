"""A/B validation: regime-classifier DMI direction read at 4H (fix) vs the
original 1H-period DMI (baseline). Same 3-window methodology as ab_matrix.py.

Usage: PYTHONPATH=. python scratch/ab_dmi_4h.py
"""

import json
import subprocess
import sys
import zipfile
from pathlib import Path

STRATEGY_FILE = Path("user_data/strategies/WolfStrategyV1/WolfStrategy.py")
RESULTS_DIR = Path("user_data/backtest_results")
CONFIG = "user_data/strategies/config.json"
STRATEGY_PATH = "user_data/strategies/WolfStrategyV1"
DEEP_LOSS_THRESHOLD = -0.12
OOS_PAIRS = ["SOL/USDT:USDT", "ADA/USDT:USDT", "AVAX/USDT:USDT",
             "XRP/USDT:USDT", "DOGE/USDT:USDT", "LINK/USDT:USDT"]

WINDOWS = {
    "W1_bear2026": {"strategy": "WolfStrategy", "timerange": "20260101-20260702", "pairs": None},
    "W2_bull2025": {"strategy": "WolfStrategy", "timerange": "20250501-20250930", "pairs": None},
    "W3_oos2026": {"strategy": "WolfStrategyOOS", "timerange": "20260101-20260702", "pairs": OOS_PAIRS},
}


def latest_zip() -> Path | None:
    zips = sorted(RESULTS_DIR.glob("backtest-result-*.zip"), key=lambda p: p.stat().st_mtime)
    return zips[-1] if zips else None


def run_backtest(strategy: str, timerange: str, pairs: list[str] | None) -> dict:
    before = latest_zip()
    cmd = [r"D:\PYTHON\freqtrade\ft_venv\Scripts\python.exe", "-m", "freqtrade", "backtesting", "--config", CONFIG,
           "--strategy", strategy, "--strategy-path", STRATEGY_PATH,
           "--timerange", timerange, "--export", "trades"]
    if pairs:
        cmd += ["--pairs", *pairs]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    after = latest_zip()
    if proc.returncode != 0 or after is None or after == before:
        print(proc.stdout[-3000:])
        print(proc.stderr[-2000:])
        raise RuntimeError(f"backtest failed: {strategy} {timerange}")
    archive = zipfile.ZipFile(after)
    name = [n for n in archive.namelist()
            if n.endswith(".json") and "config" not in n and "market_change" not in n][0]
    payload = json.loads(archive.read(name))
    stats = payload["strategy"][strategy]
    trades = stats["trades"]
    deep = [t for t in trades if t["profit_ratio"] <= DEEP_LOSS_THRESHOLD]
    return {
        "profit_pct": round(stats["profit_total"] * 100, 1),
        "pf": round(stats.get("profit_factor") or 0.0, 2),
        "dd_pct": round((stats.get("max_drawdown_account") or 0.0) * 100, 1),
        "trades": len(trades),
        "wins": stats["wins"],
        "losses": stats["losses"],
        "deep_losers": len(deep),
        "zip": after.name,
    }


def main() -> None:
    fixed_text = STRATEGY_FILE.read_text(encoding="utf-8")
    proc = subprocess.run(["git", "show", f"HEAD:{STRATEGY_FILE.as_posix()}"],
                           capture_output=True, text=True, check=True)
    baseline_text = proc.stdout

    variants = {"baseline_1h_dmi": baseline_text, "fixed_4h_dmi": fixed_text}
    results: dict[str, dict[str, dict]] = {}
    try:
        for variant, text in variants.items():
            STRATEGY_FILE.write_text(text, encoding="utf-8")
            results[variant] = {}
            for window, spec in WINDOWS.items():
                print(f">>> {variant} / {window}")
                cell = run_backtest(spec["strategy"], spec["timerange"], spec["pairs"])
                results[variant][window] = cell
                print(f"    profit {cell['profit_pct']:+.1f}%  PF {cell['pf']}  "
                      f"DD {cell['dd_pct']}%  trades {cell['trades']} "
                      f"(W{cell['wins']}/L{cell['losses']})  deep {cell['deep_losers']}")
    finally:
        STRATEGY_FILE.write_text(fixed_text, encoding="utf-8")

    Path("scratch/ab_dmi_4h_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\n=== MATRIX (profit% | PF | DD% | trades | deep losers) ===")
    header = f"{'variant':<18}" + "".join(f"{w:<38}" for w in WINDOWS)
    print(header)
    for variant, cells in results.items():
        row = f"{variant:<18}"
        for window in WINDOWS:
            c = cells[window]
            row += f"{c['profit_pct']:+7.1f}% {c['pf']:5.2f} {c['dd_pct']:5.1f}% {c['trades']:3d}t {c['deep_losers']:2d}d   "
        print(row)


if __name__ == "__main__":
    main()
