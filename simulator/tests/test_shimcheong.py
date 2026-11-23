"""simcheongi controller wrapper with a fake planner.

No network, GPU or simcheongi package: these tests check the wrapper's
decision cadence, inputs and follower, not the driving model.
"""
import importlib.util
import math
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

from simulator.contracts import MotionAction
from simulator.environment import PlayEnv
from simulator.examples import controller_client
from simulator.examples.shimcheong_controller import BlankFrames, ShimcheongController


class RoutePlanner:
    """Fake planner: 50 points along the supplied route at 0.25 m/s."""
    model_version = 'fake-route-planner'

    def __init__(self):
        self.calls = []
        self.resets = []

    def reset(self, session=None):
        self.resets.append(session)

    def plan(self, frames, lidar, ego_history, route, *, ultrasonic=None, session='default'):
        self.calls.append(dict(frames=list(frames), lidar=list(lidar), history=[tuple(r) for r in ego_history],
                               route=list(route), ultrasonic=list(ultrasonic), session=session))
        (x0, y0), (x1, y1) = route[0], route[-1]
        d = max(math.hypot(x1-x0, y1-y0), 1e-9)
        ux, uy = (x1-x0)/d, (y1-y0)/d
        points = [(x0+ux*min(d, .025*k), y0+uy*min(d, .025*k), math.atan2(uy, ux)) for k in range(1, 51)]
        return SimpleNamespace(trajectory_world=points, speed_hint=.25, latency_s=.001)



class ShimcheongControllerTests(unittest.TestCase):
    def make(self, **options):
        planner = RoutePlanner()
        return planner, ShimcheongController(planner, frame_source=lambda observation: observation['tick'], **options)

    def test_missing_package_gives_install_hint(self):
        controller = ShimcheongController(frame_source=lambda observation: None)
        with mock.patch.dict(sys.modules, {'simcheongi': None}):
            with self.assertRaisesRegex(ImportError, 'SHIMCHEONG.md'):
                controller.reset(0)

    def test_requires_explicit_sensor_block_and_frame_source(self):
        _, controller = self.make()
        controller.reset(0)
        env = PlayEnv('tag')
        try:
            observation, _ = env.reset(seed=0)
            with self.assertRaisesRegex(ValueError, 'serbot_sensors'):
                controller.predict(observation)
        finally:
            env.close()
        with self.assertRaises(ValueError):
            ShimcheongController(RoutePlanner(), frame_source=None)

    def test_decision_cadence_history_frames_and_inputs(self):
        planner, controller = self.make()
        env = PlayEnv('tag', controller=controller, physics='serbot_measured', serbot_sensors=True)
        try:
            env.reset(seed=2, count=3, settings={'time_limit': 30})
            for _ in range(16):
                env.step()
            game_target = env.world.game['target_id']
        finally:
            env.close()
        self.assertEqual(planner.resets, ['sim'])
        self.assertEqual(len(planner.calls), 4)              # t = 0, 0.5, 1.0, 1.5 at dt 0.1
        first, last = planner.calls[0], planner.calls[-1]
        self.assertEqual(first['frames'], [0, 0, 0, 0])
        self.assertEqual(last['frames'], [0, 25, 50, 75])    # t0-1.5 / -1.0 / -0.5 / 0 s ticks
        times = [row[0] for row in last['history']]
        self.assertEqual(len(times), 16)
        self.assertAlmostEqual(times[-1], 1.5)
        self.assertTrue(all(abs(b-a-.1) < 1e-6 for a, b in zip(times, times[1:])))
        self.assertEqual((len(last['lidar']), len(last['ultrasonic'])), (400, 6))
        self.assertEqual(last['route'][0], last['history'][-1][1:3])
        self.assertIsNotNone(controller.target_id)
        self.assertEqual(game_target, controller.target_id)

    def test_history_reaches_three_seconds_and_stays_bounded(self):
        planner, controller = self.make()
        env = PlayEnv('tag', controller=controller, physics='serbot_measured', serbot_sensors=True)
        try:
            env.reset(seed=4, count=2, settings={'time_limit': 30})
            for _ in range(61):
                env.step()
        finally:
            env.close()
        self.assertEqual(len(planner.calls[-1]['history']), 41)
        self.assertGreaterEqual(len(planner.calls[6]['history']), 31)

    def test_follower_speed_turn_and_stop_rules(self):
        _, controller = self.make()
        controller.reset(0)
        w_max = math.radians(40)

        def follow(path, speed=.25):
            controller.plan = dict(path=[(0., 0.)]+path, cursor=0., speed=speed)
            return controller._follow((0., 0., 0.))
        straight = follow([(.1*k, 0.) for k in range(1, 20)])
        self.assertAlmostEqual(straight.linear_mps, .25)
        self.assertAlmostEqual(straight.angular_rps, 0.)
        left = follow([(.3, .3), (.3, .6)])
        self.assertGreater(left.angular_rps, 0.)
        self.assertLessEqual(abs(left.angular_rps), w_max+1e-9)
        behind = follow([(-.5, -.1), (-1., -.2)])
        self.assertEqual(behind.linear_mps, 0.)
        self.assertAlmostEqual(behind.angular_rps, -w_max)
        for action in (follow([(.1, 0.)]), follow([(1., 0.)], speed=0.)):
            self.assertEqual((action.linear_mps, action.angular_rps), (0., 0.))
        self.assertTrue(straight.guard)

    def test_inactive_and_red_light_gaze_are_bounded(self):
        _, controller = self.make()
        env = PlayEnv('red_light', controller=controller, physics='serbot_measured', serbot_sensors=True)
        try:
            env.reset(seed=0, settings={'time_limit': 10})
            for _ in range(30):
                env.step()
                self.assertLessEqual(abs(env.world.requested_action['angular_rps']), math.radians(40)+1e-9)
                self.assertEqual(env.world.requested_action['linear_mps'], 0.)
        finally:
            env.close()
        observation = dict(env.last_observation)
        observation['game'] = dict(observation['game'], held=True)
        self.assertEqual(controller.predict(observation), MotionAction())

    def test_route_planner_drives_toward_children_within_limits(self):
        planner, controller = self.make()
        env = PlayEnv('tag', controller=controller, physics='serbot_measured', serbot_sensors=True)
        try:
            observation, _ = env.reset(seed=3, count=2, settings={'time_limit': 10, 'catch_distance': .85})
            start = min(c['distance'] for c, m in zip(observation['children'], observation['child_mask']) if m)
            done, peak = False, 0.
            while not done:
                _, _, terminated, truncated, info = env.step()
                peak = max(peak, abs(env.world.robot['angular']))
                done = terminated or truncated
        finally:
            env.close()
        self.assertEqual(controller.decisions, len(planner.calls))
        self.assertGreater(env.world.distance, 1.)
        self.assertLess(info['metrics']['min_distance'], start)
        self.assertLessEqual(peak, math.radians(40)+1e-9)

    def test_factory_is_lazy_and_loadable_by_name(self):
        controller = controller_client.load_controller('simulator.examples.shimcheong_controller:create_controller')
        self.assertIsInstance(controller, ShimcheongController)
        self.assertIsNone(controller._policy)

    @unittest.skipUnless(importlib.util.find_spec('numpy'), 'numpy not installed')
    def test_blank_frames_have_model_size(self):
        frame = BlankFrames()({})
        self.assertEqual((frame.shape, str(frame.dtype)), ((720, 1280, 3), 'uint8'))


if __name__ == '__main__':
    unittest.main()
