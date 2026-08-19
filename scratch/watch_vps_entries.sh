#!/bin/bash
# Poll the VPS every 15 min for a new trade row and surface the current
# LongGate/ShortGate diagnostic per pair. Exits early on a new trade, or
# after MAX_ITERS with a summary. Each echo is a stdout line for Monitor.
set -u
BASELINE_MAX_ID=2
INTERVAL_SEC=900
MAX_ITERS=16   # ~4 hours

for i in $(seq 1 "$MAX_ITERS"); do
  ts=$(date -u +"%Y-%m-%d %H:%M:%S UTC")
  latest=$(ssh -o ConnectTimeout=10 root@139.180.209.239 \
    'cd /root/ft_userdata && docker compose exec -T freqtrade sqlite3 /freqtrade/user_data/live_20260706.sqlite "SELECT id, pair, is_short, open_date FROM trades ORDER BY id DESC LIMIT 1;"' 2>/dev/null)
  max_id=$(echo "$latest" | cut -d'|' -f1)

  gates=$(ssh -o ConnectTimeout=10 root@139.180.209.239 \
    'cd /root/ft_userdata && docker compose logs --tail 400 freqtrade 2>/dev/null' \
    | grep -A1 "V7 SMC" | grep -E "V7 SMC|LongGate" | tail -6)

  if [ -n "$max_id" ] && [ "$max_id" -gt "$BASELINE_MAX_ID" ]; then
    echo "[$ts] NEW TRADE DETECTED: $latest"
    echo "--- recent gate state ---"
    echo "$gates"
    exit 0
  fi

  echo "[$ts] iter $i/$MAX_ITERS — no new trade yet (max id still $max_id)"
  echo "$gates"

  if [ "$i" -lt "$MAX_ITERS" ]; then
    sleep "$INTERVAL_SEC"
  fi
done

echo "[$(date -u +"%Y-%m-%d %H:%M:%S UTC")] done watching, no new trade in the window."
