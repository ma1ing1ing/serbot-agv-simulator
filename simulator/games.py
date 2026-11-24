"""Seeded synthetic play policies. No learned child behaviour is claimed."""
from __future__ import annotations

import math
import random

from .referee_route import plan_route

MODES = ('tag', 'freeze_tag', 'red_light')
VERSION = 'play-rules-5'
CHILD_POLICY_VERSION = 'red-light-paths-1'
BEHAVIOR_TYPES = ('cautious', 'playful', 'helper')
BEHAVIORS = dict(
    cautious=dict(threat_sensitivity=1.18, wander=.42, rescue_scale=.65),
    playful=dict(threat_sensitivity=.86, wander=.72, rescue_scale=.85),
    helper=dict(threat_sensitivity=1., wander=.55, rescue_scale=1.25),
)
DEFAULTS = dict(time_limit=120., chase_duration=20., catch_distance=.74,
                rescue_distance=.85, rescue_hold=.6, immunity=1.2,
                gaze_period=5., look_duration=1.8, detection_grace=.3,
                trajectory_difficulty='mixed', child_speed_scale=1.,
                gaze_timing='timed', turn_profile='baseline', stop_reaction='immediate',
                movement_threshold=.04, robot_speed=.48, randomize=True,
                child_behavior='mixed', child_perception_range=6.,
                child_fov_degrees=360., perception_memory=1.)
LIMITS = dict(child_speed_scale=(.6, 1.4), time_limit=(1, 3600), chase_duration=(1, 300), catch_distance=(.67, 1.5),
              rescue_distance=(.5, 2), rescue_hold=(.1, 5), immunity=(.2, 10),
              gaze_period=(2, 30), look_duration=(.2, 15), detection_grace=(0, 3),
              movement_threshold=(.001, 1), robot_speed=(.05, .5),
              child_perception_range=(.75, 20), child_fov_degrees=(30, 360),
              perception_memory=(0, 5))


def options(mode, seed, settings):
    if mode not in MODES:
        raise ValueError('mode: '+', '.join(MODES))
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32:
        raise ValueError('seed: 0 ~ 4294967295 정수가 필요합니다')
    if settings is not None and not isinstance(settings, dict):
        raise ValueError('settings는 JSON 객체여야 합니다')
    config = dict(DEFAULTS)
    for key, value in (settings or {}).items():
        if key not in config:
            raise ValueError('알 수 없는 설정: '+key)
        if key == 'child_behavior':
            if not isinstance(value, str) or value not in ('mixed', *BEHAVIOR_TYPES):
                raise ValueError('child_behavior: mixed, cautious, playful, helper')
        elif key == 'trajectory_difficulty':
            if value not in ('simple', 'mixed', 'challenge'):
                raise ValueError('trajectory_difficulty: simple, mixed, challenge')
        elif key == 'gaze_timing':
            if value not in ('timed', 'settled', 'friendly') or (value == 'friendly' and mode != 'red_light'):
                raise ValueError('gaze_timing: timed, settled 또는 무궁화꽃용 friendly')
        elif key == 'turn_profile':
            if value not in ('baseline', 'braking', 'smooth'):
                raise ValueError('turn_profile: baseline, braking, smooth')
            if mode != 'red_light' and value != 'baseline':
                raise ValueError('turn_profile은 무궁화꽃이 피었습니다에서 사용합니다')
        elif key == 'stop_reaction':
            if value not in ('immediate', 'delayed'):
                raise ValueError('stop_reaction: immediate 또는 delayed')
        elif key == 'randomize':
            if not isinstance(value, bool):
                raise ValueError('randomize는 bool이어야 합니다')
        else:
            lo, hi = LIMITS[key]
            value = float(value)
            if not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError(f'{key}: {lo} ~ {hi}')
        config[key] = value
    if config['gaze_timing'] == 'friendly':
        config['turn_profile'] = 'smooth'
    if config['look_duration'] >= config['gaze_period']:
        raise ValueError('look_duration은 gaze_period보다 작아야 합니다')
    return config


