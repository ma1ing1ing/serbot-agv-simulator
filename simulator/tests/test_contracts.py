"""Bounded controller commands and explicit oracle/sensor observations."""
import copy
import math
from types import SimpleNamespace
import unittest

from simulator.contracts import MotionAction, make_observation
from simulator.controllers import IdleController, RuleController


def fixture():
    return SimpleNamespace(time=0., frame=0,
                           robot=dict(x=0., z=0., heading=0., linear=0., angular=0.),
                           children=[dict(id=0, x=0., z=2., heading=0., speed=0., state='free')],
                           game=dict(mode='tag', phase='chasing', elapsed=0., held=False, target_id=None),
                           rules=dict(robot_speed=.48, gaze_period=5., look_duration=1.8, catch_distance=.74),
                           bounds=(-5.5, 5.5, -4.5, 4.5), obstacles=[],
                           ray=lambda angle, max_range=4.: max_range)


class ContractTests(unittest.TestCase):
    def test_motion_action_normalizes_json_and_rejects_unsafe_inputs(self):
        self.assertEqual(MotionAction.from_value({'linear_mps':.2}).to_dict(),
                         dict(linear_mps=.2, angular_rps=0., guard=True))
        self.assertEqual(MotionAction.from_value([.2, -.3]), MotionAction(.2, -.3))
        for value in ({'linear_mps':float('nan')}, {'angular_rps':float('inf')}, {'linear_mps':True},
                      {'linear_mps':.51}, {'angular_rps':-3.1}, {'guard':1}, {'x':2}, [0, 0, 0], None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                MotionAction.from_value(value)

    def test_robot_relative_coordinates_and_velocity_follow_heading(self):
        world = fixture()
        world.robot.update(heading=math.pi/2, linear=.2)
        world.children[0].update(x=-1., z=0., heading=-math.pi/2, speed=.1)
        child = make_observation(world)['children'][0]
        self.assertAlmostEqual(child['relative_x'], 0.)
        self.assertAlmostEqual(child['relative_z'], 1.)
        self.assertAlmostEqual(child['bearing'], 0.)
        self.assertAlmostEqual(child['relative_vz'], -.1)

    def test_fixed_shape_mask_and_isolated_copy(self):
        world = fixture()
        observation = make_observation(world)
        self.assertEqual(len(observation['children']), 8)
        self.assertEqual(observation['child_mask'], [True]+[False]*7)
        self.assertEqual(observation['children'][1]['id'], -1)
        observation['robot']['x'] = 999
        observation['children'][0]['relative_z'] = 999
        observation['bounds'][0] = 999
        self.assertEqual(world.robot['x'], 0)
        self.assertEqual(world.children[0]['z'], 2)
        self.assertEqual(world.bounds[0], -5.5)

    def test_sensor_mode_never_fills_missing_detections_with_truth(self):
        world = fixture()
        observation = make_observation(world, 'sensor')
        self.assertEqual(observation['source'], 'sensor')
        self.assertFalse(any(observation['child_mask']))
        self.assertEqual(observation['obstacles'], [])
        self.assertIsNone(observation['bounds'])
        self.assertEqual(set(observation['sensors']), {'front_m', 'left_m', 'right_m', 'rear_m'})
        observed = make_observation(world, 'sensor', detections=[dict(id=12, relative_x=1., relative_z=2., state='caught')])
        self.assertEqual(observed['children'][0]['id'], 12)
        self.assertEqual(observed['children'][0]['state'], 'unknown')
        self.assertEqual(observed['child_mask'], [True]+[False]*7)

    def test_bad_detection_does_not_fall_back_to_oracle(self):
        world = fixture()
        for detections in ([{'id':1, 'relative_x':float('nan'), 'relative_z':2}],
                           [{'id':1, 'relative_x':1, 'relative_z':2}]*2,
                           [{'id':True, 'relative_x':1, 'relative_z':2}], 'bad'):
            with self.subTest(detections=detections), self.assertRaises(ValueError):
                make_observation(world, 'sensor', detections=detections)


class ControllerTests(unittest.TestCase):
    def test_rule_controller_has_no_world_side_effects_and_idle_stops(self):
        world = fixture(); before = copy.deepcopy(world.robot)
        observation = make_observation(world)
        original = copy.deepcopy(observation)
        controller = RuleController()
        action = controller.predict(observation)
        self.assertGreater(action.linear_mps, 0)
        self.assertFalse(action.guard)
        self.assertEqual(world.robot, before)
        self.assertEqual(observation, original)
        self.assertEqual(IdleController().predict(observation), MotionAction())

    def test_hysteresis_and_ineligible_children(self):
        world = fixture()
        world.children = [dict(id=0, x=0., z=1.1, heading=0., speed=0., state='free'),
                          dict(id=1, x=0., z=1., heading=0., speed=0., state='free')]
        controller = RuleController(); controller.predict(make_observation(world))
        self.assertEqual(controller.target_id, 1)
        world.children[0]['z'] = .8
        controller.predict(make_observation(world))
        self.assertEqual(controller.target_id, 1)
        world.children[1]['state'] = 'frozen'
        controller.predict(make_observation(world))
        self.assertEqual(controller.target_id, 0)
        controller.reset(seed=123)
        self.assertIsNone(controller.target_id)

    def test_red_light_turning_and_finished_state(self):
        world = fixture(); world.game.update(mode='red_light', phase='approaching', elapsed=3.)
        controller = RuleController()
        action = controller.predict(make_observation(world))
        self.assertEqual(action.linear_mps, 0.)
        self.assertGreater(abs(action.angular_rps), 0.)
        world.game['phase'] = 'finished'
        self.assertEqual(controller.predict(make_observation(world)), MotionAction())


if __name__ == '__main__':
    unittest.main()
