import math
import tempfile
import unittest
import wave
from array import array
from pathlib import Path

from simulator.contracts import MotionAction
from simulator.engine import World
from simulator.examples.friendly_jetson import scaled_wav
from simulator.friendly_controller import FriendlyReferee
from simulator.friendly_policy import FriendlyPolicy, features


class FriendlyTests(unittest.TestCase):
    def test_trained_preferences_and_inactive_phases(self):
        policy = FriendlyPolicy()
        slow = policy.decide('approaching', False, [(5., .25)]*3)
        quick = policy.decide('approaching', False, [(5., .9)]*3)
        close = policy.decide('approaching', False, [(1.2, .7)]*4)
        self.assertGreater(slow['away_seconds'], quick['away_seconds'] + .5)
        self.assertLess(close['cue_gain'], slow['cue_gain'])
        self.assertLess(quick['watch_seconds'], close['watch_seconds'])
        for phase, held, rows in [('ready', False, [(2., .4)]), ('finished', False, [(2., .4)]),
                                  ('approaching', True, [(2., .4)]), ('approaching', False, [])]:
            self.assertIsNone(policy.decide(phase, held, rows))
            self.assertIsNone(policy.cue_gain(phase, held, rows))
        self.assertIsNotNone(policy.cue_gain('escaping', False, [(2., None)]))
        self.assertIsNone(policy.decide('escaping', False, [(2., None)]))
        with self.assertRaises(ValueError):
            features([(math.nan, None)])

    def test_live_mode_latches_one_decision_and_clears_after_finish(self):
        world = World()
        world.start_game('red_light', count=3, seed=78, settings={'gaze_timing':'friendly'})
        self.assertIsInstance(world.controller, FriendlyReferee)
        self.assertEqual(world.rules['turn_profile'], 'smooth')
        world.tick(.02)
        first = world.game['friendly_decision']
        self.assertIsNotNone(first)
        for _ in range(8):
            world.tick(.02)
            self.assertIs(world.game['friendly_decision'], first)
        turns = set()
        for _ in range(800):
            world.tick(.02)
            turns.add(world.game['watching'])
        self.assertEqual(turns, {True, False})
        world.finish_game()
        self.assertNotIn('friendly_cue_gain', world.game)
        self.assertNotIn('friendly_decision', world.game)
        self.assertEqual(world.controller.predict(world.observe()), MotionAction())
        world.start_game('tag')
        self.assertNotIsInstance(world.controller, FriendlyReferee)

    def test_lost_tracks_stop_and_fresh_tracks_resume(self):
        world = World()
        world.start_game('red_light', settings={'gaze_timing': 'friendly'}, observation_mode='sensor')
        for _ in range(4):
            world.tick(.02)
        self.assertTrue(world.game['tracking_lost'])
        world.set_detections([dict(id=0, relative_x=0., relative_z=2.)])
        world.tick(.02)
        self.assertFalse(world.game['tracking_lost'])
        self.assertIsNotNone(world.game['friendly_decision'])
        for _ in range(27):
            world.tick(.02)
        self.assertTrue(world.game['tracking_lost'])
        self.assertIsNone(world.game['friendly_decision'])
        self.assertEqual(world.requested_action, MotionAction().to_dict())

    def test_robot_cue_scales_amplitude_and_preserves_duration(self):
        cue = Path(__file__).resolve().parents[1] / 'static/sounds/chant.wav'
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'soft.wav'
            scaled_wav(cue, output, .7)
            with wave.open(str(cue)) as a, wave.open(str(output)) as b:
                self.assertEqual(a.getparams(), b.getparams())
                raw = array('h', a.readframes(a.getnframes()))
                soft = array('h', b.readframes(b.getnframes()))
                self.assertAlmostEqual(max(soft)/max(raw), .7, places=3)