def apply_behavior(child, behavior_type):
    """Apply a named synthetic style; scenarios may call this after spawning."""
    if behavior_type not in BEHAVIOR_TYPES:
        raise ValueError('behavior_type: '+', '.join(BEHAVIOR_TYPES))
    child['behavior_type'] = behavior_type
    child['profile']['behavior_type'] = behavior_type


def perceive_robot(world, child):
    """Bounded geometric belief, not camera detection or access to target_id.

    The simulator supplies a range/FOV observation with optional memory. A
    pursuit cue is inferred from closing speed and robot facing alignment;
    the child's policy never reads the controller's private target choice.
    Occlusion and recognition error are not modelled by this helper.
    """
    robot = world.robot
    rx, rz = robot['x']-child['x'], robot['z']-child['z']
    actual_distance = math.hypot(rx, rz)
    facing_child = (math.sin(child['heading'])*rx+math.cos(child['heading'])*rz)/max(actual_distance, .001)
    limit = math.cos(math.radians(world.rules['child_fov_degrees'])/2)
    visible = actual_distance <= world.rules['child_perception_range'] and facing_child >= limit-1e-9
    elapsed = world.game['elapsed']
    if visible:
        linear = robot.get('linear', 0.)
        child['robot_memory'] = dict(x=robot['x'], z=robot['z'],
                                    vx=robot.get('vx', -math.sin(robot['heading'])*linear),
                                    vz=robot.get('vz', math.cos(robot['heading'])*linear),
                                    heading=robot['heading'], time=elapsed)
    memory = child.get('robot_memory')
    if memory is None or elapsed-memory['time'] > world.rules['perception_memory']+1e-9:
        child.update(robot_visible=False, perception_source='unobserved',
                     closing_speed=0., pursuit_cue=0., perceived_threat=0.)
        return None
    age = max(0., elapsed-memory['time'])
    x, z = memory['x']+memory['vx']*age, memory['z']+memory['vz']*age
    dx, dz = child['x']-x, child['z']-z
    d = math.hypot(dx, dz)
    closing = (memory['vx']*dx+memory['vz']*dz)/max(d, .001)
    alignment = (-math.sin(memory['heading'])*dx+math.cos(memory['heading'])*dz)/max(d, .001)
    pursuit = max(0., min(1., closing/.5))*max(0., min(1., (alignment-.35)/.65))
    # Receding robots reduce urgency; a robot approaching directly raises it.
    effective_distance = max(0., d-.75*max(-.8, min(.8, closing))-.9*pursuit)
    style = BEHAVIORS[child.get('behavior_type', 'helper')]
    threat = max(0., min(1., (3.5-effective_distance)/3.5*style['threat_sensitivity']))
    child.update(robot_visible=visible,
                 perception_source='geometry_range_fov' if visible else 'extrapolated_memory',
                 closing_speed=closing, pursuit_cue=pursuit, perceived_threat=threat)
    return dict(x=x, z=z, dx=dx, dz=dz, distance=d, effective_distance=effective_distance,
                closing_speed=closing, pursuit_cue=pursuit, threat=threat)


def distance(a, b):
    return math.hypot(a['x']-b['x'], a['z']-b['z'])


def angle(target, current):
    return (target-current+math.pi) % (2*math.pi)-math.pi


def watching_start_line(world):
    """The whole group shares one gaze cue along the game's +Z axis."""
    return math.cos(world.robot['heading']) >= -1e-9


class RefereeCycle:
    """Count real opportunities to move and the referee checks that follow them."""
    def __init__(self):
        self.away = False
        self.start_z = {}
        self.opportunity = False
        self.settled_seconds = 0.

    def update(self, world, dt, visible_violation):
        if not world.game['watching']:
            if not self.away:
                self.start_z = {c['id']: c['z'] for c in world.children if c['state'] != 'eliminated'}
                self.opportunity = False
            self.away = True
            self.settled_seconds = 0.
            if not self.opportunity and any(self.start_z.get(c['id'], c['z']) - c['z'] >= .2 for c in world.children):
                self.opportunity = True
                world.emit('advance_opportunity', actor='robot')
            return
        self.away = False
        if self.opportunity:
            robot = world.robot
            settled = math.cos(robot['heading']) >= math.cos(math.pi/4) and abs(robot['angular']) <= .5
            self.settled_seconds = self.settled_seconds + dt if settled else 0.
            if visible_violation or self.settled_seconds + 1e-9 >= .3:
                world.emit('referee_check', actor='robot')
                self.opportunity = False


