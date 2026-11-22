"""Fixed game opponents: legal targets, gaze settling and episode reset."""
import copy
import math
import unittest

from simulator import games
from simulator.contracts import MotionAction
from simulator.controllers import (
    FreezeTagController, RedLightController, RuleController, TagController,
)
from simulator.engine import World
from simulator.environment import PlayEnv
from simulator.examples.tag_pursuit import LeadTagController, SteadyTagController


CONTROLLERS = (
    ('tag', TagController),
    ('freeze_tag', FreezeTagController),
    ('red_light', RedLightController),
)


def world_for(mode, count=3):
    world = World()
    world.start_game(mode, auto_chase=False, count=count, seed=42)
    world.robot.update(x=0., z=0., heading=0., linear=0., angular=0.)
    for i, child in enumerate(world.children):
        child.update(x=0., z=.7+i*1.3, state='free', speed=0., moving=False)
    return world


class GameControllerTests(unittest.TestCase):
    def test_capture_or_freeze_changes_target_and_thawed_child_is_eligible_again(self):
        for mode, factory in CONTROLLERS[:2]:
            with self.subTest(mode=mode):
                world = world_for(mode)
                controller = factory()
                controller.predict(world.observe())
                self.assertEqual(controller.target_id, 0)
                world.check_touch()
                self.assertEqual(world.children[0]['state'],
                                 'caught' if mode == 'tag' else 'frozen')
                controller.predict(world.observe())
                self.assertEqual(controller.target_id, 1)
                if mode == 'freeze_tag':
                    world.children[1]['z'] = 1.3
                    games.rescue(world, world.children[1], world.rules['rescue_hold'])
                    self.assertEqual(world.children[0]['state'], 'free')
                    controller.predict(world.observe())
                    self.assertEqual(controller.target_id, 0)

    def test_ineligible_states_and_masked_slots_are_never_chased(self):
        for mode, factory in CONTROLLERS:
            with self.subTest(mode=mode):
                world = world_for(mode)
                if mode == 'red_light':
                    world.game['phase'] = 'escaping'
                observation = world.observe()
                observation['children'][0]['state'] = 'escaping' if mode != 'red_light' else 'free'
                observation['children'][1]['state'] = 'caught'
                observation['children'][2]['state'] = 'frozen'
                controller = factory()
                self.assertEqual(controller.predict(observation), MotionAction())
                self.assertIsNone(controller.target_id)
                observation['children'][0]['state'] = 'escaping' if mode == 'red_light' else 'free'
                observation['child_mask'][0] = False
                self.assertEqual(controller.predict(observation), MotionAction())
                self.assertIsNone(controller.target_id)

    def test_explicit_controller_rejects_another_game(self):
        for mode, factory in CONTROLLERS:
            wrong_mode = 'freeze_tag' if mode == 'tag' else 'tag'
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                factory().predict(world_for(wrong_mode).observe())

    def test_inactive_games_stop_and_clear_target(self):
        for mode, factory in CONTROLLERS:
            world = world_for(mode)
            if mode == 'red_light':
                world.game['phase'] = 'escaping'
                for child in world.children:
                    child['state'] = 'escaping'
            controller = factory()
            for inactive in ('held', 'ready', 'finished'):
                with self.subTest(mode=mode, inactive=inactive):
                    observation = world.observe()
                    controller.predict(observation)
                    self.assertIsNotNone(controller.target_id)
                    if inactive == 'held':
                        observation['game']['held'] = True
                    else:
                        observation['game']['phase'] = inactive
                    self.assertEqual(controller.predict(observation), MotionAction())
                    self.assertIsNone(controller.target_id)

    def test_red_light_gaze_schedule_turns_in_place_and_changes_direction(self):
        world = world_for('red_light')
        world.robot['heading'] = .5
        controller = RedLightController()
        looking = controller.predict(world.observe())
        self.assertEqual(looking.linear_mps, 0.)
        self.assertLess(looking.angular_rps, 0.)
        world.game['elapsed'] = world.rules['look_duration']+.1
        away = controller.predict(world.observe())
        self.assertEqual(away.linear_mps, 0.)
        self.assertGreater(away.angular_rps, 0.)
        world.game['elapsed'] = world.rules['gaze_period']+.1
        self.assertLess(controller.predict(world.observe()).angular_rps, 0.)

    def test_red_light_gaze_settles_with_live_and_training_time_steps(self):
        # Observe the away plateau: the old error/.02 control kept oscillating
        # around pi even when the target heading had stopped changing.
        for dt in (.02, .1):
            with self.subTest(dt=dt), PlayEnv(game='red_light', controller=RedLightController(), dt=dt) as env:
                env.reset(seed=42, settings={'time_limit':6})
                for child in env.world.children:
                    child['mode'] = 'still'
                for _ in range(round(4.8/dt)):
                    env.step()
                robot = env.world.robot
                error = (math.pi-robot['heading']+math.pi) % (2*math.pi)-math.pi
                self.assertLess(abs(error), .02)
                self.assertLess(abs(robot['angular']), .05)
                self.assertAlmostEqual(robot['x'], 0.)
                self.assertAlmostEqual(robot['z'], -3.35)

    def test_red_light_touch_switches_from_gaze_to_chase_and_skips_terminal_children(self):
        controller = RedLightController()
        with PlayEnv(game='red_light', controller=controller) as env:
            env.reset(seed=42, count=2, settings={'time_limit':10})
            world = env.world
            self.assertEqual(controller.predict(world.observe()).linear_mps, 0.)
            world.children[0].update(x=world.robot['x'], z=world.robot['z']+.7)
            world.children[1].update(x=world.robot['x'], z=world.robot['z']+2.)
            world.check_touch()
            self.assertEqual(world.game['phase'], 'escaping')
            action = controller.predict(world.observe())
            self.assertEqual(controller.target_id, 0)
            self.assertGreater(action.linear_mps, 0.)
            env.last_observation = world.observe()
            env.step()
            self.assertGreater(world.robot['z'], -3.35)
            world.children[0]['state'] = 'caught'
            controller.predict(world.observe())
            self.assertEqual(controller.target_id, 1)
            world.children[1]['state'] = 'escaped'
            self.assertEqual(controller.predict(world.observe()), MotionAction())
            self.assertIsNone(controller.target_id)

    def test_dispatcher_matches_explicit_controller_without_mutating_observation(self):
        for mode, factory in CONTROLLERS:
            with self.subTest(mode=mode):
                world = world_for(mode)
                explicit, dispatcher = factory(), RuleController()
                for elapsed in (0., 2., 5.2):
                    world.game['elapsed'] = elapsed
                    observation = world.observe()
                    original = copy.deepcopy(observation)
                    self.assertEqual(explicit.predict(observation), dispatcher.predict(observation))
                    self.assertEqual(explicit.target_id, dispatcher.target_id)
                    self.assertEqual(observation, original)
                self.assertIsInstance(explicit.model_version, str)
                self.assertTrue(explicit.model_version)

    def test_reset_and_same_episode_inputs_reproduce_commands(self):
        for mode, factory in CONTROLLERS:
            controller = factory()
            traces = []
            for _ in range(2):
                with PlayEnv(game=mode, controller=controller) as env:
                    env.reset(seed=42, settings={'time_limit':2})
                    self.assertIsNone(controller.target_id)
                    trace = []
                    for _ in range(10):
                        env.step()
                        trace.append((copy.deepcopy(env.world.requested_action),
                                      controller.target_id, dict(env.world.robot)))
                    traces.append(trace)
            with self.subTest(mode=mode):
                self.assertEqual(traces[0], traces[1])


