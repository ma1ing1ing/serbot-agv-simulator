"""Explicit PPO learning example; importing this module never starts training."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from simulator import games
from simulator.contracts import SCHEMA_VERSION
from simulator.environment import default_reward


def train(*, game='tag', steps=100000, seed=0, count=5, time_limit=30., output=None,
          reward_fn=default_reward, rule_demo_seeds=()):
    """Train one oracle policy and save its model and matching configuration.

    ``output`` is available to Python callers for isolated experiments. The
    command-line example uses artifacts/models/<game> and never overwrites it.
    Supply a named reward function to compare a personal reward with the default.
    For tag, rule_demo_seeds optionally provides separate imitation episodes.
    """
    if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
        raise ValueError('steps must be a positive integer')
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 8:
        raise ValueError('count must be an integer from 1 to 8')
    if not callable(reward_fn):
        raise ValueError('reward_fn must be callable')
    rule_demo_seeds = tuple(rule_demo_seeds)
    if rule_demo_seeds:
        if game != 'tag':
            raise ValueError('rule demonstrations are supported for tag only')
        if (any(type(s) is not int or not 0 <= s < 2**32 for s in rule_demo_seeds)
                or len(set(rule_demo_seeds)) != len(rule_demo_seeds)):
            raise ValueError('rule demonstration seeds must be distinct unsigned 32-bit integers')
    rules = games.options(game, seed, {'time_limit': time_limit})
    target = Path(output) if output is not None else Path('artifacts/models') / game
    if target.exists():
        raise ValueError(f'output already exists: {target}; use a new directory')
    try:
        import stable_baselines3
        from stable_baselines3 import PPO
        from simulator.examples.ppo_features import PlayFeaturesExtractor
        from simulator.gym_env import GymPlayEnv
    except ImportError as exc:
        raise ImportError('PPO example requires: python3 -m pip install -e ".[training]" '
                          '"stable-baselines3>=2.4,<3"') from exc
    from simulator.recording import CODE_SHA256

    class SeedTrackingEnv(GymPlayEnv):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.episode_seeds = set()
            self.blocked_attempts = 0
            self.episodes_started = 0
            self.episodes_finished = 0
            self.capture_events = 0
            self.episodes_with_capture = 0

        def reset(self, **kwargs):
            result = super().reset(**kwargs)
            self.episode_seeds.add(self.environment.world.game['seed'])
            self.first_step = True
            self.captured_this_episode = False
            return result

        def step(self, action):
            observation, reward, terminated, truncated, info = super().step(action)
            if self.first_step:
                self.episodes_started += 1
                self.first_step = False
            if terminated or truncated:
                self.episodes_finished += 1
            catches = info['event_delta'].get('catch', 0)
            self.capture_events += catches
            if catches and not self.captured_this_episode:
                self.episodes_with_capture += 1
                self.captured_this_episode = True
            self.blocked_attempts += info['metrics_delta']['blocked_attempts']
            return observation, reward, terminated, truncated, info

    env = SeedTrackingEnv(game=game, count=count, observation_mode='oracle',
                          dt=.1, settings={'time_limit': rules['time_limit']}, guard=False,
                          reward_fn=reward_fn)
    try:
        model = PPO('MultiInputPolicy', env, n_steps=256, batch_size=64, n_epochs=4,
                    policy_kwargs={'features_extractor_class': PlayFeaturesExtractor},
                    device='cpu', verbose=1, seed=seed)
        # Exclusive creation protects an earlier model, including concurrent runs.
        target.mkdir(parents=True, exist_ok=False)
        imitation = None
        if rule_demo_seeds:
            from simulator.examples.tag_imitation import imitate_rule
            imitation = imitate_rule(model, rule_demo_seeds, count=count,
                                     time_limit=rules['time_limit'], shuffle_seed=seed)
        model.learn(total_timesteps=steps)
        model_path = target / 'model.zip'
        model.save(str(model_path))
        config = dict(game=game, count=count, time_limit=rules['time_limit'], dt=.1,
                      observation_mode='oracle', guard=False,
                      reward=getattr(reward_fn, '__name__', type(reward_fn).__name__),
                      action_format=['linear_mps', 'angular_rps'],
                      rules=rules, physics=dict(env.environment.physics),
                      schema_version=SCHEMA_VERSION, code_sha256=CODE_SHA256, seed=seed,
                      requested_steps=steps, actual_steps=int(model.num_timesteps),
                      training_episode_seeds=sorted(env.episode_seeds),
                      training_blocked_attempts=env.blocked_attempts,
                      training_episodes_started=env.episodes_started,
                      training_episodes_finished=env.episodes_finished,
                      training_capture_events=env.capture_events,
                      training_episodes_with_capture=env.episodes_with_capture,
                      rule_pretraining=imitation,
                      model_sha256=hashlib.sha256(model_path.read_bytes()).hexdigest(),
                      stable_baselines3_version=stable_baselines3.__version__)
        with (target / 'config.json').open('x', encoding='utf-8') as handle:
            json.dump(config, handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.write('\n')
        return model_path
    finally:
        env.close()


def main():
    parser = argparse.ArgumentParser(description='로봇 PPO 학습·모델 저장 최소 예제')
    parser.add_argument('--game', choices=games.MODES, default='tag')
    parser.add_argument('--steps', type=int, default=100000)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--count', type=int, default=5)
    parser.add_argument('--time-limit', type=float, default=30.)
    parser.add_argument('--rule-demo-seeds', type=int, nargs='+', default=(),
                        help='술래잡기 규칙 제어기를 먼저 모방할 시드 목록')
    args = parser.parse_args()
    try:
        path = train(game=args.game, steps=args.steps, seed=args.seed,
                     count=args.count, time_limit=args.time_limit, rule_demo_seeds=args.rule_demo_seeds)
    except (ValueError, OSError, ImportError) as exc:
        parser.exit(1, str(exc) + '\n')
    except KeyboardInterrupt:
        parser.exit(130, '학습을 중단했습니다.\n')
    print('모델 저장: ' + str(path))


if __name__ == '__main__':
    main()
