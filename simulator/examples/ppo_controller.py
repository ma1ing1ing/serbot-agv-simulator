"""Load the optional PPO example as an ordinary observation-only controller."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from simulator import games
from simulator.contracts import MotionAction, SCHEMA_VERSION


class PPOController:
    def __init__(self, model_path, game):
        if game not in games.MODES:
            raise ValueError('unsupported PPO game: ' + str(game))
        path = Path(model_path)
        with (path.parent / 'config.json').open(encoding='utf-8') as handle:
            config = json.load(handle)
        if (not isinstance(config, dict) or config.get('game') != game
                or config.get('observation_mode') != 'oracle'
                or config.get('schema_version') != SCHEMA_VERSION
                or config.get('guard') is not False or config.get('dt') != .1):
            raise ValueError('PPO config must match the game, oracle schema, dt=0.1 and guard=False')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if config.get('model_sha256') != digest:
            raise ValueError('PPO model does not match config.json model_sha256')
        try:
            from stable_baselines3 import PPO
            from simulator.gym_env import GymPlayEnv
        except ImportError as exc:
            raise ImportError('PPO example requires: python3 -m pip install -e ".[training]" '
                              '"stable-baselines3>=2.4,<3"') from exc
        self.game = game
        self.name = 'ppo_' + game
        self.model_version = 'ppo-' + digest[:12]
        self.config = config
        self.model = PPO.load(str(path), device='cpu')
        self._encode = GymPlayEnv.encode_observation

    def reset(self, seed=None):
        # This feed-forward PPO policy has no per-episode recurrent state.
        pass

    def predict(self, observation):
        if (observation.get('schema_version') != SCHEMA_VERSION
                or observation.get('source') != 'oracle'
                or observation.get('game', {}).get('mode') != self.game):
            raise ValueError('PPO observation must match the trained game and oracle schema')
        if observation['game']['held'] or observation['game']['phase'] in ('ready', 'finished'):
            return MotionAction(guard=False)
        action, _ = self.model.predict(self._encode(observation), deterministic=True)
        return MotionAction(float(action[0]), float(action[1]), guard=False)


def create_tag_controller():
    return PPOController('artifacts/models/tag/model.zip', 'tag')


def create_freeze_tag_controller():
    return PPOController('artifacts/models/freeze_tag/model.zip', 'freeze_tag')


def create_red_light_controller():
    return PPOController('artifacts/models/red_light/model.zip', 'red_light')
