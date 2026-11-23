"""Opt-in SerBot physics preset and sensor observation block.

No network or GPU. Defaults must stay unchanged; the sensor block must not
change the world it reads.
"""
import json
import math
from pathlib import Path
import random
import tempfile
import unittest

from simulator import evaluate, serbot_sensors as S
from simulator.controllers import IdleController
from simulator.engine import World
from simulator.environment import PlayEnv
from simulator.motion import DEFAULT_PHYSICS, validate_physics
from simulator.tests import test_http_routes as routes


def still_world(**robot):
    """Stepped tag world with its only child hidden, robot placed explicitly."""
    world = World()
    world.start_game('tag', False, seed=0, count=1, execution_mode='stepped', serbot_sensors=True)
    world.children[0]['visible'] = False
    world.robot.update(robot)
    return world


class PhysicsPresetTests(unittest.TestCase):
    def test_default_physics_is_unchanged(self):
        original = dict(max_linear=.5, max_angular=3., max_acceleration=1., max_deceleration=1.5,
                        max_angular_acceleration=6., body_margin=.02, guard_distance=.2, enabled=True)
        self.assertEqual(DEFAULT_PHYSICS, original)
        for value in (None, {}):
            self.assertEqual(validate_physics(value), original)
        self.assertNotIn('preset', PlayEnv('tag').physics)

    def test_serbot_measured_values_and_overrides(self):
        physics = validate_physics('serbot_measured')
        self.assertEqual(physics['preset'], 'serbot_measured')
        self.assertAlmostEqual(physics['max_angular'], math.radians(40))
        self.assertAlmostEqual(physics['max_angular_acceleration'], math.radians(120))
        self.assertEqual((physics['max_linear'], physics['max_acceleration'], physics['max_deceleration']), (.5, .3, .3))
        self.assertEqual((physics['body_margin'], physics['guard_distance']), (.06, .125))
        self.assertEqual(validate_physics(physics), physics)
        custom = validate_physics({'preset': 'serbot_measured', 'guard_distance': .3})
        self.assertEqual(custom, dict(physics, guard_distance=.3))
        self.assertEqual({k: v for k, v in validate_physics('default').items() if k != 'preset'}, DEFAULT_PHYSICS)
        for bad in ('fast', {'preset': 3}, {'preset': 'serbot_measured', 'max_linear': 2}, 7):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_physics(bad)

    def test_preset_bounds_turn_rate_and_acceleration(self):
        env = PlayEnv('tag', physics='serbot_measured')
        try:
            env.reset(seed=0, count=1, settings={'time_limit': 10})
            _, _, _, _, info = env.step(dict(linear_mps=.5, angular_rps=3., guard=False))
            self.assertAlmostEqual(env.world.robot['linear'], .03, places=6)
            for _ in range(20):
                _, _, _, _, info = env.step(dict(linear_mps=.5, angular_rps=3., guard=False))
            self.assertLessEqual(abs(env.world.robot['angular']), math.radians(40)+1e-9)
            self.assertLessEqual(info['metrics']['max_abs_acceleration'], .3+1e-9)
            self.assertLessEqual(info['metrics']['max_abs_angular_acceleration'], math.radians(120)+1e-9)
        finally:
            env.close()

    def test_evaluate_reports_preset_only_when_requested(self):
        common = dict(seeds=(0,), controllers={'idle': IdleController}, settings={'time_limit': 1.})
        default = evaluate.run('tag', **common)
        self.assertEqual(default['physics'], DEFAULT_PHYSICS)
        self.assertNotIn('serbot_sensors', default)
        measured = evaluate.run('tag', physics='serbot_measured', serbot_sensors=True, **common)
        self.assertEqual(measured['physics']['preset'], 'serbot_measured')
        self.assertEqual(measured['serbot_sensors'], S.SCHEMA)


