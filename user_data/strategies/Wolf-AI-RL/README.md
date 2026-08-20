# Wolf-AI-RL

FreqAI Reinforcement Learning strategy. The PPO agent decides entries/exits directly
(`&-action` from `Base5ActionRLEnv`); the strategy only supplies features, the VWAP
entry gate, and the ATR-based stoploss — per the project's CLAUDE.md rules.

Files:
- `WolfAIRL.py` — the strategy (feature engineering, VWAP gate, ATR stoploss).
- `config.json` — `freqai.rl_config` for PPO + the custom reward model.
- `../../freqaimodels/WolfReinforcementLearner.py` — custom `calculate_reward()`.

## One-time environment setup

RL deps (`torch`, `gymnasium`, `stable-baselines3`, `sb3-contrib`) are NOT part of the
base install:

```bash
uv pip install -e ".[freqai,freqai_rl]"
```

### macOS-only: xgboost needs OpenMP

`freqtrade/freqai/tensorboard/` imports `xgboost` unconditionally (even though this
strategy never uses it), and on macOS the PyPI xgboost wheel needs `libomp.dylib`,
which isn't installed by default and this machine has no Homebrew. `scikit-learn`'s
wheel happens to bundle a working copy, so point the dynamic linker at it instead of
installing Homebrew:

```bash
export DYLD_LIBRARY_PATH="$(pwd)/.venv/lib/python3.14/site-packages/sklearn/.dylibs"
```

Set this in every shell before running `freqtrade` commands for this strategy (or add
it to your shell profile). If you'd rather fix it permanently: `brew install libomp`
removes the need for the workaround entirely.

## Download data

```bash
freqtrade download-data -c user_data/strategies/Wolf-AI-RL/config.json -t 15m 1h --timerange 20260701-20260820
```

## Backtest

```bash
freqtrade backtesting \
  -c user_data/strategies/Wolf-AI-RL/config.json \
  --strategy-path user_data/strategies/Wolf-AI-RL \
  --strategy WolfAIRL \
  --freqaimodel WolfReinforcementLearner \
  --timerange 20260701-20260820
```

Training logs print stable-baselines3's per-eval reward — watch it trend up across
`Eval num_timesteps=...` lines. This confirms the agent is learning, not just running.

## Dry-run

```bash
freqtrade trade \
  -c user_data/strategies/Wolf-AI-RL/config.json \
  --strategy-path user_data/strategies/Wolf-AI-RL \
  --strategy WolfAIRL \
  --freqaimodel WolfReinforcementLearner
```

Live/dry-run can set `rl_config.add_state_info: true` in config.json (current profit,
position, duration fed to the agent) — backtesting cannot, freqtrade raises
`OperationalException` if it's `true` there, so it is kept `false` in this config to
keep backtest and live behavior on the same trained model.

## Design notes (why the code looks the way it does)

- **Features are lean by design (CLAUDE.md #5):** only 4 dimensions — momentum
  (price deviation from EMA), volatility (ATR / price), volume (relative to its
  rolling mean), and structure (distance to VWAP) — each parametrized by
  `indicator_periods_candles`, no stacked oscillators.
- **VWAP gate (CLAUDE.md #3):** `populate_entry_trend` blocks `rl_long` when
  `close <= vwap` and `rl_short` when `close >= vwap`, regardless of what the agent
  wants. The agent never sees this as a feature-engineered signal; it's a hard
  strategy-level filter, so a mistrained agent still can't fight the VWAP rule.
- **No hardcoded stoploss (CLAUDE.md #4):** `stoploss = -0.99` is only the emergency
  safety net Freqtrade requires as a class attribute; the real stop is
  `custom_stoploss`, sized as `ATR_STOP_MULT * ATR(14)/price` at the entry candle,
  clamped to `[SL_MIN_PCT, SL_MAX_PCT]` — widens in storms, tightens in calm ranges.
- **Reward function** (`WolfReinforcementLearner.MyRLEnv.calculate_reward`) is
  intentionally simple: penalize invalid actions and idle sitting, penalize holding
  past `max_trade_duration_candles`, reward realized PnL on exit (scaled up past the
  configured `profit_aim * rr`). It does not re-encode the VWAP rule since that's
  already enforced structurally in `populate_entry_trend`.

## Tuning it further

The smoke-tested config uses `train_cycles: 25` and 3 pairs — enough to prove the
pipeline works end-to-end, not enough to be profitable. Before trusting results:
- Widen the data window (`train_period_days` / backtest range) well beyond a few weeks.
- Raise `train_cycles` and watch Tensorboard (`tensorboard --logdir user_data/models/wolf_ai_rl_v1`)
  for reward convergence, not just a single number.
- Iterate on `calculate_reward` — the shipped one is a reasonable starting point per
  the FreqAI RL docs, not a tuned strategy.
