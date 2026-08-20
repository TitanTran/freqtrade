import logging

from freqtrade.freqai.prediction_models.ReinforcementLearner import ReinforcementLearner
from freqtrade.freqai.RL.Base5ActionRLEnv import Actions, Base5ActionRLEnv, Positions


logger = logging.getLogger(__name__)

# Defaults used when a key is missing from `rl_config.model_reward_parameters`.
# Every value below is overridable from config.json - nothing here is a hidden
# magic number, it is only the fallback if the user does not set one.
DEFAULT_INVALID_ACTION_PENALTY = -2.0
DEFAULT_IDLE_PENALTY = -1.0
DEFAULT_WIN_REWARD_FACTOR = 2.0
DEFAULT_HOLD_PENALTY_FACTOR = 1.0


class WolfReinforcementLearner(ReinforcementLearner):
    """
    Wolf-AI-RL prediction model.

    Save to `user_data/freqaimodels`, then run with:
    freqtrade trade --freqaimodel WolfReinforcementLearner --strategy WolfAIRL --config config.json

    Reward shaping goals (kept intentionally simple - see docs/freqai-reinforcement-learning.md,
    the stock reward is a showcase, not production-ready):
      * Punish invalid actions and idle sitting-in-neutral so the agent explores.
      * Punish sitting in a position past `max_trade_duration_candles` (proportional to
        the overshoot, not a single cliff-edge penalty, so the gradient stays smooth).
      * Reward realized PnL on exit, scaled up when the trade cleared the configured
        `profit_aim * rr` target (win_reward_factor).
    The strategy's `populate_entry_trend` VWAP gate (CLAUDE.md rule #3) already blocks
    counter-VWAP entries before the agent's action reaches the exchange, so this reward
    function does not need to re-encode VWAP alignment.
    """

    class MyRLEnv(Base5ActionRLEnv):
        def calculate_reward(self, action: int) -> float:
            reward_params = self.rl_config.get("model_reward_parameters", {})

            if not self._is_valid(action):
                self.tensorboard_log("invalid", category="actions")
                return reward_params.get("invalid_action_penalty", DEFAULT_INVALID_ACTION_PENALTY)

            if action == Actions.Neutral.value and self._position == Positions.Neutral:
                return reward_params.get("idle_penalty", DEFAULT_IDLE_PENALTY)

            max_trade_duration = self.rl_config.get("max_trade_duration_candles", 300)
            trade_duration = self._current_tick - self._last_trade_tick if self._last_trade_tick else 0

            if (
                self._position in (Positions.Long, Positions.Short)
                and action == Actions.Neutral.value
            ):
                hold_penalty_factor = reward_params.get(
                    "hold_penalty_factor", DEFAULT_HOLD_PENALTY_FACTOR
                )
                return -hold_penalty_factor * trade_duration / max_trade_duration

            is_closing_long = action == Actions.Long_exit.value and self._position == Positions.Long
            is_closing_short = (
                action == Actions.Short_exit.value and self._position == Positions.Short
            )
            if is_closing_long or is_closing_short:
                pnl = self.get_unrealized_profit()
                factor = 1.0
                if pnl > self.profit_aim * self.rr:
                    factor = reward_params.get("win_reward_factor", DEFAULT_WIN_REWARD_FACTOR)
                return float(pnl * factor)

            return 0.0