# The browser camera has a 75° vertical FOV, a 4:3 aspect and a .22 m offset.
CAMERA_HALF_WIDTH = math.tan(math.radians(75 / 2)) * 4 / 3


def _blocks_view(origin, child, box):
    near, far = 0., 1.
    for axis, size in (('x', 'w'), ('z', 'd')):
        delta = child[axis] - origin[axis]
        low, high = box[axis] - box[size] / 2, box[axis] + box[size] / 2
        if abs(delta) < 1e-9:
            if not low <= origin[axis] <= high:
                return False
            continue
        a, b = sorted(((low-origin[axis])/delta, (high-origin[axis])/delta))
        near, far = max(near, a), min(far, b)
        if near > far:
            return False
    return far > 0. and near < 1.


def visible_to_referee(world, child):
    """Approximate the simulated camera in the floor plane."""
    if not child.get('visible', True):
        return False
    robot = world.robot
    s, c = math.sin(robot['heading']), math.cos(robot['heading'])
    eye = dict(x=robot['x']-.22*s, z=robot['z']+.22*c)
    dx, dz = child['x']-eye['x'], child['z']-eye['z']
    forward, sideways = -s*dx+c*dz, c*dx+s*dz
    if not .05 <= forward <= 40. or abs(sideways) > forward*CAMERA_HALF_WIDTH:
        return False
    if any(_blocks_view(eye, child, box) for box in world.obstacles):
        return False
    length_sq = dx*dx+dz*dz
    for other in world.children:
        if other is child or not other.get('visible', True):
            continue
        ox, oz = other['x']-eye['x'], other['z']-eye['z']
        fraction = (ox*dx+oz*dz)/length_sq
        if 0. < fraction < 1. and math.hypot(ox-fraction*dx, oz-fraction*dz) < .22:
            return False
    return True


def stop(child):
    child.update(moving=False, running=False, speed=0., motion_kind='idle', action='wait')


def finish(world, reason):
    if world.game['phase'] == 'finished':
        return
    world.game.update(phase='finished', end_reason=reason, target_id=None)
    world.game.pop('escort', None)
    world.game.pop('friendly_decision', None)
    world.game.pop('friendly_cue_gain', None)
    world.finish_motion('game_finished')
    for child in world.children:
        stop(child)
    world.emit('episode_end', reason=reason)
    world.log('게임 종료 · '+reason)


