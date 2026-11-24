"""Learned social timing over the existing bounded referee motion repertoire."""
import math

from .contracts import MotionAction
from .controllers import RedLightController
from .friendly_policy import FriendlyPolicy


class FriendlyReferee(RedLightController):
    name = 'friendly_referee'
    model_version = 'friendly-referee-v1'
    default_game_settings = {'gaze_timing': 'friendly', 'turn_profile': 'smooth'}

    def __init__(self):
        self.policy = FriendlyPolicy()
        super().__init__()

    def reset(self, seed=None):
        super().reset(seed)
        self._forget_scene()
        self._last_seen_at = None
        self._gain_at = None
        self.cue_gain = None

    def _forget_scene(self):
        self._pace = {}
        self._tracks = []
        self._pose = None
        self.decision = None
        self.tracking_lost = False

    def predict(self, observation):
        game = observation['game']
        now = observation['time']
        dt = observation.get('control_dt', .1)
        gap = self._last_seen_at is not None and now-self._last_seen_at > dt+1e-8
        self._last_seen_at = now
        inactive = self._inactive(observation)
        if inactive or gap:
            self._forget_scene()
            self._gain_at = self.cue_gain = None
        if inactive:
            return super().predict(observation)
        rows = [child for child, present in zip(observation['children'], observation['child_mask'])
                if present and child['state'] not in ('eliminated', 'caught', 'escaped')]
        stamp = observation.get('detection_time')
        stale = observation['source'] == 'sensor' and (stamp is None or not 0 <= now-stamp <= .5)
        if stale or not any(observation['child_mask']) or (not rows and not game.get('escort')):
            self._forget_scene()
            self.tracking_lost = True
            self._gain_at = self.cue_gain = None
            self.target_id = self._turn = self._gaze_ready_since = self._last_gaze_at = None
            return MotionAction()
        self.tracking_lost = False
        if game['phase'] == 'approaching' and not game.get('escort'):
            if observation['rules'].get('gaze_timing') not in ('settled', 'friendly'):
                raise ValueError('friendly_referee requires gaze_timing=friendly or settled')
            # Only learn walking pace while walking is permitted. A frozen player
            # looking back at the referee must not be interpreted as hesitant.
            if not game['watching']:
                weight = 1.-math.exp(-dt/.45)
                for row in rows:
                    speed = math.hypot(row['relative_vx'], row['relative_vz'])
                    previous, _ = self._pace.get(row['id'], (speed, now))
                    self._pace[row['id']] = (previous + weight*(speed-previous), now)
            self._tracks = []
            for row in rows:
                pace, sampled_at = self._pace.get(row['id'], (None, now))
                self._tracks.append((row['distance'], pace if now-sampled_at < 12. else None))
        else:
            self._forget_scene()
            if self._gain_at is None or now-self._gain_at >= .4:
                self.cue_gain = self.policy.cue_gain(game['phase'], False, [(r['distance'], None) for r in rows])
                self._gain_at = now
        return super().predict(observation)

    def _gaze_dwell(self, observation):
        if self._pose != self.looking:
            self.decision = self.policy.decide('approaching', False, self._tracks)
            self.cue_gain = self.decision['cue_gain']
            self._pose = self.looking
        return self.decision['watch_seconds' if self.looking else 'away_seconds']
