"""Common motion dynamics, braking and swept geometric collision prevention."""
import math
import unittest

from simulator.contracts import MotionAction
from simulator.motion import integrate, validate_physics


class MotionWorld:
    radius = .39

    def __init__(self, obstacle=None):
        self.robot = dict(x=0., z=0., heading=0., linear=0., angular=0.)
        self.distance = 0.
        self.obstacle = obstacle
        self.contacts = []
        self.range = 4.

    def clearance(self, x, z):
        free = min(5.5-abs(x), 4.5-abs(z))
        if self.obstacle is not None:
            free = min(free, math.hypot(x-self.obstacle[0], z-self.obstacle[1])-.22)
        return free

    def ray(self, angle):
        return self.range

    def contact(self, actor, target, blocked):
        self.contacts.append((actor, target, blocked))


class MotionTests(unittest.TestCase):
    def test_acceleration_and_distance_from_rest(self):
        world = MotionWorld()
        integrate(world, MotionAction(.5, guard=False), .2)
        self.assertAlmostEqual(world.robot['linear'], .2)
        self.assertAlmostEqual(world.robot['z'], .02)
        self.assertAlmostEqual(world.distance, .02)

    def test_zero_action_brakes_without_teleporting_velocity_to_zero(self):
        world = MotionWorld(); world.robot['linear'] = .4
        integrate(world, MotionAction(guard=False), .1)
        self.assertAlmostEqual(world.robot['linear'], .25)
        self.assertAlmostEqual(world.robot['z'], .0325)

    def test_reversal_first_uses_deceleration(self):
        world = MotionWorld(); world.robot['linear'] = .3
        integrate(world, MotionAction(-.5, guard=False), .02)
        self.assertAlmostEqual(world.robot['linear'], .27)
        self.assertGreater(world.robot['z'], 0)

    def test_angular_acceleration_and_sign(self):
        world = MotionWorld()
        integrate(world, MotionAction(0., 3., False), .1)
        self.assertAlmostEqual(world.robot['angular'], .6)
        self.assertAlmostEqual(world.robot['heading'], .03)
        integrate(world, MotionAction(.5, 3., False), .2)
        self.assertLess(world.robot['x'], 0)

    def test_fixed_substeps_match_one_long_integration(self):
        first, second = MotionWorld(), MotionWorld()
        action = MotionAction(.3, .8, False)
        integrate(first, action, .2)
        for _ in range(10): integrate(second, action, .02)
        for key in first.robot:
            self.assertAlmostEqual(first.robot[key], second.robot[key])

    def test_collision_prevention_cannot_tunnel_through_child(self):
        world = MotionWorld(obstacle=(0., 1.))
        self.assertEqual(integrate(world, MotionAction(.5, guard=False), 3.), 'collision')
        self.assertGreaterEqual(1.-world.robot['z'], world.radius+.22+.02-1e-10)
        self.assertEqual(world.robot['linear'], 0)
        self.assertTrue(world.contacts[-1][-1])

    def test_guard_is_distinct_from_body_collision(self):
        world = MotionWorld(); world.range = .1
        self.assertEqual(integrate(world, MotionAction(.5), .02), 'guard')
        self.assertEqual(world.robot['z'], 0)
        self.assertFalse(world.contacts[-1][-1])

    def test_disabled_dynamics_retains_ideal_motion_and_limits_still_apply(self):
        world = MotionWorld()
        integrate(world, MotionAction(.2, guard=False), 1., {'enabled':False})
        self.assertAlmostEqual(world.robot['z'], .2)
        world = MotionWorld()
        integrate(world, MotionAction(.5, guard=False), 1., {'enabled':False, 'max_linear':.1})
        self.assertAlmostEqual(world.robot['z'], .1)

    def test_invalid_dynamics_rejected_before_moving(self):
        for settings in ({'max_acceleration':float('inf')}, {'enabled':1}, {'max_linear':1}, {'unknown':1}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                validate_physics(settings)
        world = MotionWorld()
        for dt in (0., -.1, float('nan'), True):
            with self.subTest(dt=dt), self.assertRaises(ValueError):
                integrate(world, MotionAction(.2), dt)
        self.assertEqual(world.robot['z'], 0)


if __name__ == '__main__':
    unittest.main()