def start(world, mode, auto, seed, config, scenario):
    rng = random.Random(seed)
    world.rules = config
    world.touch_distance = config['catch_distance']
    world.game.update(mode=mode, phase='approaching' if mode == 'red_light' else 'chasing',
                      auto_chase=bool(auto), seed=seed, elapsed=0., end_reason=None,
                      eliminated_ids=[], frozen_ids=[], looking=True,
                      look_since=0.)
    if mode == 'red_light':
        world.referee_cycle = RefereeCycle()
        world.game.update(gaze_timing=config['gaze_timing'], watching=watching_start_line(world),
                          stop_reaction=config['stop_reaction'], turn_profile=config['turn_profile'])
    for i, c in enumerate(world.children):
        if mode == 'red_light':
            rng = random.Random(f'{seed}:profile:{i}')
        profile = dict(speed_scale=rng.uniform(.85, 1.15), reaction_time=rng.uniform(.08, .65),
                       stamina_drain=rng.uniform(.10, .17), turn_rate=rng.uniform(2.8, 4.5),
                       rescue_willingness=rng.uniform(.25, .95), rescue_caution=rng.uniform(1., 2.5))
        jitter = rng.uniform(-.10, .10) if config['randomize'] else 0.
        x = (i-(len(world.children)-1)/2)*.85+jitter
        z = world.home_z if mode == 'red_light' else .3+(i % 2)*1.15+jitter
        if mode == 'red_light':
            x, z = scenario['children'][i]['x'], scenario['children'][i]['z']
            style = config['child_behavior']
            if style == 'mixed':
                style = scenario['behavior_types'][i]
            difficulty = config['trajectory_difficulty']
            spread = {'simple': 0., 'mixed': .65, 'challenge': 1.}[difficulty]
            cautious = style == 'cautious'
            profile.update(
                hesitation=spread*rng.uniform(.1, .6 if cautious else .35),
                detour=spread*rng.uniform(.25, .85 if style == 'playful' else .55),
                wait_probability=.7 if cautious else .22,
                side=rng.choice((-1, 1)),
            )
            profile['speed_scale'] = config['child_speed_scale'] * (1.+spread*(profile['speed_scale']-1.))
            c.update(decision_number=0, route_phase=None, waypoint=None, wait_until=0.)
        c.update(x=x, z=z, home_x=x, heading=math.pi if mode == 'red_light' else (i*.9) % (2*math.pi), profile=profile,
                 state='stopped' if mode == 'red_light' else 'free', caught=False,
                 escaped=False, running=False, moving=False, wave=False, mode='walk',
                 stamina=1., resting=False, speed=0., motion_time=i*.17, motion_kind='idle',
                 watched=world.robot_watching(c), action='wait', target_id=None,
                 rescue_progress=0., immune_until=0., was_threatened=False,
                 robot_memory=None, robot_visible=False, perception_source='unobserved',
                 closing_speed=0., pursuit_cue=0., perceived_threat=0.)
        behavior = config['child_behavior']
        apply_behavior(c, BEHAVIOR_TYPES[(seed+i) % len(BEHAVIOR_TYPES)] if behavior == 'mixed' else behavior)
        if mode == 'red_light':
            c.update(watched=world.game['watching'], watch_since=0.)
    world.emit('episode_start', mode=mode)
    world.log(dict(tag='술래잡기', freeze_tag='얼음땡', red_light='무궁화꽃이 피었습니다')[mode]+' 시작 · 가상 행동 규칙')


def catch(world):
    g = world.game
    if g['phase'] not in ('chasing', 'escaping') or g['held']:
        return
    mode = g['mode']
    for c in world.children:
        if c['state'] not in ('free', 'rescuing', 'escaping') or g['elapsed'] < c['immune_until']:
            continue
        if distance(c, world.robot) > world.touch_distance:
            continue
        c['caught'] = True
        c['target_id'] = None
        stop(c)
        if mode == 'freeze_tag':
            c['state'] = 'frozen'
            g['frozen_ids'].append(c['id'])
            world.emit('freeze', actor='robot', target=c['id'], reason='within_catch_distance')
        else:
            c['state'] = 'caught'
            world.emit('catch', actor='robot', target=c['id'], reason='within_catch_distance')
            world.log(f"{c['name']} 잡힘")
        if c['id'] not in g['caught_ids']:
            g['caught_ids'].append(c['id'])
    if mode == 'freeze_tag' and all(c['state'] == 'frozen' for c in world.children):
        finish(world, 'all_frozen')
    elif mode in ('tag', 'red_light') and all(c['state'] in ('caught', 'escaped', 'eliminated') for c in world.children):
        finish(world, 'all_caught' if mode == 'tag' else 'pursuit_complete')


