"""Observation-only tag policies for the paired pursuit experiments."""
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
