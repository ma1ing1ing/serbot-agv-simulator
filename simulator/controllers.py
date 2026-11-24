"""Replaceable observation-only robot policies; these are rule baselines, not ML."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from .contracts import MotionAction, SCHEMA_VERSION


class Controller(Protocol):
    def reset(self, seed=None):
        """Clear per-episode policy memory."""

    def predict(self, observation: dict) -> MotionAction:
        """Choose a desired velocity without modifying the environment."""


class IdleController:
    name = 'idle'
    target_id = None

    def reset(self, seed=None):
        self.target_id = None

    def predict(self, observation):
        return MotionAction()


def _angle(target, current):
    return (target-current+math.pi) % (2*math.pi)-math.pi


class _PursuitController:
    """Common observation-only pursuit for the game-specific baselines.

    It can run against oracle observations for the known-state benchmark or
    sensor observations containing an external detector's relative positions.
    In sensor mode it cannot know which players are frozen or caught.
    """
    model_version = 'game-rules-1'
    eligible_states = ('free', 'rescuing', 'unknown')
    active_phases = ('chasing',)
    target_margin = .3

    def __init__(self):
        self.reset()

    def reset(self, seed=None):
        self.target_id = None
        self.looking = True

    def _inactive(self, observation):
        if observation.get('schema_version') != SCHEMA_VERSION:
            raise ValueError('unsupported observation schema_version')
        game = observation['game']
        if game['mode'] != self.mode:
            raise ValueError(f'{self.name} supports only {self.mode}')
        return game['held'] or game['phase'] not in self.active_phases

    @staticmethod
    def _world_point(robot, child):
        right, forward = child['relative_x'], child['relative_z']
        h = robot['heading']
        return dict(id=child['id'], x=robot['x']+math.cos(h)*right-math.sin(h)*forward,
                    z=robot['z']+math.sin(h)*right+math.cos(h)*forward)

    @staticmethod
    def _target_bearing(target):
        return target['bearing']

    def _clearance_course(self, observation, desired, exclude_id, lookahead=.55):
        robot = observation['robot']
        points = [self._world_point(robot, c) for c, mask in zip(observation['children'], observation['child_mask'])
                  if mask and c['id'] != exclude_id]
        xmin, xmax, zmin, zmax = observation['bounds']
        options = []
        for offset in (0., .45, -.45, .9, -.9, 1.4, -1.4, 2., -2.):
            h = desired+offset
            x, z = robot['x']-math.sin(h)*lookahead, robot['z']+math.cos(h)*lookahead
            spaces = [x-xmin, xmax-x, z-zmin, zmax-z]
            for b in observation['obstacles']:
                spaces.append(math.hypot(max(abs(x-b['x'])-b['w']/2, 0.), max(abs(z-b['z'])-b['d']/2, 0.)))
            spaces.extend(math.hypot(x-c['x'], z-c['z'])-.22 for c in points)
            options.append((math.cos(offset)+min(min(spaces)-.42, .3)*3., h))
        return max(options, key=lambda item: item[0])[1]

    def predict(self, observation):
        if self._inactive(observation):
            self.target_id = None
            return MotionAction()
        return self._pursue(observation)

    def _select_target(self, candidates, observation):
        return min(candidates, key=lambda c: (
            c['distance'] - (self.target_margin if c['id'] == self.target_id else 0.), c['id']))

    def _pursue(self, observation):
        robot, rules = observation['robot'], observation['rules']
        candidates = [c for c, mask in zip(observation['children'], observation['child_mask'])
                      if mask and c['state'] in self.eligible_states]
        if not candidates:
            self.target_id = None
            return MotionAction()
        target = self._select_target(candidates, observation)
        self.target_id = target['id']
        desired = robot['heading']+self._target_bearing(target)
        if observation['source'] == 'oracle':
            desired = self._clearance_course(observation, desired, target['id'])
        elif observation['sensors'].get('front_m', 4.) < .3:
            left = observation['sensors'].get('left_m', 0.)
            right = observation['sensors'].get('right_m', 0.)
            return MotionAction(0., 1.5 if left >= right else -1.5)
        error = _angle(desired, robot['heading'])
        speed = rules['robot_speed']*max(0., math.cos(error))
        return MotionAction(speed, max(-2.4, min(2.4, error*3)), guard=False)


class TagController(_PursuitController):
    """Chase a nearby uncaught child; choose another after a capture."""
    name = 'tag_rule'
    mode = 'tag'


class FreezeTagController(_PursuitController):
    """Chase free/rescuing children; thawed children become eligible again."""
    name = 'freeze_tag_rule'
    mode = 'freeze_tag'


@dataclass(frozen=True)
class _GazeTurn:
    target: float
    start_heading: float
    delta: float
    started_at: float

    @staticmethod
    def _smoothstep(u):
        return u**3 * (10. - 15.*u + 6.*u**2)

    def angular_command(self, robot, rules, now, dt):
        # Unwrap about the middle of the planned arc. A noisy heading at ±π
        # must not change the chosen direction at the start of a half-turn.
        remaining = self.delta/2 + _angle(self.start_heading + self.delta/2, robot['heading'])
        distance = abs(remaining)
        if distance <= .001:
            return 0.
        acceleration = rules['max_angular_acceleration']
        speed_limit = min(2.4, rules['max_angular'])
        # Leave enough angle to hold this command for one control interval
        # and then brake. Account for momentum already present at takeover.
        braking_limit = 2.*distance / (dt + math.sqrt(dt*dt + 2.*distance/acceleration))
        free_angle = max(0., distance - robot['angular']**2/(2.*acceleration))
        limit = min(speed_limit, braking_limit, free_angle/dt)
        if rules['turn_profile'] == 'braking':
            return math.copysign(limit, remaining)

        # Peak derivatives of the quintic are 1.875 and 10/sqrt(3).
        duration = max(2.6, 1.875*abs(self.delta)/speed_limit,
                       math.sqrt(10./math.sqrt(3.)*abs(self.delta)/acceleration))
        u = min(1., (now-self.started_at)/duration)
        next_u = min(1., (now-self.started_at+dt)/duration)
        progress = self._smoothstep(u)
        # Average reference velocity over the held action, plus position feedback.
        feedforward = self.delta * (self._smoothstep(next_u)-progress) / dt
        error = remaining - self.delta*(1.-progress)
        commanded = feedforward + min(2., 1./dt)*error
        if commanded*remaining <= 0.:
            return 0.
        return math.copysign(min(abs(commanded), limit), remaining)


class RedLightController(_PursuitController):
    """Alternate facing home/away, then pursue after the first touch.

    The default schedule includes turn time. The optional settled schedule
    starts each dwell after the measured heading and speeds have settled.
    Actual heading determines the group's stop cue in both schedules.
    """
    name = 'red_light_rule'
    mode = 'red_light'
    eligible_states = ('escaping', 'unknown')
    active_phases = ('approaching', 'escaping')

    def reset(self, seed=None):
        super().reset(seed)
        self._gaze_ready_since = None
        self._last_gaze_at = None
        self._turn = None
        self._last_turn_at = None

    def predict(self, observation):
        if self._inactive(observation):
            self.target_id = None
            self._turn = None
            self._gaze_ready_since = self._last_gaze_at = None
            return MotionAction()
        game, robot, rules = observation['game'], observation['robot'], observation['rules']
        if game.get('escort'):
            self._turn = None
            self._gaze_ready_since = self._last_gaze_at = None
            return self._escort_motion(observation, game['escort'])
        if game['phase'] == 'approaching':
            self.target_id = None
            if rules.get('gaze_timing') in ('settled', 'friendly'):
                return self._settled_gaze(observation)
            self.looking = game.get('gaze_elapsed', game['elapsed']) % rules['gaze_period'] < rules['look_duration']
            if rules.get('turn_profile', 'baseline') != 'baseline':
                return self._profiled_turn(observation)
            error = _angle(0. if self.looking else math.pi, robot['heading'])
            return MotionAction(0., max(-2.4, min(2.4, error*3)), guard=False)
        self._turn = None
        self._gaze_ready_since = self._last_gaze_at = None
        return self._pursue(observation)

    def _profiled_turn(self, observation):
        robot, rules = observation['robot'], observation['rules']
        target = 0. if self.looking else math.pi
        now, dt = observation['time'], observation['control_dt']
        interrupted = self._last_turn_at is None or now-self._last_turn_at > dt+1e-9
        if self._turn is None or self._turn.target != target or interrupted:
            delta = _angle(target, robot['heading'])
            self._turn = _GazeTurn(target, robot['heading'], delta, now)
        self._last_turn_at = now
        return MotionAction(angular_rps=self._turn.angular_command(robot, rules, now, dt))

    def _escort_motion(self, observation, escort):
        stage, goal = escort['stage'], escort['goal']
        self.target_id = None if stage == 'return' else escort['child_id']
        if escort['waiting']:
            return MotionAction()
        robot = observation['robot']
        dx, dz = goal['x']-robot['x'], goal['z']-robot['z']
        distance = math.hypot(dx, dz)
        stop_at = .94 if stage == 'pickup' and not escort['routed'] else .08
        desired = math.atan2(-dx, dz)
        speed = 0.
        if stage == 'return' and escort['aligning']:
            desired = goal['heading']
        elif distance > stop_at:
            remaining = distance - stop_at
            if not escort['routed'] and observation['source'] == 'oracle':
                desired = self._clearance_course(observation, desired,
                                                 self.target_id if stage == 'pickup' else None,
                                                 min(.55, remaining+.08))
            cap = .37 if stage == 'lead' else .46
            speed = min(cap, remaining * 1.7)
        else:
            return MotionAction()
        error = _angle(desired, robot['heading'])
        return MotionAction(speed*max(0., (math.cos(error)-.5)*2),
                            max(-2.4, min(2.4, error*3)))

    def _gaze_dwell(self, observation):
        rules = observation['rules']
        return rules['look_duration'] if self.looking else rules['gaze_period'] - rules['look_duration']

    def _settled_gaze(self, observation):
        robot, rules = observation['robot'], observation['rules']
        elapsed = observation['game']['elapsed']
        dt = observation['control_dt']
        # An interval controlled externally cannot count toward the dwell.
        if self._last_gaze_at is not None and elapsed - self._last_gaze_at > dt + 1e-9:
            self._gaze_ready_since = None
        self._last_gaze_at = elapsed

        target = 0. if self.looking else math.pi
        error = _angle(target, robot['heading'])
        aligned = abs(error) <= .02
        stopped = abs(robot['angular']) <= .05 and abs(robot['linear']) <= .01
        if aligned and stopped:
            if self._gaze_ready_since is None:
                self._gaze_ready_since = elapsed
            dwell = self._gaze_dwell(observation)
            if elapsed - self._gaze_ready_since + 1e-9 < dwell:
                self._turn = None
                return MotionAction()
            self.looking = not self.looking
            target = 0. if self.looking else math.pi
            error = _angle(target, robot['heading'])
        self._gaze_ready_since = None
        if rules.get('turn_profile', 'baseline') != 'baseline':
            return self._profiled_turn(observation)

        # Cap the proportional gain for actions held over a longer PlayEnv step.
        turn_rate = error * min(3., 1. / dt) if abs(error) > .02 else 0.
        return MotionAction(angular_rps=max(-2.4, min(2.4, turn_rate)))


class RuleController:
    """Select the game's fixed rule policy; preserves the ``rule`` entry point.

    These policies do not train or update their parameters during play. Seed
    resets clear target memory; game settings still set speed and gaze timing.
    """
    name = 'rule'
    model_version = _PursuitController.model_version

    def __init__(self):
        self._controllers = {policy.mode: policy() for policy in
                             (TagController, FreezeTagController, RedLightController)}
        self.reset()

    def reset(self, seed=None):
        for controller in self._controllers.values():
            controller.reset(seed)
        self._active = None

    @property
    def target_id(self):
        return self._active.target_id if self._active is not None else None

    @property
    def looking(self):
        return self._active.looking if self._active is not None else True

    def predict(self, observation):
        if observation.get('schema_version') != SCHEMA_VERSION:
            raise ValueError('unsupported observation schema_version')
        mode = observation['game']['mode']
        if mode not in self._controllers:
            raise ValueError('unsupported rule-controller game: '+str(mode))
        self._active = self._controllers[mode]
        return self._active.predict(observation)
