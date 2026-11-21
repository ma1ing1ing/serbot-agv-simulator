"""Explicit, isolated controller comparisons on common scenario/seed pairs."""
from __future__ import annotations

import argparse
from collections import defaultdict
import copy
import importlib
import json
from pathlib import Path
import statistics

from . import games
from . import scenarios as scenario_library


def load_controller(reference):
    """Load a user-requested module:factory without changing simulator code."""
    module_name, separator, attribute = reference.partition(':')
    if not separator or not module_name or not attribute or '.' in attribute:
        raise ValueError('controller는 module:factory 형식이어야 합니다')
    factory = getattr(importlib.import_module(module_name), attribute)
    if not callable(factory):
        raise ValueError('controller factory는 호출 가능해야 합니다')
    return factory


def outcome(world):
    """Report game-specific task measures; no across-game ranking is defined."""
    game = world.game
    count = len(world.children)
    caught = len(game.get('caught_ids', ()))
    frozen = len(game.get('frozen_ids', ()))
    eliminated = len(game.get('eliminated_ids', ()))
    escaped = len(game.get('escaped_ids', ()))
    if game['mode'] == 'tag':
        score = caught/count
        success = game.get('end_reason') == 'all_caught'
        definition = 'caught_fraction'
    elif game['mode'] == 'freeze_tag':
        score = frozen/count
        success = game.get('end_reason') == 'all_frozen'
        definition = 'currently_frozen_fraction'
    else:
        score = (caught+eliminated)/count
        success = caught+eliminated == count and escaped == 0
        definition = 'caught_or_eliminated_fraction'
    episode = getattr(world, 'episode', None)
    events = dict(episode.counts) if episode is not None else {}
    return dict(task_score=score, score_definition=definition, task_success=success,
                participants=count, caught=caught, frozen=frozen, eliminated=eliminated,
                escaped=escaped, touched=game.get('touched_by') is not None,
                freeze_events=events.get('freeze', 0), rescue_events=events.get('thaw', 0))


def _aggregates(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row['game'], row['controller'])].append(row)
    result = []
    for (game, controller), cases in sorted(groups.items()):
        item = dict(game=game, controller=controller, episodes=len(cases),
                    success_rate=statistics.mean(int(case['outcome']['task_success']) for case in cases),
                    mean_task_score=statistics.mean(case['outcome']['task_score'] for case in cases),
                    mean_game_time=statistics.mean(case['game_time'] for case in cases))
        metrics = {}
        keys = set().union(*(case['metrics'] for case in cases))
        for key in sorted(keys):
            values = [case['metrics'][key] for case in cases if isinstance(case['metrics'].get(key), (int, float))
                      and not isinstance(case['metrics'][key], bool)]
            if values:
                metrics['mean_'+key] = statistics.mean(values)
        item['metrics'] = metrics
        result.append(item)
    return result


