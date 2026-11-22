"""Feature extraction for the simulator's numeric Gymnasium observation."""
from gymnasium.spaces.utils import flatdim
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor
import torch


class PlayFeaturesExtractor(BaseFeaturesExtractor):
    def __init__(self, observation_space):
        super().__init__(observation_space, flatdim(observation_space))
        # 'children' is a valid observation key but a reserved nn.Module method.
        self.keys_in_order = tuple(observation_space.spaces)

    def forward(self, observations):
        return torch.cat([observations[key].flatten(1) for key in self.keys_in_order], dim=1)
