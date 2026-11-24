"""Explicit, isolated controller comparisons on common scenario/seed pairs."""
from __future__ import annotations

import argparse
from collections import defaultdict
import copy
import hashlib
import importlib
import json
from pathlib import Path
import statistics

from . import games
from . import scenarios as scenario_library


def referee_stages(world):
    """Score observed play. A final elimination ends the game at drop-off."""
    events = world.episode.counts
    reason = world.game['end_reason']
    detected = events['movement_detected']
    escorted = events['escort_complete']
    returned = events['escort_return']
    returns_due = max(0, escorted - int(reason == 'all_eliminated'))
    checks = events['referee_check']
    touched = events['touch'] > 0
    pursued = world.metrics['pursuit_closing_m'] >= .2
    chase_finished = touched and reason == 'pursuit_complete'
    complete = (checks > 0 and detected == escorted and returned == returns_due
                and (reason == 'all_eliminated' or (chase_finished and pursued)))
    return dict(advance_opportunities=events['advance_opportunity'], referee_checks=checks,
                detections=detected, escorts_completed=escorted, returns_due=returns_due,
                returns_completed=returned, touched=touched, pursuit_attempted=pursued,
                pursuit_finished=chase_finished, caught=events['catch'], referee_round_complete=complete)


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
        settings=None, count=5, observation_mode='oracle', output=None, physics=None, dt=.1,
        serbot_sensors=False):
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
    if serbot_sensors:
        # Opt-in input block; absent from default reports.
        from .serbot_sensors import SCHEMA as SERBOT_SCHEMA
        report['serbot_sensors'] = SERBOT_SCHEMA
    for label, factory in factories.items():
        for scenario_name in scenario_names:
            for seed in seeds:
                policy = factory()
                if not callable(getattr(policy, 'predict', None)) or not callable(getattr(policy, 'reset', None)):
                    raise ValueError('controller에는 reset과 predict가 필요합니다')
                env = PlayEnv(game=game, controller=policy, observation_mode=observation_mode,physics=physical,dt=dt,
                              serbot_sensors=serbot_sensors)
                report['controller_types'][label] = dict(factory=policy.__class__.__module__+':'+policy.__class__.__qualname__,
                                                         model_version=str(getattr(policy,'model_version','unspecified')))
                try:
                    observation, info = env.reset(seed=seed, scenario=scenario_name, settings=settings,
                                                  count=count, record=False)
                    initial = env.world.episode.config['initial_state']
                    case_hash = hashlib.sha256(json.dumps(initial, sort_keys=True).encode()).hexdigest()
                    done = False
                    total_reward = 0.
                    while not done:
                        observation, reward, terminated, truncated, info = env.step()
                        total_reward += reward
                        done = terminated or truncated
                    world = env.world
                    metrics = info['metrics']
                    flags = []
                    if game == 'red_light' and world.game['end_reason'] == 'time_limit':
                        flags.append('timeout')
                        if metrics['approach_seconds'] and metrics['watching_seconds'] >= .9*metrics['approach_seconds']:
                            flags.append('constant_watch')
                        if world.game['touched_by'] is None and metrics['rotation_radians'] > world.time:
                            flags.append('spinning_without_touch')
                    row = dict(game=game, controller=label, scenario=scenario_name,
                               scenario_split=world.scenario['split'], seed=seed,
                               end_reason=world.game.get('end_reason'), game_time=world.game.get('elapsed', world.time),
                               reward_total=total_reward, outcome=outcome(world), failure_flags=flags,
                               initial_state_sha256=case_hash, metrics=copy.deepcopy(metrics))
                    if game == 'red_light':
                        stages = referee_stages(world)
                        row['referee_stages'] = stages
                        if not stages['referee_checks']:
                            flags.append('no_referee_check')
                        if stages['escorts_completed'] < stages['detections']:
                            flags.append('unfinished_escort')
                        if stages['returns_completed'] < stages['returns_due']:
                            flags.append('unfinished_return')
                        if stages['touched'] and not stages['pursuit_attempted']:
                            flags.append('no_active_pursuit')
                    report['rows'].append(row)
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
    parser.add_argument('--physics', choices=('default', 'serbot_measured'), default=None,
                        help='주행 제한 프리셋. 생략하면 기본값 그대로')
    parser.add_argument('--serbot-sensors', action='store_true', help='관측에 SerBot 라이다·초음파 블록 추가')
    parser.add_argument('--catch-distance', type=float, default=None, help='잡힘 중심 거리(m). 생략하면 기본값')
    args = parser.parse_args()
    try:
        from .controllers import IdleController, RuleController
        builtins = dict(rule=RuleController, idle=IdleController)
        factories = {name:builtins[name] for name in args.controllers}
        if args.controller:
            factories[args.controller] = load_controller(args.controller)
        settings = {'time_limit':args.time_limit}
        if args.catch_distance is not None:
            settings['catch_distance'] = args.catch_distance
        report = run(args.game, scenarios=args.scenario, group=args.group, seeds=args.seeds,
                     controllers=factories, count=args.count, settings=settings,
                     observation_mode=args.observation_mode, output=args.output,dt=args.dt,
                     physics=args.physics, serbot_sensors=args.serbot_sensors)
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
