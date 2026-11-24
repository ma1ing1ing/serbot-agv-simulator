"""Versioned, JSON-compatible controller inputs and bounded motion commands.

Relative X points to the robot's right and relative Z points forward. Bearings
and angular commands are positive to the left. Positions are metres, time is
seconds and angles are radians. This schema deliberately excludes reward and
evaluation truth from the controller input.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from numbers import Real

from . import serbot_sensors

SCHEMA_VERSION = 1
MAX_CHILDREN = 8


def finite(value, name):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f'{name} must be a finite number')
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f'{name} must be a finite number')
    return result


@dataclass(frozen=True)
class MotionAction:
    linear_mps: float = 0.
    angular_rps: float = 0.
    guard: bool = True

    def __post_init__(self):
        linear = finite(self.linear_mps, 'linear_mps')
        angular = finite(self.angular_rps, 'angular_rps')
        if not -.5 <= linear <= .5 or not -3. <= angular <= 3.:
            raise ValueError('motion bounds: linear_mps -0.5..0.5, angular_rps -3..3')
        if not isinstance(self.guard, bool):
            raise ValueError('guard must be a bool')
        object.__setattr__(self, 'linear_mps', linear)
        object.__setattr__(self, 'angular_rps', angular)

    @classmethod
    def from_value(cls, value):
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            if set(value)-{'linear_mps', 'angular_rps', 'guard'}:
                raise ValueError('unknown action field')
            return cls(**value)
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return cls(value[0], value[1])
        raise ValueError('action must be MotionAction, a motion object or a pair of numbers')

    def to_dict(self):
        return asdict(self)


def _relative(x, z, heading):
    return math.cos(heading)*x+math.sin(heading)*z, -math.sin(heading)*x+math.cos(heading)*z


def _blank_child():
    return dict(id=-1, relative_x=0., relative_z=0., relative_vx=0., relative_vz=0.,
                distance=0., bearing=0., state='missing', visible=False)


def _detected_child(detection):
    if not isinstance(detection, dict):
        raise ValueError('each detection must be an object')
    ident = detection.get('id')
    if isinstance(ident, bool) or not isinstance(ident, int) or ident < 0:
        raise ValueError('detection id must be a non-negative integer')
    x = finite(detection.get('relative_x'), 'relative_x')
    z = finite(detection.get('relative_z'), 'relative_z')
    vx = finite(detection.get('relative_vx', 0.), 'relative_vx')
    vz = finite(detection.get('relative_vz', 0.), 'relative_vz')
    # Game state is unknown in sensor mode, even if a caller supplied oracle
    # fields in a detection object. A policy must infer it from observations.
    return dict(id=ident, relative_x=x, relative_z=z, relative_vx=vx, relative_vz=vz,
                distance=math.hypot(x, z), bearing=math.atan2(-x, z), state='unknown', visible=True)


def make_observation(world, mode='oracle', *, detections=None):
    """Return an isolated controller observation, never the full world snapshot.

    ``oracle`` is an explicit state-based control experiment. ``sensor`` uses
    simulated odometry/range rays and ONLY explicitly supplied robot-relative
    detections (or ``world.external_detections``); absent detections stay empty.
    A sensor observation is not a camera detector implementation.
    """
    if mode not in ('oracle', 'sensor'):
        raise ValueError('observation mode: oracle or sensor')
    robot = world.robot
    heading = robot['heading']
    robot_vx = robot.get('vx', -math.sin(heading)*robot['linear'])
    robot_vz = robot.get('vz', math.cos(heading)*robot['linear'])
    result = dict(schema_version=SCHEMA_VERSION, source=mode, time=world.time, tick=world.frame,
                  robot={key: float(robot[key]) for key in ('x', 'z', 'heading', 'linear', 'angular')},
                  game={key: world.game.get(key) for key in ('mode', 'phase', 'elapsed', 'held', 'target_id')},
                  rules={key: world.rules[key] for key in ('robot_speed', 'gaze_period', 'look_duration', 'catch_distance')},
                  children=[], child_mask=[], sensors={}, bounds=None, obstacles=[])
    result['robot'].update(vx=robot_vx, vz=robot_vz)
    if world.game['mode'] == 'red_light':
        result['game']['watching'] = bool(world.game.get('watching'))
    if world.game.get('escort') and mode == 'oracle':
        escort = world.game['escort']
        result['game']['escort'] = {
            **{key: escort[key] for key in ('child_id', 'stage', 'waiting')},
            'goal': dict(escort['goal']),
            'aligning': escort.get('aligning', False),
            'routed': bool(escort.get('route')),
        }
    if world.game.get('gaze_pause'):
        result['game']['gaze_elapsed'] = world.game['elapsed'] - world.game['gaze_pause']
    if world.game['mode'] == 'red_light' and world.rules.get('gaze_timing') in ('settled', 'friendly'):
        result['rules']['gaze_timing'] = world.rules['gaze_timing']
        result['control_dt'] = world.control_dt
    if world.game['mode'] == 'red_light' and world.rules.get('turn_profile', 'baseline') != 'baseline':
        result['rules'].update(turn_profile=world.rules['turn_profile'],
                               max_angular=world.physics['max_angular'],
                               max_angular_acceleration=world.physics['max_angular_acceleration'])
        result['control_dt'] = world.control_dt
    if mode == 'oracle':
        if len(world.children) > MAX_CHILDREN:
            raise ValueError('controller observations support up to eight game participants; replay is separate')
        for child in sorted(world.children, key=lambda c: c['id']):
            if child.get('visible', True) is False:
                result['children'].append(_blank_child())
                result['child_mask'].append(False)
                continue
            dx, dz = child['x']-robot['x'], child['z']-robot['z']
            x, z = _relative(dx, dz, heading)
            cvx = child.get('vx', math.sin(child['heading'])*child.get('speed', 0.))
            cvz = child.get('vz', math.cos(child['heading'])*child.get('speed', 0.))
            vx, vz = _relative(cvx-robot_vx, cvz-robot_vz, heading)
            result['children'].append(dict(id=child['id'], relative_x=x, relative_z=z,
                                          relative_vx=vx, relative_vz=vz, distance=math.hypot(x, z),
                                          bearing=math.atan2(-x, z), state=child.get('state', 'free'), visible=True))
            result['child_mask'].append(True)
        result['bounds'] = list(world.bounds)
        result['obstacles'] = [dict(x=b['x'], z=b['z'], w=b['w'], d=b['d']) for b in world.obstacles]
    else:
        supplied = getattr(world, 'external_detections', []) if detections is None else detections
        if supplied is None:
            supplied = []
        if not isinstance(supplied, (list, tuple)) or len(supplied) > MAX_CHILDREN:
            raise ValueError('detections must be a list of up to eight participants')
        children = sorted((_detected_child(d) for d in supplied), key=lambda c: c['id'])
        if len({c['id'] for c in children}) != len(children):
            raise ValueError('duplicate detection id')
        result['children'] = children
        result['child_mask'] = [True]*len(children)
        result['sensors'] = {name: world.ray(heading+offset, max_range=4.) for name, offset in
                             (('front_m', 0.), ('left_m', math.pi/2), ('right_m', -math.pi/2), ('rear_m', math.pi))}
        result['detection_time'] = getattr(world, 'external_detection_time', None)
        result['game']['target_id'] = None
    while len(result['children']) < MAX_CHILDREN:
        result['children'].append(_blank_child())
        result['child_mask'].append(False)
    if getattr(world, 'serbot_sensors', False):
        # Opt-in only: same tick, same geometry; absent by default.
        result['serbot'] = serbot_sensors.observe(world)
    return result