def move(world, c, tx, tz, speed, dt, *, flee=False):
    dx, dz = tx-c['x'], tz-c['z']
    length = max(math.hypot(dx, dz), .001)
    vx, vz = dx/length, dz/length
    for other in world.children:
        if other['id'] == c['id']:
            continue
        ox, oz = c['x']-other['x'], c['z']-other['z']
        d = math.hypot(ox, oz)
        if d < .9:
            vx += ox/max(d, .05)*(1-d/.9)*1.8
            vz += oz/max(d, .05)*(1-d/.9)*1.8
    desired = math.atan2(vx, vz)
    best = None
    for offset in (0, .35, -.35, .7, -.7, 1.1, -1.1, 1.6, -1.6, 2.3, -2.3, math.pi):
        h = desired+offset
        x, z = c['x']+math.sin(h)*speed*dt, c['z']+math.cos(h)*speed*dt
        if not clear(world, c, x, z):
            continue
        space = world.clearance(x+math.sin(h)*.4, z+math.cos(h)*.4, exclude_child=c['id'])
        score = math.cos(offset)+min(space, .5)*1.6-abs(angle(h, c['heading']))*.04
        if best is None or score > best[0]:
            best = score, h
    moved = False
    if best:
        turn = max(-c['profile']['turn_rate']*dt,
                   min(c['profile']['turn_rate']*dt, angle(best[1], c['heading'])))
        c['heading'] += turn
        x, z = c['x']+math.sin(c['heading'])*speed*dt, c['z']+math.cos(c['heading'])*speed*dt
        if clear(world, c, x, z):
            c.update(x=x, z=z)
            moved = True
        if abs(angle(best[1], desired)) > .3 and world.game['elapsed']-c.get('last_avoidance', -1.) > .5:
            world.emit('avoidance_turn', actor=c['id'], reason='clearance_steering')
            c['last_avoidance'] = world.game['elapsed']
    world.contact(c['id'], 'blocked', not moved)
    c.update(moving=moved, speed=speed if moved else 0., running=moved and flee,
             motion_kind='run' if moved and flee else 'jog' if moved and speed > .52 else 'walk' if moved else 'idle')
    if moved:
        c['motion_time'] += dt*speed/(.85 if flee else .62 if speed > .52 else .44)


def clear(world, c, x, z):
    return world.clearance(x, z, exclude_child=c['id']) > .25 and math.hypot(x-world.robot['x'], z-world.robot['z']) > world.radius+.25


def rescue(world, c, dt, perception=None):
    g = world.game
    candidates = [o for o in world.children if o['state'] == 'frozen']
    perceived_distance = perception['distance'] if perception else math.inf
    if not candidates or perceived_distance < c['profile']['rescue_caution']:
        c.update(rescue_progress=0., target_id=None, state='free')
        return False
    target = min(candidates, key=lambda o: distance(c, o)/c['profile']['rescue_willingness'])
    # Willingness affects how far away a child will commit to helping.
    willingness = min(1., c['profile']['rescue_willingness']*BEHAVIORS[c.get('behavior_type', 'helper')]['rescue_scale'])
    if distance(c, target) > 1.5+6*willingness:
        c.update(rescue_progress=0., target_id=None, state='free')
        return False
    if c['target_id'] != target['id']:
        world.emit('rescue_attempt', actor=c['id'], target=target['id'])
        c['rescue_progress'] = 0.
    c.update(state='rescuing', target_id=target['id'], action='rescue')
    if distance(c, target) > world.rules['rescue_distance']:
        c['rescue_progress'] = 0.
        move(world, c, target['x'], target['z'], .65*c['profile']['speed_scale'], dt)
        return True
    stop(c)
    c['action'] = 'rescue'
    c['rescue_progress'] += dt
    if c['rescue_progress']+1e-9 >= world.rules['rescue_hold']:
        target.update(state='free', caught=False, immune_until=g['elapsed']+world.rules['immunity'])
        for key in ('caught_ids', 'frozen_ids'):
            if target['id'] in g[key]:
                g[key].remove(target['id'])
        world.emit('thaw', actor=c['id'], target=target['id'])
        c.update(state='free', rescue_progress=0., target_id=None)
    return True


