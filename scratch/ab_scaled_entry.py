"""A/B test: SCALED ENTRY (ENABLE_SCALED_ENTRY).

Context (2026-07-31): after two rejected fast-exit ideas (fixed-% VWAP
reclaim 2026-06-21, ATR-normalized variant 2026-07-31), this tests a
different lever — take LESS risk on the entry itself instead of trying to
exit faster. Only SCALED_ENTRY_INITIAL_FRACTION of the full risk-sized stake
fires at the trigger candle; the rest is added only if a closed candle within
SCALED_ENTRY_CONFIRM_BARS confirms continuation (still on the correct side of
VWAP, closes further in the trade's favor). Exit logic is untouched.

Same three-window methodology as scratch/ab_extension_veto.py /
scratch/ab_vwap_atr_exit.py:
  W1 in-sample bear/chop : BTC/ETH  2026-01-01 -> 2026-07-02
  W2 bull regime         : BTC/ETH  2025-05-01 -> 2025-09-30
  W3 out-of-sample pairs : 6 pairs  2026-01-01 -> 2026-07-02

Metrics per cell: net profit %, profit factor, max account DD, trades,
deep losers (margin ROI <= -12%), avg stake (should shrink vs baseline
when a lot of trades never get the top-up). Restores the strategy file
afterwards.

Usage: PYTHONPATH=. python scratch/ab_scaled_entry.py
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
OOS_PAIRS = ["SOL/USDT:USDT", "ADA/USDT:USDT", "AVAX/USDT:USDT",
             "XRP/USDT:USDT", "DOGE/USDT:USDT", "LINK/USDT:USDT"]

VARIANTS = {
    "scaled_off": {"ENABLE_SCALED_ENTRY": False},
    "scaled_on":  {"ENABLE_SCALED_ENTRY": True},
}

WINDOWS = {
    "W1_bear2026": {"strategy": "WolfStrategy", "timerange": "20260101-20260702", "pairs": None},
    "W2_bull2025": {"strategy": "WolfStrategy", "timerange": "20250501-20250930", "pairs": None},
    "W3_oos2026": {"strategy": "WolfStrategyOOS", "timerange": "20260101-20260702", "pairs": OOS_PAIRS},
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


def run_backtest(strategy: str, timerange: str, pairs: list[str] | None) -> dict:
    before = latest_zip()
    cmd = [sys.executable, "-m", "freqtrade", "backtesting", "--config", CONFIG,
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
    winners = [t["profit_ratio"] for t in trades if t["profit_ratio"] > 0]
    stakes = [t["stake_amount"] for t in trades if t.get("stake_amount")]
    topped_up = [t for t in trades if len(t.get("orders", []) or []) > 1]
    return {
        "profit_pct": round(stats["profit_total"] * 100, 1),
        "pf": round(stats.get("profit_factor") or 0.0, 2),
        "dd_pct": round((stats.get("max_drawdown_account") or 0.0) * 100, 1),
        "trades": len(trades),
        "wins": stats["wins"],
        "deep_losers": len(deep),
        "avg_win_pct": round(sum(winners) / len(winners) * 100, 1) if winners else 0.0,
        "avg_stake": round(sum(stakes) / len(stakes), 1) if stakes else 0.0,
        "topped_up": len(topped_up),
        "zip": after.name,
    }


def main() -> None:
    original = STRATEGY_FILE.read_text(encoding="utf-8")
    results: dict[str, dict[str, dict]] = {}
    try:
        for variant, flags in VARIANTS.items():
            STRATEGY_FILE.write_text(set_flags(original, flags), encoding="utf-8")
            results[variant] = {}
            for window, spec in WINDOWS.items():
                print(f">>> {variant} / {window}")
                cell = run_backtest(spec["strategy"], spec["timerange"], spec["pairs"])
                results[variant][window] = cell
                print(f"    profit {cell['profit_pct']:+.1f}%  PF {cell['pf']}  "
                      f"DD {cell['dd_pct']}%  trades {cell['trades']}  deep {cell['deep_losers']}  "
                      f"avgWin {cell['avg_win_pct']}%  avgStake {cell['avg_stake']}  "
                      f"toppedUp {cell['topped_up']}")
    finally:
        STRATEGY_FILE.write_text(original, encoding="utf-8")

    Path("scratch/ab_scaled_entry_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\n=== MATRIX (profit% | PF | DD% | trades | deep losers) ===")
    header = f"{'variant':<14}" + "".join(f"{w:<38}" for w in WINDOWS)
    print(header)
    for variant, cells in results.items():
        row = f"{variant:<14}"
        for window in WINDOWS:
            c = cells[window]
            row += f"{c['profit_pct']:+7.1f}% {c['pf']:5.2f} {c['dd_pct']:5.1f}% {c['trades']:3d}t {c['deep_losers']:2d}d   "
        print(row)


if __name__ == "__main__":
    main()
