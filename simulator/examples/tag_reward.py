"""Alternative blocked-move cost for the tag PPO experiment."""
from simulator.environment import default_reward


def double_blocked_penalty(previous_observation, action, observation, info):
    """Increase the default cost from 0.05 to 0.10 per new blocked attempt."""
    base = default_reward(previous_observation, action, observation, info)
    return base - .05 * info['metrics_delta']['blocked_attempts']