def follow_red_light_path(world, child, target_x, target_z, speed, dt, *, returning=False):
    """Choose a local waypoint at decision times, then use the common bounded mover."""
    profile = child['profile']
    dx, dz = target_x-child['x'], target_z-child['z']
    remaining = math.hypot(dx, dz)
    now = world.game['elapsed']
    phase = world.game['phase']
    if remaining <= 1.35 or not profile['detour']:
        child['waypoint'] = None
        move(world, child, target_x, target_z, speed, dt, flee=returning)
        return
    point = child['waypoint']
    if child['route_phase'] != phase or point is None or now >= child['replan_at'] or distance(child, point) < .23:
        index = child['decision_number']
        rng = random.Random(f"{world.game['seed']}:{child['id']}:{phase}:{index}")
        child.update(decision_number=index+1, route_phase=phase, wait_until=now)
        ux, uz = dx/remaining, dz/remaining
        ahead = rng.uniform(.7, 1.25)
        center_x, center_z = child['x']+ux*ahead, child['z']+uz*ahead
        preferred = profile['side'] * profile['detour'] * rng.uniform(.35, 1.)
        def space(x, z):
            return min(world.clearance(x, z, exclude_child=child['id']),
                       math.hypot(x-world.robot['x'], z-world.robot['z'])-world.radius)
        choices = [(center_x+uz*off, center_z-ux*off) for off in (preferred, -preferred, 0.)]
        px, pz = max(choices, key=lambda p: min(.65, space(*p)))
        if space(center_x, center_z) < .32 and rng.random() < profile['wait_probability']:
            child['wait_until'] = now+rng.uniform(.1, .4)
        point = dict(x=px, z=pz)
        child.update(waypoint=point, replan_at=now+rng.uniform(.8, 1.5))
    if now < child['wait_until']:
        stop(child)
        child['action'] = 'yield'
        return
    move(world, child, point['x'], point['z'], speed, dt, flee=returning)


def red_light(world, c, dt):
    """Advance one participant and report movement after the stop grace."""
    g = world.game
    if c['state'] in ('eliminated', 'escaped', 'caught'):
        stop(c)
        return False
    if g['phase'] == 'escaping':
        c.update(state='escaping', action='escape')
        if math.hypot(c['x']-c['home_x'], c['z']-world.home_z) < .12:
            c.update(state='escaped', escaped=True)
            g['escaped_ids'].append(c['id'])
            stop(c)
            world.emit('escape', actor=c['id'], reason='home_reached')
        else:
            follow_red_light_path(world, c, c['home_x'], world.home_z,
                                  .95*c['profile']['speed_scale'], dt, returning=True)
        return False
    watched = g['watching']
    if watched != c['watched']:
        c['watch_since'] = g['elapsed']
        c['waypoint'] = None
        world.emit('gaze_change', actor='robot', target=c['id'], watched=watched)
    c['watched'] = watched
    delay = g['elapsed']-c.get('watch_since', 0.)
    # Only an already-moving child has a delayed stop; waiting children do not
    # begin moving merely because the robot is looking at them.
    delayed = world.rules['stop_reaction'] == 'delayed'
    should_move = not watched or (delayed and c['moving'] and delay < c['profile']['reaction_time'])
    if not watched and delay < c['profile']['hesitation']:
        should_move = False
    if c['mode'] == 'still' or (c['mode'] == 'intermittent' and (world.time+c['phase']) % 5 >= 2.7):
        should_move = False
    if should_move:
        c.update(state='approaching', action='approach')
        follow_red_light_path(world, c, world.robot['x']+max(-.6, min(.6, c['home_x']*.2)),
                              world.robot['z'], c['pace']*c['profile']['speed_scale'], dt)
    else:
        if c['moving'] and watched:
            world.emit('stop_response', actor=c['id'], delay=round(delay, 6))
        c['state'] = 'stopped'
        stop(c)
    return (delayed and watched and delay > world.rules['detection_grace'] + 1e-9
            and c['speed'] > world.rules['movement_threshold'])


