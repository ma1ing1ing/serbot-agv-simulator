"""Validated, seedable layouts with separate development/evaluation families.

Presets are synthetic test cases, not calibrated child behaviour datasets.
"""
from __future__ import annotations

import copy
import json
import math
import random

VERSION = 'scenarios-1'
BOUNDS = (-5.5, 5.5, -4.5, 4.5)
BEHAVIORS = ('cautious', 'playful', 'helper')
GROUPS = dict(train=('standard', 'open'),
              validation=('staggered', 'obstacle_course'),
              test=('cross_room', 'dense'))
DESCRIPTIONS = dict(standard='기본 교실·지그재그 배치', open='장애물 없는 넓은 배치',
                    staggered='두 줄로 엇갈린 배치·측면 장애물',
                    obstacle_course='접근 경로 중앙의 장애물',
                    cross_room='교실 여러 방향에 분산된 배치',
                    dense='가까이 모인 참가자·측면 장애물')


def names(group=None):
    if group is None:
        return tuple(name for values in GROUPS.values() for name in values)
    if group not in GROUPS:
        raise ValueError('scenario group: train, validation, test')
    return GROUPS[group]


def _finite(value, field):
    if isinstance(value, bool):
        raise ValueError(field+'는 유한한 수여야 합니다')
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(field+'는 유한한 수여야 합니다') from exc
    if not math.isfinite(value):
        raise ValueError(field+'는 유한한 수여야 합니다')
    return value