class TagExperimentTests(unittest.TestCase):
    def test_switch_margin_keeps_current_target_until_another_is_closer(self):
        world = world_for('tag', count=2)
        baseline, steady = TagController(), SteadyTagController()
        for controller in (baseline, steady):
            controller.predict(world.observe())
            self.assertEqual(controller.target_id, 0)
        world.children[0]['z'] = 2.5  # Target 1, at 2.0 m, is 0.5 m closer.
        for controller, expected in ((baseline, 1), (steady, 0)):
            controller.predict(world.observe())
            self.assertEqual(controller.target_id, expected)
        world.children[0]['z'] = 3.
        steady.predict(world.observe())
        self.assertEqual(steady.target_id, 1)

    def test_lead_uses_relative_velocity_without_changing_target_priority(self):
        world = world_for('tag', count=2)
        world.children[0].update(x=0., z=2., vx=1., vz=0.)
        world.children[1].update(x=-2.03, z=0., vx=0., vz=0.)
        baseline, lead = TagController(), LeadTagController()
        obs = world.observe()
        self.assertEqual(baseline.predict(obs).angular_rps, 0.)
        expected_turn = 3 * math.atan2(-.6, 2.)
        self.assertAlmostEqual(lead.predict(obs).angular_rps, expected_turn)
        self.assertEqual(lead.target_id, 0)
        self.assertEqual(lead.target_id, baseline.target_id)


if __name__ == '__main__':
    unittest.main()
