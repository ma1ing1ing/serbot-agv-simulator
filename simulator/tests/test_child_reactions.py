"""Synthetic child response tests; no records, browser, or learned policy."""
import copy
import math
import unittest

from simulator.engine import World
from simulator import games


def scene(*, linear=0., heading=0., settings=None):
    world = World()
    world.set_count(1)
    world.start_game('tag', auto_chase=False, seed=9, settings=settings)
    child = world.children[0]
    child.update(x=0., z=0., heading=0.)
    child['profile']['reaction_time'] = 0.
    world.robot.update(x=0., z=-3.2, heading=heading, linear=linear)
    # World versions that expose actual velocities should use these values.
    world.robot.update(vx=-math.sin(heading)*linear, vz=math.cos(heading)*linear)
    return world


class ChildReactionTests(unittest.TestCase):
    def test_approaching_robot_causes_more_urgency_and_faster_escape(self):
        approaching = scene(linear=.5)
        receding = scene(linear=-.5)
        for world in (approaching, receding):
            games.advance_children(world, .02)
        a, r = approaching.children[0], receding.children[0]
        self.assertGreater(a['closing_speed'], 0.)
        self.assertLess(r['closing_speed'], 0.)
        self.assertGreater(a['pursuit_cue'], r['pursuit_cue'])
        self.assertGreater(a['perceived_threat'], r['perceived_threat'])
        self.assertGreater(a['speed'], r['speed'])
        self.assertEqual(a['motion_kind'], 'run')
        self.assertEqual(r['motion_kind'], 'walk')

    def test_pursuit_is_a_geometric_cue_not_private_target_knowledge(self):
        world = scene(linear=.5)
        world.game['target_id'] = 0
        first = games.perceive_robot(world, world.children[0])
        world.game['target_id'] = 99
        second = games.perceive_robot(world, world.children[0])
        self.assertEqual(first, second)
        self.assertGreater(first['pursuit_cue'], .9)
        # A passing robot has a weaker pursuit cue than a direct approach.
        world.robot.update(heading=math.pi/2, vx=-.5, vz=0.)
        passing = games.perceive_robot(world, world.children[0])
        self.assertLess(passing['pursuit_cue'], first['pursuit_cue'])

    def test_range_and_fov_hide_current_robot_position(self):
        world = scene(linear=.5, settings={'child_fov_degrees':120})
        child = world.children[0]
        # Child looks +Z, while the robot is behind the child.
        self.assertIsNone(games.perceive_robot(world, child))
        self.assertEqual(child['perception_source'], 'unobserved')
        child['heading'] = math.pi
        self.assertIsNotNone(games.perceive_robot(world, child))
        self.assertTrue(child['robot_visible'])
        world.game['elapsed'] = .1
        world.robot.update(x=4., z=-4.)
        child['heading'] = 0.
        memory = games.perceive_robot(world, child)
        self.assertFalse(child['robot_visible'])
        self.assertEqual(child['perception_source'], 'extrapolated_memory')
        self.assertAlmostEqual(memory['x'], 0.)
        self.assertAlmostEqual(memory['z'], -3.15)
        world.game['elapsed'] = 1.2
        self.assertIsNone(games.perceive_robot(world, child))
        self.assertEqual(child['perceived_threat'], 0.)

    def test_named_styles_and_per_child_scenario_override(self):
        for style in games.BEHAVIOR_TYPES:
            world = scene(settings={'child_behavior':style})
            child = world.children[0]
            self.assertEqual(child['behavior_type'], style)
            self.assertEqual(child['profile']['behavior_type'], style)
        world = scene(linear=.5)
        child = world.children[0]
        games.apply_behavior(child, 'playful')
        playful = games.perceive_robot(world, child)['threat']
        games.apply_behavior(child, 'cautious')
        cautious = games.perceive_robot(world, child)['threat']
        self.assertGreater(cautious, playful)
        with self.assertRaises(ValueError):
            games.apply_behavior(child, 'unknown')

    def test_seeded_profiles_and_reactions_are_reproducible(self):
        a = scene(linear=.5)
        b = scene(linear=.5)
        before = copy.deepcopy(a.children)
        for _ in range(50):
            games.advance_children(a, .02)
            games.advance_children(b, .02)
        self.assertEqual(a.children, b.children)
        self.assertNotEqual(a.children[0]['z'], before[0]['z'])

    def test_invalid_perception_settings_are_rejected(self):
        for settings in ({'child_behavior':'unknown'}, {'child_fov_degrees':0},
                         {'child_perception_range':0}, {'perception_memory':float('nan')}):
            with self.assertRaises(ValueError):
                games.options('tag', 0, settings)


if __name__ == '__main__':
    unittest.main()