def run(game='tag', *, scenarios=None, group=None, seeds=(0, 1, 2), controllers=None,
        settings=None, count=5, observation_mode='oracle', output=None, physics=None, dt=.1):
    """Compare fresh policies in independent environments, without recording.

    ``controllers`` maps labels to zero-argument factories. No simulation runs on
    import. Files are created only when ``output`` is explicitly supplied.
    """
    from .controllers import IdleController, RuleController
    from .environment import PlayEnv
    from .recording import CODE_SHA256
    from .motion import validate_physics
    from .contracts import SCHEMA_VERSION

    if game not in games.MODES:
        raise ValueError('지원하는 게임: '+', '.join(games.MODES))
    scenario_names = tuple(scenarios) if scenarios is not None else scenario_library.names(group) if group is not None else ('open',)
    if not scenario_names or len(set(scenario_names)) != len(scenario_names):
        raise ValueError('중복 없는 scenario 목록이 필요합니다')
    seeds = tuple(seeds)
    if not seeds or len(set(seeds)) != len(seeds) or any(isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32 for seed in seeds):
        raise ValueError('중복 없는 0 ~ 4294967295 정수 시드가 필요합니다')
    settings = dict({'time_limit':30.} if settings is None else settings)
    games.options(game, seeds[0], settings)
    for name in scenario_names:
        # Validate the whole requested suite before running its first episode.
        for seed in seeds:
            scenario_library.prepare_scenario(name, count, seed, game=game)
    factories = dict(controllers) if controllers is not None else {'rule':RuleController, 'idle':IdleController}
    if not factories or any(not isinstance(label, str) or not label or not callable(factory) for label, factory in factories.items()):
        raise ValueError('controllers는 이름:factory 형식이어야 합니다')
    target = Path(output) if output is not None else None
    if target is not None and target.exists():
        raise ValueError('평가 출력 파일이 이미 존재합니다')
    physical = validate_physics(physics)
    report = dict(schema_version=2, game=game,code_sha256=CODE_SHA256, policy_version=games.VERSION,
                  observation_schema_version=SCHEMA_VERSION,physics=physical,control_dt=dt,controller_types={}, scenario_version=scenario_library.VERSION,
                  scenarios=list(scenario_names), scenario_group=(group or 'open_room') if scenarios is None else 'explicit',
                  seeds=list(seeds), count=count, settings=copy.deepcopy(settings),
                  observation_mode=observation_mode, recording=False,
                  comparison='same game, scenario and seed; task scores are not comparable across games',
                  rows=[], aggregate=[])
    for label, factory in factories.items():
        for scenario_name in scenario_names:
            for seed in seeds:
                policy = factory()
                if not callable(getattr(policy, 'predict', None)) or not callable(getattr(policy, 'reset', None)):
                    raise ValueError('controller에는 reset과 predict가 필요합니다')
                env = PlayEnv(game=game, controller=policy, observation_mode=observation_mode,physics=physical,dt=dt)
                report['controller_types'][label] = dict(factory=policy.__class__.__module__+':'+policy.__class__.__qualname__,
                                                         model_version=str(getattr(policy,'model_version','unspecified')))
                try:
                    observation, info = env.reset(seed=seed, scenario=scenario_name, settings=settings,
                                                  count=count, record=False)
                    done = False
                    total_reward = 0.
                    while not done:
                        observation, reward, terminated, truncated, info = env.step()
                        total_reward += reward
                        done = terminated or truncated
                    world = env.world
                    report['rows'].append(dict(game=game, controller=label, scenario=scenario_name,
                                                scenario_split=scenario_library.prepare_scenario(scenario_name, count, seed, game=game)['split'],
                                                seed=seed, end_reason=world.game.get('end_reason'),
                                                game_time=world.game.get('elapsed', world.time),
                                                reward_total=total_reward, outcome=outcome(world),
                                                metrics=copy.deepcopy(info.get('metrics', {}))))
                finally:
                    env.close()
    report['aggregate'] = _aggregates(report['rows'])
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents accidental overwrite, including a race.
        with target.open('x', encoding='utf-8') as handle:
            json.dump(report, handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.write('\n')
    return report


def main():
    parser = argparse.ArgumentParser(description='동일 조건에서 놀이별 로봇 제어기 비교')
    parser.add_argument('--game', choices=games.MODES, default='tag')
    parser.add_argument('--group', choices=tuple(scenario_library.GROUPS), default=None, help=argparse.SUPPRESS)
    parser.add_argument('--scenario', nargs='+', choices=scenario_library.names(), help=argparse.SUPPRESS)
    parser.add_argument('--seeds', nargs='+', type=int, default=[0, 1, 2])
    parser.add_argument('--controllers', nargs='+', choices=('rule', 'idle'), default=['rule', 'idle'])
    parser.add_argument('--controller', help='추가로 비교할 사용자 module:factory')
    parser.add_argument('--count', type=int, default=5)
    parser.add_argument('--time-limit', type=float, default=30.)
    parser.add_argument('--observation-mode', choices=('oracle', 'sensor'), default='oracle')
    parser.add_argument('--dt',type=float,default=.1,help='control interval, multiple of .02 seconds')
    parser.add_argument('--output', type=Path, help='지정할 때만 평가 JSON 저장')
    args = parser.parse_args()
    try:
        from .controllers import IdleController, RuleController
        builtins = dict(rule=RuleController, idle=IdleController)
        factories = {name:builtins[name] for name in args.controllers}
        if args.controller:
            factories[args.controller] = load_controller(args.controller)
        report = run(args.game, scenarios=args.scenario, group=args.group, seeds=args.seeds,
                     controllers=factories, count=args.count, settings={'time_limit':args.time_limit},
                     observation_mode=args.observation_mode, output=args.output,dt=args.dt)
    except (ValueError, TypeError, OSError, ImportError, AttributeError) as exc:
        parser.exit(1, str(exc)+'\n')
    except KeyboardInterrupt:
        parser.exit(130, '평가를 중단했습니다.\n')
    for item in report['aggregate']:
        print(f"{item['controller']}: {item['episodes']}판 · 성공률 {item['success_rate']:.1%} · 게임 점수 {item['mean_task_score']:.3f}")
    if args.output:
        print('평가 저장: '+str(args.output.resolve()))


if __name__ == '__main__':
    main()
