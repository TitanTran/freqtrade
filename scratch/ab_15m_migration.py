"""A/B validation: base timeframe 1h (baseline, git HEAD) vs 15m (migrated,
current working tree) across the standard 3-window methodology.

Usage: PYTHONPATH=. python scratch/ab_15m_migration.py
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
PYTHON = r"D:\PYTHON\freqtrade\ft_venv\Scripts\python.exe"
DEEP_LOSS_THRESHOLD = -0.12
OOS_PAIRS = ["SOL/USDT:USDT", "ADA/USDT:USDT", "AVAX/USDT:USDT",
             "XRP/USDT:USDT", "DOGE/USDT:USDT", "LINK/USDT:USDT"]

WINDOWS = {
    "W1_bear2026": {"strategy": "WolfStrategy", "timerange": "20260101-20260702", "pairs": None},
    "W2_bull2025": {"strategy": "WolfStrategy", "timerange": "20250501-20250930", "pairs": None},
    "W3_oos2026": {"strategy": "WolfStrategyOOS", "timerange": "20260101-20260702", "pairs": OOS_PAIRS},
}

VARIANTS = {
    "baseline_1h": "1h",
    "migrated_15m": "15m",
}


def latest_zip() -> Path | None:
    zips = sorted(RESULTS_DIR.glob("backtest-result-*.zip"), key=lambda p: p.stat().st_mtime)
    return zips[-1] if zips else None


def run_backtest(strategy: str, timeframe: str, timerange: str, pairs: list[str] | None) -> dict:
    before = latest_zip()
    cmd = [PYTHON, "-m", "freqtrade", "backtesting", "--config", CONFIG,
           "--strategy", strategy, "--strategy-path", STRATEGY_PATH,
           "--timeframe", timeframe,
           "--timerange", timerange, "--export", "trades"]
    if pairs:
        cmd += ["--pairs", *pairs]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    after = latest_zip()
    if proc.returncode != 0 or after is None or after == before:
        print(proc.stdout[-3000:])
        print(proc.stderr[-2000:])
        raise RuntimeError(f"backtest failed: {strategy} {timeframe} {timerange}")
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

    texts = {"baseline_1h": baseline_text, "migrated_15m": fixed_text}
    results: dict[str, dict[str, dict]] = {}
    try:
        for variant, timeframe in VARIANTS.items():
            STRATEGY_FILE.write_text(texts[variant], encoding="utf-8")
            results[variant] = {}
            for window, spec in WINDOWS.items():
                print(f">>> {variant} ({timeframe}) / {window}")
                cell = run_backtest(spec["strategy"], timeframe, spec["timerange"], spec["pairs"])
                results[variant][window] = cell
                print(f"    profit {cell['profit_pct']:+.1f}%  PF {cell['pf']}  "
                      f"DD {cell['dd_pct']}%  trades {cell['trades']} "
                      f"(W{cell['wins']}/L{cell['losses']})  deep {cell['deep_losers']}")
    finally:
        STRATEGY_FILE.write_text(fixed_text, encoding="utf-8")

    Path("scratch/ab_15m_migration_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
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
