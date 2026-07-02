"""Out-of-sample validation wrapper for WolfStrategy.

Only widens the ALLOWED_PAIRS guard so backtests can run on pairs the
strategy was NEVER tuned on. Zero logic changes — any edge measured here is
evidence the entry model generalizes; any collapse is curve-fit evidence.
NEVER deploy this class live.
"""

from WolfStrategy import WolfStrategy


class WolfStrategyOOS(WolfStrategy):
    ALLOWED_PAIRS = {
        "SOL/USDT:USDT", "ADA/USDT:USDT", "AVAX/USDT:USDT",
        "XRP/USDT:USDT", "DOGE/USDT:USDT", "LINK/USDT:USDT",
    }
