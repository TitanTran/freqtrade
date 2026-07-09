"""Crowd-positioning data source for the F5 positioning veto.

Fetches hourly OPEN INTEREST history from the exchange's PUBLIC futures API
(no auth). Open interest is one of the two retail-accessible windows into
market-maker/crowd positioning (the other is the funding rate, which
freqtrade already provides natively as a candle type).

Design rules:
- Composition: the strategy owns the veto logic; this module only supplies
  a clean [date, open_interest] time series.
- Fail-open: ANY failure (network, geo-block, missing ccxt method, empty
  payload) returns an empty frame so the veto resolves to NEUTRAL instead
  of crashing or blocking the bot.
- Live/dry-run only by nature: the exchange keeps ~30 days of OI history,
  so this data cannot backtest years — which matches the forward-validation
  policy for every new filter.
"""

import logging
import time

import pandas as pd

logger = logging.getLogger(__name__)

# Binance /futures/data/openInterestHist: period 1h, max 500 rows (~20 days).
OI_TIMEFRAME = "1h"
OI_HISTORY_LIMIT = 500
# One refresh per 1h candle; slightly under the candle length so a late
# candle-processing tick still triggers a fresh fetch.
CACHE_TTL_SECONDS = 55 * 60


class OpenInterestProvider:
    """Cached, fail-open access to hourly open-interest history."""

    def __init__(self) -> None:
        self._client = None
        self._cache: dict[str, tuple[float, pd.DataFrame]] = {}

    def _get_client(self):
        if self._client is None:
            import ccxt  # deferred: only needed when OI is actually fetched

            self._client = ccxt.binanceusdm({"enableRateLimit": True})
        return self._client

    def history(self, pair: str) -> pd.DataFrame:
        """Hourly OI history as columns [date (UTC), open_interest].

        open_interest is the BASE-asset amount (pure positioning, not
        confounded by price like the USDT value is); falls back to the
        quote value when the exchange omits the amount. Returns an EMPTY
        frame on any failure (fail-open -> veto neutral).
        """
        now = time.time()
        cached = self._cache.get(pair)
        if cached is not None and now - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]

        frame = pd.DataFrame(columns=["date", "open_interest"])
        try:
            raw = self._get_client().fetch_open_interest_history(
                pair, timeframe=OI_TIMEFRAME, limit=OI_HISTORY_LIMIT
            )
            rows = [
                {
                    "date": entry["timestamp"],
                    "open_interest": entry.get("openInterestAmount")
                    if entry.get("openInterestAmount") is not None
                    else entry.get("openInterestValue"),
                }
                for entry in raw
                if entry.get("timestamp") is not None
            ]
            if rows:
                frame = pd.DataFrame(rows)
                frame["date"] = pd.to_datetime(frame["date"], unit="ms", utc=True)
                frame["open_interest"] = pd.to_numeric(
                    frame["open_interest"], errors="coerce"
                )
                frame = frame.dropna().sort_values("date").reset_index(drop=True)
        except Exception as exc:  # noqa: BLE001 - positioning data must never crash the bot
            logger.warning(f"[F5 OI] {pair} open-interest fetch failed (veto neutral): {exc}")
        self._cache[pair] = (now, frame)
        return frame


# Module-level singleton (same pattern as approval_queue): one client and
# one cache shared across all pairs of the single strategy instance.
_PROVIDER = OpenInterestProvider()


def oi_history(pair: str) -> pd.DataFrame:
    """Public entry point: cached hourly OI history for `pair`."""
    return _PROVIDER.history(pair)