def _validate(spec):
    if not isinstance(spec, dict):
        raise ValueError('scenario는 이름 또는 객체여야 합니다')
    spec = copy.deepcopy(spec)
    if not isinstance(spec.get('name'), str) or not spec['name']:
        raise ValueError('scenario name이 필요합니다')
    if spec.get('game') not in ('tag', 'freeze_tag', 'red_light'):
        raise ValueError('지원하지 않는 scenario game')
    count = spec.get('count')
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 8:
        raise ValueError('scenario count: 1 ~ 8 정수')
    seed = spec.get('seed')
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32:
        raise ValueError('scenario seed: 0 ~ 4294967295 정수')
    if tuple(spec.get('bounds', BOUNDS)) != BOUNDS:
        raise ValueError('이 버전에서는 기본 놀이실 경계를 사용합니다')
    spec['bounds'] = list(BOUNDS)
    children = spec.get('children')
    if not isinstance(children, list) or len(children) != count:
        raise ValueError('scenario children과 count가 일치해야 합니다')
    behaviors = spec.get('behavior_types')
    if not isinstance(behaviors, list) or len(behaviors) != count or any(v not in BEHAVIORS for v in behaviors):
        raise ValueError('behavior_types: cautious, playful, helper를 인원만큼 지정하세요')
    robot = spec.get('robot')
    if not isinstance(robot, dict):
        raise ValueError('scenario robot이 필요합니다')
    for key in ('x', 'z', 'heading'):
        robot[key] = _finite(robot.get(key), 'robot.'+key)
    obstacles = spec.get('obstacles')
    if not isinstance(obstacles, list):
        raise ValueError('scenario obstacles는 목록이어야 합니다')
    xmin, xmax, zmin, zmax = BOUNDS
    for obstacle in obstacles:
        if not isinstance(obstacle, dict):
            raise ValueError('장애물은 객체여야 합니다')
        for key in ('x', 'z', 'w', 'd'):
            obstacle[key] = _finite(obstacle.get(key), 'obstacle.'+key)
        if obstacle['w'] <= 0 or obstacle['d'] <= 0:
            raise ValueError('장애물 크기는 양수여야 합니다')
        if not (xmin <= obstacle['x']-obstacle['w']/2 < obstacle['x']+obstacle['w']/2 <= xmax
                and zmin <= obstacle['z']-obstacle['d']/2 < obstacle['z']+obstacle['d']/2 <= zmax):
            raise ValueError('장애물이 놀이실 경계를 벗어납니다')
    for ident, child in enumerate(children):
        if not isinstance(child, dict) or child.get('id') != ident:
            raise ValueError('scenario child id는 0부터 연속이어야 합니다')
        for key in ('x', 'z', 'heading'):
            child[key] = _finite(child.get(key), 'child.'+key)
        if spec['game'] == 'red_light' and abs(child['z']-3.2) > 1e-9:
            raise ValueError('무궁화꽃이 피었습니다 시작선은 z=3.2입니다')
    actors = [(robot, .42)]+[(child, .25) for child in children]
    for actor, radius in actors:
        x, z = actor['x'], actor['z']
        if min(x-xmin, xmax-x, z-zmin, zmax-z) <= radius:
            raise ValueError('참가자가 경계에 너무 가깝습니다')
        for obstacle in obstacles:
            dx = max(abs(x-obstacle['x'])-obstacle['w']/2, 0.)
            dz = max(abs(z-obstacle['z'])-obstacle['d']/2, 0.)
            if math.hypot(dx, dz) <= radius:
                raise ValueError('참가자와 장애물이 겹칩니다')
    for index, child in enumerate(children):
        if math.hypot(child['x']-robot['x'], child['z']-robot['z']) <= .8:
            raise ValueError('참가자가 술래의 초기 잡힘 범위에 있습니다')
        for other in children[index+1:]:
            if math.hypot(child['x']-other['x'], child['z']-other['z']) <= .5:
                raise ValueError('아이들의 초기 위치가 겹칩니다')
    spec.setdefault('schema_version', 1)
    spec.setdefault('version', VERSION)
    spec.setdefault('split', 'custom')
    try:
        json.dumps(spec, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError('scenario는 유한한 JSON 값으로 구성해야 합니다') from exc
    return spec


def prepare_scenario(name='standard', count=5, seed=0, *, game='tag'):
    """Return a detached, fully validated layout before modifying a World.

    A previously prepared/custom dictionary is accepted without rerandomizing it;
    its count, seed and game must match the requested episode.
    """
    if isinstance(name, dict):
        spec = _validate(name)
        if (spec['count'], spec['seed'], spec['game']) != (count, seed, game):
            raise ValueError('scenario의 count·seed·game이 게임 설정과 다릅니다')
        return spec
    if name not in names():
        raise ValueError('scenario: '+', '.join(names()))
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 8:
        raise ValueError('count: 1 ~ 8 정수')
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32:
        raise ValueError('seed: 0 ~ 4294967295 정수')
    if game not in ('tag', 'freeze_tag', 'red_light'):
        raise ValueError('지원하지 않는 game')
    rng = random.Random(seed)
    obstacles = [dict(x=-4.5, z=.5, w=.7, d=1.6), dict(x=4.5, z=.5, w=.7, d=1.6)]
    robot = dict(x=0., z=-3.35, heading=0.)
    if name == 'open':
        obstacles = []
    elif name == 'staggered':
        obstacles = [dict(x=-3.6, z=.5, w=.6, d=1.8), dict(x=3.6, z=.5, w=.6, d=1.8)]
    elif name == 'obstacle_course':
        obstacles.append(dict(x=0., z=-.75, w=1.0, d=.8))
    elif name == 'dense':
        obstacles = [dict(x=-2.7, z=.6, w=.6, d=1.7), dict(x=2.7, z=.6, w=.6, d=1.7)]
    elif name == 'cross_room':
        robot['heading'] = math.pi/4
    children = []
    for ident in range(count):
        if game == 'red_light':
            spacing = .75 if name == 'dense' else .9
            x, z = (ident-(count-1)/2)*spacing, 3.2
        elif name == 'cross_room':
            theta = 2*math.pi*ident/count+.1
            x, z = math.cos(theta)*2.45, .4+math.sin(theta)*2.45
        elif name in ('dense', 'staggered'):
            columns = min(count, 4)
            spacing = .65 if name == 'dense' else 1.05
            x = (ident % columns-(columns-1)/2)*spacing
            z = .4+(ident//columns)*(.65 if name == 'dense' else 1.3)
        else:
            x = (ident-(count-1)/2)*(.95 if name == 'open' else .85)
            z = (1.0 if name == 'obstacle_course' else .3)+(ident % 2)*(1.0 if name == 'obstacle_course' else 1.15)
        x += rng.uniform(-.05, .05)
        if game != 'red_light':
            z += rng.uniform(-.05, .05)
        children.append(dict(id=ident, x=x, z=z, heading=math.pi if game == 'red_light' else rng.uniform(-math.pi, math.pi)))
    behavior_types = [BEHAVIORS[(ident+seed) % len(BEHAVIORS)] for ident in range(count)]
    if name == 'dense':
        behavior_types = ['helper' if i % 2 else 'cautious' for i in range(count)]
    elif name == 'cross_room':
        behavior_types = ['playful' if i % 2 else 'cautious' for i in range(count)]
    spec = dict(schema_version=1, version=VERSION, name=name,
                split=next(key for key, values in GROUPS.items() if name in values),
                description=DESCRIPTIONS[name], seed=seed, count=count, game=game,
                bounds=list(BOUNDS), robot=robot, obstacles=obstacles,
                children=children, behavior_types=behavior_types)
    return _validate(spec)


def apply_scenario(world, scenario='standard', seed=0):
    """Apply a layout atomically after game initialization, before recording."""
    spec = prepare_scenario(scenario, len(world.children), seed, game=world.game['mode'])
    # Validation above deliberately occurs before the first mutation.
    world.robot.update(spec['robot'], linear=0., angular=0., vx=0., vz=0.)
    world.obstacles = copy.deepcopy(spec['obstacles'])
    for child, initial, behavior in zip(world.children, spec['children'], spec['behavior_types']):
        child.update(initial, home_x=initial['x'], vx=0., vz=0., behavior_type=behavior)
        child.setdefault('profile', {})['behavior_type'] = behavior
        child['watched'] = world.robot_watching(child)
    world.trail = [[world.robot['x'], world.robot['z']]]
    world.scenario = copy.deepcopy(spec)
    return copy.deepcopy(spec)
