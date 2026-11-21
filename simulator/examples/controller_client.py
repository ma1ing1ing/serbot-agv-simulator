"""Run a replaceable controller locally, without a server or output files.

python3 -m simulator.examples.controller_client --game tag --controller rule
python3 -m simulator.examples.controller_client --controller my_policy:create_controller
"""
from __future__ import annotations

import argparse
import importlib
import json

from simulator.controllers import IdleController, RuleController
from simulator.environment import PlayEnv


def create_controller():
    """Example factory: replace this object with your own model adapter."""
    return RuleController()


def load_controller(name):
    if name == 'rule':
        return RuleController()
    if name == 'idle':
        return IdleController()
    module_name, separator, factory_name = name.partition(':')
    if not separator or not module_name or not factory_name:
        raise ValueError('controller: rule, idle 또는 module:factory 형식이 필요합니다')
    factory = getattr(importlib.import_module(module_name), factory_name)
    if not callable(factory):
        raise ValueError('controller factory는 호출 가능해야 합니다')
    controller = factory()
    if not callable(getattr(controller, 'reset', None)) or not callable(getattr(controller, 'predict', None)):
        raise ValueError('제어기는 reset(seed=...)와 predict(observation)를 제공해야 합니다')
    return controller


def main():
    parser = argparse.ArgumentParser(description='서버 없이 로봇 제어기를 한 판 연결하는 예제')
    parser.add_argument('--game', choices=('tag', 'freeze_tag', 'red_light'), default='tag')
    parser.add_argument('--controller', default='rule', help='rule, idle 또는 module:factory')
    parser.add_argument('--scenario', default='open', help=argparse.SUPPRESS)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--count', type=int, default=5)
    parser.add_argument('--time-limit', type=float, default=10)
    parser.add_argument('--observation-mode', choices=('oracle', 'sensor'), default='oracle')
    args = parser.parse_args()
    try:
        controller = load_controller(args.controller)
        env = PlayEnv(game=args.game,controller=controller,observation_mode=args.observation_mode)
        try:
            observation, info = env.reset(seed=args.seed, scenario=args.scenario, count=args.count,
                                          settings={'time_limit': args.time_limit})
            total_reward = 0.
            terminated = truncated = False
            while not (terminated or truncated):
                observation, reward, terminated, truncated, info = env.step()
                total_reward += reward
            print(json.dumps(dict(game=args.game, controller=args.controller, seed=args.seed,
                                  scenario=args.scenario, total_reward=total_reward,
                                  terminated=terminated, truncated=truncated,
                                  end_reason=info.get('end_reason'), metrics=info.get('metrics', {})),
                             ensure_ascii=False, allow_nan=False, indent=2))
        finally:
            env.close()
    except (ValueError, ImportError, AttributeError) as exc:
        parser.exit(1, str(exc)+'\n')


if __name__ == '__main__':
    main()
