"""Portable SerBot in-game timing model. Inference needs only the standard library."""
import json
import math
from pathlib import Path
from statistics import median

MODEL_PATH = Path(__file__).with_name('models') / 'friendly_referee_v1.json'
FEATURES = ('count', 'nearest', 'middle_distance', 'farthest', 'near_fraction',
            'slow_pace', 'middle_pace', 'known_pace_fraction')
# Seconds after a turn settles, and relative gain for the two musical game signals.
LIMITS = ((2.4, 4.6), (1.2, 2.6), (.65, 1.))
FIXED = (3.2, 1.8, 1.)


def features(tracks):
    """One (distance_m, last_go_speed_mps or None) per visible player."""
    if len(tracks) > 8:
        raise ValueError('expected at most eight tracks')
    if not tracks:
        return None
    distances, speeds = [], []
    for distance, speed in tracks:
        if not math.isfinite(distance) or distance < 0:
            raise ValueError('distance must be finite and nonnegative')
        distances.append(min(distance, 10.))
        if speed is not None:
            if not math.isfinite(speed) or speed < 0:
                raise ValueError('speed must be finite and nonnegative')
            speeds.append(min(speed, 1.6))
    speeds.sort()
    n = len(distances)
    return [n / 8., min(distances) / 10., median(distances) / 10., max(distances) / 10.,
            sum(d < 2. for d in distances) / n,
            speeds[(len(speeds)-1)//4] / 1.6 if speeds else .3,
            median(speeds) / 1.6 if speeds else .3, len(speeds) / n]


class FriendlyPolicy:
    def __init__(self, model_path=MODEL_PATH):
        model = json.loads(Path(model_path).read_text(encoding='utf-8'))
        if (model['format'] != 'serbot-friendly-1' or tuple(model['features']) != FEATURES
                or model['limits'] != [list(pair) for pair in LIMITS]):
            raise ValueError('incompatible friendly referee model')
        self.layers = model['layers']

    def decide(self, phase, held, tracks):
        """Call once upon settling. A missing decision means stay quiet and still."""
        if held or phase != 'approaching':
            return None
        return self._predict(tracks)

    def cue_gain(self, phase, held, tracks):
        """The acoustic head depends on listener distance in either active phase."""
        if held or phase not in ('approaching', 'escaping'):
            return None
        decision = self._predict(tracks)
        return decision['cue_gain'] if decision else None

    def _predict(self, tracks):
        values = features(tracks)
        if values is None:
            return None
        for index, layer in enumerate(self.layers):
            values = [sum(x*w for x, w in zip(values, row)) + b
                      for row, b in zip(layer['weight'], layer['bias'])]
            if index < len(self.layers)-1:
                values = [max(0., x) for x in values]
        away, watch, gain = [lo+(hi-lo)*min(1., max(0., x))
                             for x, (lo, hi) in zip(values, LIMITS)]
        return dict(away_seconds=away, watch_seconds=watch, cue_gain=gain)