def start_escort(world, child):
    game, robot = world.game, world.robot
    xmin, xmax, zmin, zmax = world.bounds
    side_positions = sorted(((xmin+1.45, -1), (xmax-1.45, 1)),
                            key=lambda side: abs(side[0]-child['x']))
    # Prefer a free slot near the child's current row, including a spot for
    # the robot to lead it beyond the drop-off without blocking the child.
    slots = []
    for x, side in side_positions:
        for row in range(math.floor((zmax-zmin-1.6)/.85)+1):
            z = zmin+.8+row*.85
            guide_x = x+.85*side
            if (world.clearance(x, z, exclude_child=child['id']) > .32
                    and world.clearance(guide_x, z, exclude_child=child['id']) > world.radius+.08):
                slots.append((distance(child, dict(x=x, z=z)), x, z, guide_x))
    # The default room has open edges. If a custom layout blocks every slot,
    # wait for a later visible movement instead of eliminating in place.
    if not slots:
        return
    _, x, z, guide_x = min(slots)
    game['escort'] = dict(child_id=child['id'], stage='pickup',
                          origin={key: robot[key] for key in ('x','z','heading')},
                          goal=dict(x=child['x'], z=child['z']), drop=dict(x=x, z=z),
                          lead=dict(x=guide_x, z=z), waiting=False, started=game['elapsed'])
    dx, dz = robot['x']-child['x'], robot['z']-child['z']
    bearing = math.atan2(dz, dx)
    for offset in (0., .75, -.75, 1.5, -1.5, math.pi):
        point = dict(x=child['x']+.84*math.cos(bearing+offset),
                     z=child['z']+.84*math.sin(bearing+offset))
        route = plan_route(world, point)
        if route:
            game['escort'].update(route=route, goal=route[0])
            break
    game['eliminated_ids'].append(child['id'])
    world.emit('movement_detected', actor='robot', target=child['id'], reason='visible_movement_after_stop')
    for other in world.children:
        stop(other)
        if other['state'] != 'eliminated':
            other['state'] = 'stopped'
    child.update(state='eliminated', caught=True, action='escort')
    world.emit('escort_start', actor='robot', target=child['id'])


def advance_escort(world, dt):
    game, robot = world.game, world.robot
    escort = game['escort']
    child = world.children[escort['child_id']]
    stage = escort['stage']
    route = escort.get('route')
    if route and len(route) > 1 and distance(robot, route[0]) <= .14:
        route.pop(0)
        escort['goal'] = route[0]
    if stage == 'pickup':
        if distance(robot, child) <= .98:
            route = plan_route(world, escort['lead'])
            escort.update(stage='lead', route=route, goal=route[0] if route else escort['lead'])
        return
    if stage == 'lead':
        gap = distance(robot, child)
        guide_arrived = distance(robot, escort['lead']) <= .16
        if guide_arrived and distance(child, escort['drop']) <= .20:
            stop(child)
            world.emit('escort_complete', actor='robot', target=child['id'])
            if len(game['eliminated_ids']) == len(world.children):
                finish(world, 'all_eliminated')
            else:
                route = plan_route(world, escort['origin'])
                escort.update(stage='return', route=route, goal=route[0] if route else escort['origin'],
                              waiting=False)
            return
        escort['waiting'] = gap > 1.65 and not guide_arrived
        if guide_arrived or gap > 1.02:
            goal = escort['drop'] if guide_arrived else robot
            move(world, child, goal['x'], goal['z'], .58, dt)
        else:
            stop(child)
        child['action'] = 'escort'
        return
    origin = escort['origin']
    if distance(robot, origin) <= .16:
        escort.update(aligning=True, goal=origin, route=[])
    if (escort.get('aligning') and abs(angle(origin['heading'], robot['heading'])) <= .05
            and abs(robot['angular']) <= .08):
        game['gaze_pause'] = game.get('gaze_pause', 0.) + game['elapsed']-escort['started']
        game.pop('escort')
        world.emit('escort_return', actor='robot', target=child['id'])
        world.referee_cycle = RefereeCycle()
        game['watching'] = watching_start_line(world)
        for other in world.children:
            other.update(watch_since=game['elapsed'], watched=game['watching'])


