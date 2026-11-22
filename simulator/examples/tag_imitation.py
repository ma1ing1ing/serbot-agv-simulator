"""Initialize a tag PPO actor from rule demonstrations in the oracle simulator."""
from collections import defaultdict

import numpy as np
import torch

from simulator.controllers import RuleController
from simulator.environment import PlayEnv, default_reward
from simulator.gym_env import GymPlayEnv


def imitate_rule(model, seeds, *, count, time_limit, shuffle_seed):
    inputs = defaultdict(list)
    actions = []
    catches = 0
    def record_demonstration(previous, action, observation, info):
        # These are the exact pre-step observation and requested command.
        for key, value in GymPlayEnv.encode_observation(previous).items():
            inputs[key].append(value)
        actions.append((action.linear_mps, action.angular_rps))
        return default_reward(previous, action, observation, info)

    with PlayEnv(controller=RuleController(), reward_fn=record_demonstration) as teacher:
        for seed in seeds:
            teacher.reset(seed=seed, count=count, settings={'time_limit': time_limit})
            while teacher.active:
                _, _, _, _, info = teacher.step()
                catches += info['event_delta'].get('catch', 0)

    observations = {key: torch.as_tensor(np.stack(values)) for key, values in inputs.items()}
    targets = torch.tensor(actions, dtype=torch.float32)
    action_scale = torch.as_tensor(model.action_space.high)
    generator = torch.Generator().manual_seed(shuffle_seed)
    optimizer = torch.optim.Adam(model.policy.parameters(), lr=.001)

    def imitation_loss(batch):
        features = {key: values[batch] for key, values in observations.items()}
        means = model.policy.get_distribution(features).mode()
        return ((means - targets[batch]) / action_scale).square().mean()

    with torch.no_grad():
        initial = imitation_loss(slice(None)).item()
    epochs, batch_size = 8, 64
    for _ in range(epochs):
        for batch in torch.randperm(len(actions), generator=generator).split(batch_size):
            optimizer.zero_grad()
            imitation_loss(batch).backward()
            optimizer.step()
    with torch.no_grad():
        final = imitation_loss(slice(None)).item()
    return dict(controller='rule', seeds=list(seeds), steps=len(actions), capture_events=catches,
                epochs=epochs, batch_size=batch_size, learning_rate=.001, shuffle_seed=shuffle_seed,
                initial_scaled_mse=initial, final_scaled_mse=final)