class SensorTests(unittest.TestCase):
    def test_disabled_by_default_and_dynamics_identical_when_enabled(self):
        plain, sensed = PlayEnv('freeze_tag'), PlayEnv('freeze_tag', serbot_sensors=True)
        try:
            a, _ = plain.reset(seed=5, settings={'time_limit': 10})
            b, _ = sensed.reset(seed=5, settings={'time_limit': 10})
            self.assertNotIn('serbot', a)
            rng = random.Random(1)
            for _ in range(30):
                self.assertEqual(a, {k: v for k, v in b.items() if k != 'serbot'})
                action = dict(linear_mps=rng.uniform(-.2, .5), angular_rps=rng.uniform(-2, 2), guard=False)
                a = plain.step(action)[0]
                b = sensed.step(action)[0]
                self.assertEqual(len(b['serbot']['lidar_m']), S.LIDAR_BEAMS)
            self.assertEqual(plain.world.robot, sensed.world.robot)
            self.assertEqual(plain.world.children, sensed.world.children)
            self.assertEqual(plain.world.metrics, sensed.world.metrics)
        finally:
            plain.close()
            sensed.close()

    def test_lidar_beam_layout_against_walls(self):
        world = still_world(x=.5, z=.25, heading=0.)
        ranges = S.lidar(world)
        self.assertEqual(len(ranges), 400)
        # Lidar centre 0.025 m behind the body centre; beam i at i*0.9 deg CCW (left).
        self.assertAlmostEqual(ranges[0], 4.5-(.25-.025), places=3)
        self.assertAlmostEqual(ranges[100], .5+5.5, places=3)
        self.assertAlmostEqual(ranges[200], .225+4.5, places=3)
        self.assertAlmostEqual(ranges[300], 5.5-.5, places=3)
        self.assertAlmostEqual(ranges[50], (4.5-.225)/math.cos(math.radians(45)), places=3)
        world.robot['heading'] = math.pi/2       # facing -X
        self.assertAlmostEqual(S.lidar(world)[0], .5+.025+5.5, places=3)

    def test_lidar_sees_children_and_reports_no_return_beyond_range(self):
        world = still_world(x=.5, z=.25, heading=0.)
        world.children[0].update(visible=True, x=.5, z=2.25)
        self.assertAlmostEqual(S.lidar(world)[0], 2.25-S.CHILD_RADIUS_M-.225, places=3)
        world.children[0]['visible'] = False
        world.bounds = (-20., 20., -20., 20.)
        self.assertTrue(all(r == 0. for r in S.lidar(world)))

    def test_ultrasonic_order_cone_and_no_echo(self):
        world = still_world(x=-5., z=3., heading=0.)
        left, front_left, front_right, right, rear_left, rear_right = S.ultrasonic(world)
        self.assertAlmostEqual(left, 5.5-5.-.165, places=3)
        self.assertAlmostEqual(front_left, 4.5-(3.-.025+.225), places=3)
        self.assertAlmostEqual(front_right, front_left, places=6)
        self.assertEqual(right, S.US_MAX_M)
        # Rear sensors face -Z; the 15 deg cone edge reaches the left wall first.
        cone = math.sin(math.radians(S.US_CONE_DEG))
        self.assertAlmostEqual(rear_left, (5.5-5.08)/cone, places=3)
        self.assertAlmostEqual(rear_right, (5.5-4.92)/cone, places=3)

    def test_exact_cast_agrees_with_marching_world_ray(self):
        world = World()
        world.start_game('tag', False, seed=3, count=8, execution_mode='stepped')
        rng = random.Random(7)
        checked = 0
        for _ in range(40):
            world.robot.update(x=rng.uniform(-4.5, 4.5), z=rng.uniform(-3.5, 3.5))
            if world.clearance(world.robot['x'], world.robot['z']) < world.radius:
                continue
            for _ in range(6):
                angle = rng.uniform(-math.pi, math.pi)
                exact = S.cast(world, world.robot['x'], world.robot['z'], angle)
                grown = S.cast(world, world.robot['x'], world.robot['z'], angle, inflate=.015)
                if exact > 7.5 or exact-grown > .05:   # beyond World.ray's 8 m, or a grazing ray
                    continue
                marched = world.ray(angle)+world.radius
                self.assertLess(abs(marched-exact), .045)
                checked += 1
        self.assertGreater(checked, 100)

    def test_frame_conventions(self):
        world = still_world(x=.5, z=.25, heading=0.)
        x, y, yaw = S.rig_pose(world)
        self.assertAlmostEqual(x, .225)
        self.assertAlmostEqual(y, -.5)
        self.assertEqual(yaw, 0.)
        self.assertEqual(S.to_sim_frame(*S.to_model_frame(1.25, -2.5)), (1.25, -2.5))
        world.robot['heading'] = math.pi/2       # left turn from +Z faces -X = model +y
        _, _, yaw = S.rig_pose(world)
        self.assertAlmostEqual(yaw, math.pi/2)

    def test_recording_config_marks_sensor_block_only_when_enabled(self):
        with tempfile.TemporaryDirectory() as temporary:
            for name, enabled in (('plain', False), ('sensed', True)):
                env = PlayEnv('tag', serbot_sensors=enabled)
                env.reset(seed=1, settings={'time_limit': 1}, record=True, record_dir=Path(temporary)/name)
                env.close()
                config = json.loads((Path(temporary)/name/'config.json').read_text(encoding='utf-8'))
                self.assertEqual(config.get('serbot_sensors'), S.SCHEMA if enabled else None)

    def test_invalid_flag_is_rejected(self):
        with self.assertRaises(ValueError):
            PlayEnv('tag', serbot_sensors='yes')


class HttpOptionTests(unittest.TestCase):
    request = routes.RouteTests.request

    def setUp(self):
        routes.RouteTests.setUp(self)

    def test_training_reset_accepts_preset_and_sensor_block(self):
        status, result = self.request('/api/training/reset', {'physics': 'serbot_measured', 'serbot_sensors': True})
        self.assertEqual(status, 200)
        self.assertEqual(self.world.physics['preset'], 'serbot_measured')
        self.assertEqual(len(result['observation']['serbot']['lidar_m']), 400)
        status, result = self.request('/api/training/step', {'action': {'linear_mps': .1}})
        self.assertEqual(status, 200)
        self.assertEqual(len(result['observation']['serbot']['ultrasonic_m']), 6)
        status, state = self.request('/api/state')
        self.assertNotIn('camera_sync', state)
        for data in ({'serbot_sensors': 'yes'}, {'physics': 'unknown'}):
            self.assertEqual(self.request('/api/training/reset', data)[0], 400)
        self.request('/api/training/close', {})

    def test_realtime_game_start_and_observation_route(self):
        self.assertEqual(self.request('/api/game/start', {'serbot_sensors': True, 'physics': 'serbot_measured'})[0], 200)
        status, observation = self.request('/api/observation?mode=sensor')
        self.assertEqual(status, 200)
        self.assertEqual(observation['serbot']['schema'], S.SCHEMA)
        self.request('/api/game/start', {})
        self.assertNotIn('serbot', self.request('/api/observation')[1])


if __name__ == '__main__':
    unittest.main()