def advance_children(world, dt):
    g = world.game
    if g['phase'] in ('ready', 'finished') or g['held']:
        return
    g['elapsed'] = round(g['elapsed']+dt, 9)
    if g['elapsed']+1e-9 >= world.rules['time_limit']:
        finish(world, 'time_limit')
        return
    if g.get('escort'):
        advance_escort(world, dt)
        return
    if g['mode'] == 'red_light' and g['phase'] == 'approaching':
        g['watching'] = watching_start_line(world)
    catch(world)
    detected = []
    for c in world.children:
        if g['phase'] == 'finished':
            break
        if g['mode'] == 'red_light':
            if red_light(world, c, dt):
                detected.append(c)
            continue
        if c['state'] in ('caught', 'frozen'):
            stop(c)
            continue
        perception = perceive_robot(world, c)
        if g['mode'] == 'freeze_tag' and rescue(world, c, dt, perception):
            continue
        d = perception['distance'] if perception else math.inf
        threatened = perception is not None and perception['threat'] > 0.
        if threatened and not c['was_threatened']:
            c['threat_since'] = g['elapsed']
            world.emit('flee_start', actor=c['id'], target='robot')
        c['was_threatened'] = threatened
        reacted = g['elapsed']-c.get('threat_since', 0.) >= c['profile']['reaction_time']
        urgency = perception['threat'] if reacted and perception else 0.
        wander = g['elapsed']*.33+c['phase']
        amplitude = BEHAVIORS[c.get('behavior_type', 'helper')]['wander']
        vx = math.sin(wander)*amplitude+(perception['dx']/max(d, .05)*urgency*2.8 if perception else 0.)
        vz = math.cos(wander*.81)*amplitude+(perception['dz']/max(d, .05)*urgency*2.8 if perception else 0.)
        if c['resting'] and c['stamina'] > .65:
            c['resting'] = False
        if c['stamina'] < .12:
            c['resting'] = True
        # Dynamic cues affect the speed decision after the child's reaction
        # delay. Existing close-range caution remains even for a stopped robot.
        response_distance = perception['effective_distance'] if reacted and perception else d
        running = response_distance < 2.8 and not c['resting']
        jogging = 2.8 <= response_distance < 3.5 and not c['resting']
        speed = (.83+(c['id'] % 3)*.06) if running else (.56+(c['id'] % 3)*.04) if jogging else (.15 if c['resting'] else .40+(c['id'] % 3)*.04)
        c['stamina'] = max(0., min(1., c['stamina']+dt*(-c['profile']['stamina_drain'] if running else -.04 if jogging else .22)))
        c.update(action='flee' if threatened else 'wander', target_id=None, state='free')
        move(world, c, c['x']+vx, c['z']+vz, speed*c['profile']['speed_scale'], dt, flee=running)
    visible = [c for c in detected if visible_to_referee(world, c)]
    if g['mode'] == 'red_light' and g['phase'] == 'approaching':
        world.referee_cycle.update(world, dt, bool(visible))
    if visible:
        start_escort(world, min(visible, key=lambda c: (distance(world.robot, c), c['id'])))
    check_touch(world)
    catch(world)


def check_touch(world):
    g = world.game
    if g['mode'] != 'red_light':
        catch(world)
        return
    if g['held'] or g.get('escort'):
        return
    if g['phase'] == 'approaching':
        touching = [c for c in world.children if c['state'] != 'eliminated' and distance(c, world.robot) <= world.touch_distance]
        if touching:
            child = min(touching, key=lambda c: (distance(c, world.robot), c['id']))
            g.update(phase='escaping', touched_by=child['id'], touched_at=world.time, watching=False,
                     chase_since=g['elapsed'])
            for c in world.children:
                if c['state'] != 'eliminated':
                    stop(c)
                    c.update(state='escaping', action='escape', watched=False, mode='walk',
                             immune_until=g['elapsed']+world.rules['immunity'])
            world.emit('touch', actor=child['id'], target='robot')
            world.log(f"{child['name']} 술래 터치! · 모두 출발선으로 도망갑니다")
        elif all(c['state'] == 'eliminated' for c in world.children):
            finish(world, 'all_eliminated')
    if g['phase'] == 'escaping':
        catch(world)
        if g['phase'] != 'finished' and (all(c['state'] in ('caught', 'escaped', 'eliminated') for c in world.children)
                                        or g['elapsed']-g['chase_since'] >= world.rules['chase_duration']):
            finish(world, 'pursuit_complete')
