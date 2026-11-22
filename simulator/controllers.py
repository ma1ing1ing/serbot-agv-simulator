"""Replaceable observation-only robot policies; these are rule baselines, not ML."""
from __future__ import annotations

import math
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

    def predict(self, observation):
        if self._inactive(observation):
            self.target_id = None
            return MotionAction()
        return self._pursue(observation)

    def _pursue(self, observation):
        robot, rules = observation['robot'], observation['rules']
        candidates = [c for c, mask in zip(observation['children'], observation['child_mask'])
                      if mask and c['state'] in self.eligible_states]
        if not candidates:
            self.target_id = None
            return MotionAction()
        target = min(candidates, key=lambda c: (c['distance']-(self.target_margin if c['id'] == self.target_id else 0.), c['id']))
        self.target_id = target['id']
        desired = robot['heading']+self._target_bearing(target)
        if observation['source'] == 'oracle':
            points = [self._world_point(robot, c) for c, mask in zip(observation['children'], observation['child_mask']) if mask]
            xmin, xmax, zmin, zmax = observation['bounds']
            options = []
            for offset in (0., .45, -.45, .9, -.9, 1.4, -1.4, 2., -2.):
                h = desired+offset
                x, z = robot['x']-math.sin(h)*.55, robot['z']+math.cos(h)*.55
                spaces = [x-xmin, xmax-x, z-zmin, zmax-z]
                for b in observation['obstacles']:
                    spaces.append(math.hypot(max(abs(x-b['x'])-b['w']/2, 0.), max(abs(z-b['z'])-b['d']/2, 0.)))
                spaces.extend(math.hypot(x-c['x'], z-c['z'])-.22 for c in points if c['id'] != target['id'])
                options.append((math.cos(offset)+min(min(spaces)-.42, .3)*3., h))
            desired = max(options, key=lambda item: item[0])[1]
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


class RedLightController(_PursuitController):
    """Alternate facing home/away, then pursue after the first touch.

    Turn time is included in the existing gaze-period schedule. Actual robot
    heading (not this controller's desired ``looking`` flag) determines which
    children are watched. Proportional steering works at both live and stepped
    control intervals without treating angular error as a one-tick command.
    """
    name = 'red_light_rule'
    mode = 'red_light'
    eligible_states = ('escaping', 'unknown')
    active_phases = ('approaching', 'escaping')

    def predict(self, observation):
        if self._inactive(observation):
            self.target_id = None
            return MotionAction()
        game, robot, rules = observation['game'], observation['robot'], observation['rules']
        if game['phase'] == 'approaching':
            self.target_id = None
            self.looking = game['elapsed'] % rules['gaze_period'] < rules['look_duration']
            error = _angle(0. if self.looking else math.pi, robot['heading'])
            return MotionAction(0., max(-2.4, min(2.4, error*3)), guard=False)
        return self._pursue(observation)


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
