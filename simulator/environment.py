"""Isolated, deterministic state-based robot control episodes (no browser needed)."""
from __future__ import annotations

from collections import Counter
import copy

from .contracts import MotionAction, finite
from .engine import World
from . import games, scenarios
from .motion import validate_physics


def default_reward(previous_observation, action, observation, info):
    """Illustrative benchmark reward, not a validated model of enjoyable play."""
    events = info['event_delta']
    progress = events.get('catch', 0)+.8*(events.get('freeze', 0)-events.get('thaw', 0))
    progress += .5*events.get('movement_detected', 0)-events.get('escape', 0)-.25*events.get('touch', 0)
    return progress-.01*info['step_seconds']-.05*info['metrics_delta']['blocked_attempts']-.002*info['metrics_delta']['near_miss_steps']


class PlayEnv:
    """Common Python interface. Rendering remains a separate live-browser task.

    Every instance owns a World unless ``world`` explicitly supplies the local
    HTTP server's World. reset/step are atomic against that World's live clock.
    Controllers receive observations only; evaluation truth stays in info.
    """
    def __init__(self, game='tag', controller=None, observation_mode='oracle', reward_fn=None,
                 dt=.1, physics=None, *, world=None, serbot_sensors=False):
        games.options(game, 0, None)
        if not isinstance(serbot_sensors, bool):
            raise ValueError('serbot_sensors must be a bool')
        if observation_mode not in ('oracle', 'sensor'):
            raise ValueError('observation_mode: oracle or sensor')
        dt = finite(dt, 'dt')
        if not .02 <= dt <= 1. or abs(dt/.02-round(dt/.02)) > 1e-8:
            raise ValueError('dt: 0.02..1.0 seconds in multiples of 0.02')
        if controller is not None and (not callable(getattr(controller, 'predict', None)) or not callable(getattr(controller, 'reset', None))):
            raise ValueError('controller must implement reset(seed) and predict(observation)')
        if reward_fn is not None and not callable(reward_fn):
            raise ValueError('reward_fn must be callable')
        self.game = game
        self.controller = controller
        self.observation_mode = observation_mode
        self.reward_fn = reward_fn or default_reward
        self.dt = dt
        self.ticks = round(dt/.02)
        self.physics = validate_physics(physics)
        self.serbot_sensors = serbot_sensors
        self.world = world if world is not None else World()
        self.active = False
        self.closed = False
        self.last_observation = None
        self.epoch = None

    def reset(self, *, seed=0, scenario='open', settings=None, count=5,
              record=False, record_dir=None, split='interactive'):
        if self.closed:
            raise ValueError('environment is closed; construct a new PlayEnv')
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 8:
            raise ValueError('count: 1..8 integer')
        defaults = getattr(self.controller, 'default_game_settings', None)
        if defaults and (settings is None or isinstance(settings, dict)):
            settings = {**defaults, **(settings or {})}
        games.options(self.game, seed, settings)
        prepared = scenarios.prepare_scenario(scenario, count, seed, game=self.game)
        if not isinstance(record, bool) or split not in ('interactive','train','validation','test'):
            raise ValueError('record must be bool and split must be interactive/train/validation/test')
        if record_dir is not None:
            from pathlib import Path
            if record and Path(record_dir).exists():
                raise ValueError('record directory already exists')
        with self.world.lock:
            # Count is passed into start_game so reset validates everything before
            # it ends the previous episode or changes the participant population.
            self.world.start_game(self.game, False, seed=seed, settings=settings, count=count,
                                  scenario=prepared, physics=self.physics, record=record, record_dir=record_dir,
                                  split=split, observation_mode=self.observation_mode,
                                  execution_mode='stepped', control_dt=self.dt, serbot_sensors=self.serbot_sensors,
                                  controller_name=getattr(self.controller,'name',self.controller.__class__.__name__) if self.controller else 'external_or_manual')
            self.epoch = self.world.epoch
            if self.controller is not None:
                try:
                    self.controller.reset(seed)
                except BaseException:
                    self.world.finish_game('controller_error')
                    self.active = False
                    raise
            self.active = True
            self.last_observation = self.world.observe(self.observation_mode)
            return copy.deepcopy(self.last_observation), self.info()

    def info(self):
        w = self.world
        if self.epoch is not None and self.epoch != w.epoch:
            raise ValueError('this environment no longer owns the world; reset again')
        return dict(game=w.game['mode'], phase=w.game['phase'], end_reason=w.game.get('end_reason'),
                    seed=w.game.get('seed'), controller=w.controller_name, scenario=copy.deepcopy(w.scenario), source=self.observation_mode,
                    time=w.time, tick=w.frame, epoch=w.epoch, metrics=copy.deepcopy(w.metrics),
                    game_state=copy.deepcopy(w.game), event_counts=dict(w.episode.counts) if w.episode else {},
                    evaluation_only=True)

    def step(self, action=None):
        if self.closed or not self.active:
            raise ValueError('reset before stepping an active environment')
        with self.world.lock:
            if self.epoch != self.world.epoch:
                raise ValueError('this environment no longer owns the world; reset again')
            if self.world.game['phase'] in ('ready','finished') or self.world.execution_mode != 'stepped':
                raise ValueError('episode ended or execution mode changed; reset before stepping')
            if self.world.paused or self.world.game['held']:
                raise ValueError('resume the environment before stepping')
            before_metrics = copy.deepcopy(self.world.metrics)
            before_events = Counter(self.world.episode.counts)
            before_time = self.world.time
            previous = copy.deepcopy(self.last_observation)
            if action is None:
                if self.controller is None:
                    raise ValueError('provide an action or configure a controller')
                try:
                    action = MotionAction.from_value(self.controller.predict(copy.deepcopy(previous)))
                    self.world.controller_intent(self.controller)
                except BaseException:
                    self.world.finish_game('controller_error')
                    self.active = False
                    raise
            action = MotionAction.from_value(action)
            self.world.observation = copy.deepcopy(previous)
            self.world.note_observation(previous, source=self.observation_mode)
            try:
                self.world.advance(action, self.ticks)
            except BaseException:
                try:
                    self.world.finish_game('simulation_error')
                finally:
                    self.active = False
                raise
            observation = self.world.observe(self.observation_mode)
            info = self.info()
            info['event_delta'] = {key:value-before_events[key] for key,value in info['event_counts'].items() if value != before_events[key]}
            info['metrics_delta'] = {key:info['metrics'][key]-before_metrics[key] for key in
                                     ('blocked_attempts','near_miss_steps','angular_change','linear_change','samples')}
            info['step_seconds'] = self.world.time-before_time
            try:
                reward = finite(self.reward_fn(previous, action, observation, info), 'reward')
            except BaseException:
                self.world.finish_game('reward_error')
                self.active = False
                raise
            self.world.metrics['reward_total'] += reward
            info['metrics']['reward_total'] = self.world.metrics['reward_total']
            ended = self.world.game['phase'] == 'finished'
            truncated = ended and self.world.game['end_reason'] == 'time_limit'
            terminated = ended and not truncated
            if self.world.episode is not None:
                self.world.episode.transition(previous, action, observation, reward, terminated, truncated, info)
            self.last_observation = copy.deepcopy(observation)
            self.active = not ended
            return observation, reward, terminated, truncated, info

    def set_detections(self, detections):
        with self.world.lock:
            if not self.active or self.epoch != self.world.epoch:
                raise ValueError('reset this environment before setting detections')
            self.world.set_detections(detections)
            if self.active:
                self.last_observation = self.world.observe(self.observation_mode)

    def close(self):
        with self.world.lock:
            if not self.closed:
                if self.epoch == self.world.epoch:
                    self.world.finish_game('environment_closed')
                self.active = False
                self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
