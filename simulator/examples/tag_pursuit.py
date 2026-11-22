"""Observation-only tag policies for the paired pursuit experiments."""
from collections import deque
import math

from simulator.controllers import TagController


class SteadyTagController(TagController):
    """Keep the current target unless another is at least 0.9 m closer."""
    name = 'tag_steady'
    model_version = 'steady-0.9-v1'
    target_margin = .9


class LeadTagController(TagController):
    """Steer towards the relative position extrapolated 0.6 seconds ahead."""
    name = 'tag_lead'
    model_version = 'relative-lead-0.6-v1'

    @staticmethod
    def _target_bearing(target):
        right = target['relative_x'] + .6 * target['relative_vx']
        forward = target['relative_z'] + .6 * target['relative_vz']
        return math.atan2(-right, forward)


class ClosingTagController(TagController):
    """Prefer a nearby, closing target among challengers that clear the rule margin."""
    name = 'tag_closing'
    model_version = 'closing-1s-band-0.3-v1'
    nearby_band = .3

    def reset(self, seed=None):
        super().reset(seed)
        self.history = deque()

    def _select_target(self, candidates, observation):
        baseline = super()._select_target(candidates, observation)
        now = observation['time']
        distances = {c['id']: c['distance'] for c in candidates}
        # Keep the two observations bracketing the start of the last second.
        if self.history and self.history[-1][0] == now:
            self.history.pop()
        self.history.append((now, distances))
        cutoff = round(now - 1., 9)
        while len(self.history) >= 2 and self.history[1][0] <= cutoff:
            self.history.popleft()
        start, before = self.history[0]
        if start > cutoff or baseline['id'] == self.target_id:
            return baseline
        end, after = self.history[1]
        weight = (cutoff - start) / (end - start)
        current_limit = distances.get(self.target_id, math.inf) - self.target_margin
        nearby_limit = baseline['distance'] + self.nearby_band
        closing = []
        for child in candidates:
            ident, distance = child['id'], child['distance']
            if (ident == self.target_id or distance > current_limit or distance > nearby_limit
                    or ident not in before or ident not in after):
                continue
            gain = before[ident] + weight * (after[ident] - before[ident]) - distance
            if gain > 0.:
                closing.append((gain, -distance, -ident, child))
        return max(closing)[-1] if closing else baseline
