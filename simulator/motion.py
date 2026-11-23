"""One bounded motion path shared by manual, rule and ML controllers.

The default values are configurable simulator assumptions, not measured
SerBot motor parameters; the opt-in ``serbot_measured`` preset uses limits
from the SerBot driver (docs/SHIMCHEONG.md). Collision prevention is a
geometric emergency stop, not a prediction of real braking or impact dynamics.
"""
from __future__ import annotations

import math

from .contracts import MotionAction, finite

DEFAULT_PHYSICS = dict(max_linear=.5, max_angular=3., max_acceleration=1.,
                       max_deceleration=1.5, max_angular_acceleration=6., body_margin=.02,
                       guard_distance=.2, enabled=True)

# Opt-in limits taken from the SerBot driver used with the simcheongi model
# (docs/SHIMCHEONG.md lists the source of every value). Selecting it never
# changes DEFAULT_PHYSICS; results with it are a different environment.
SERBOT_MEASURED_PHYSICS = dict(
    max_linear=.5,                              # contract maximum; robot request ceiling is higher (0.60 outdoors)
    max_angular=math.radians(40.),              # typical driver turn cap in drive logs ("w_cap_dps": 40)
    max_acceleration=.3,                        # driver follower accel 0.30 m/s^2
    max_deceleration=.3,                        # driver THIN_DEC 0.30 m/s^2 (measured stop p10 0.29)
    max_angular_acceleration=math.radians(120.),  # driver THIN_W_RATE 120 deg/s^2
    body_margin=.06,                            # driver G_OUTLINE: body outline + 0.06 m
    guard_distance=.125,                        # driver G_FRONT_MARGIN: bumper + 0.125 m
    enabled=True)
PHYSICS_PRESETS = dict(default=DEFAULT_PHYSICS, serbot_measured=SERBOT_MEASURED_PHYSICS)


def validate_physics(settings=None):
    """Return a complete physics dict.

    ``settings`` is None (defaults), a preset name, or an object of overrides
    that may name its base with ``preset``. Only a named preset adds the
    ``preset`` key, so the default result is unchanged.
    """
    if isinstance(settings, str):
        settings = dict(preset=settings)
    if settings is not None and not isinstance(settings, dict):
        raise ValueError('physics must be an object')
    preset = (settings or {}).get('preset')
    if preset is not None and (not isinstance(preset, str) or preset not in PHYSICS_PRESETS):
        raise ValueError('physics preset: '+', '.join(PHYSICS_PRESETS))
    result = dict(PHYSICS_PRESETS[preset] if preset is not None else DEFAULT_PHYSICS)
    limits = dict(max_linear=(.01, .5), max_angular=(.01, 3.), max_acceleration=(.01, 100.),
                  max_deceleration=(.01, 100.), max_angular_acceleration=(.01, 100.),
                  body_margin=(0., .2), guard_distance=(0., 2.))
    for key, value in (settings or {}).items():
        if key == 'preset':
            continue
        if key not in result:
            raise ValueError('unknown physics setting: '+key)
        if key == 'enabled':
            if not isinstance(value, bool):
                raise ValueError('enabled must be a bool')
        else:
            value = finite(value, key)
            lo, hi = limits[key]
            if not lo <= value <= hi:
                raise ValueError(f'{key}: {lo}..{hi}')
        result[key] = value
    if preset is not None:
        result['preset'] = preset
    return result


def _approach(current, target, amount):
    return current+max(-amount, min(amount, target-current))


def integrate(world, action, dt, physics=None):
    """Apply a desired velocity; return None, 'collision' or 'guard'.

    A zero action brakes normally. An explicit emergency stop can still set
    actual velocities to zero outside this function. The caller owns command
    durations, game transitions, policy selection and time advancement.
    """
    action = MotionAction.from_value(action)
    dt = finite(dt, 'dt')
    if not 0 < dt <= 30:
        raise ValueError('dt must be positive and at most 30 seconds')
    config = validate_physics(physics)
    target_v = max(-config['max_linear'], min(config['max_linear'], action.linear_mps))
    target_w = max(-config['max_angular'], min(config['max_angular'], action.angular_rps))
    robot = world.robot
    steps = max(1, math.ceil(dt/.01))
    interval = dt/steps
    status = None
    for _ in range(steps):
        old_v, old_w = robot['linear'], robot['angular']
        if not config['enabled']:
            new_v, new_w = target_v, target_w
            applied_v, applied_w = new_v, new_w
        else:
            accelerating = old_v*target_v >= 0. and abs(target_v) > abs(old_v)
            bound = config['max_acceleration'] if accelerating else config['max_deceleration']
            new_v = _approach(old_v, target_v, bound*interval)
            new_w = _approach(old_w, target_w, config['max_angular_acceleration']*interval)
            applied_v, applied_w = (old_v+new_v)/2, (old_w+new_w)/2
        h = robot['heading']+applied_w*interval/2
        x = robot['x']-math.sin(h)*applied_v*interval
        z = robot['z']+math.cos(h)*applied_v*interval
        if abs(applied_v) > 1e-12 and world.clearance(x, z) < world.radius+config['body_margin']:
            status = 'collision'
        elif action.guard and abs(applied_v) > 1e-12 and world.ray(robot['heading']+(math.pi if applied_v < 0 else 0)) < config['guard_distance']:
            status = 'guard'
        if status:
            robot.update(linear=0., angular=0.)
            break
        robot.update(x=x, z=z, heading=(robot['heading']+applied_w*interval+math.pi) % (2*math.pi)-math.pi,
                     linear=new_v, angular=new_w)
        world.distance += abs(applied_v)*interval
    world.contact('robot', 'blocked', status == 'collision')
    return status
