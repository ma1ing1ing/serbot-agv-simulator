"""Regression checks for controller intent, input provenance and world ownership."""
import unittest

from simulator.contracts import MotionAction
from simulator.controllers import RuleController
from simulator.engine import World
from simulator.environment import PlayEnv


class ControlIntegrationTests(unittest.TestCase):
    def test_configured_stepped_controller_propagates_intent_and_identity(self):
        controller = RuleController()
        with PlayEnv(controller=controller) as env:
            env.reset(seed=2)
            _, _, _, _, info = env.step()
            self.assertIsNotNone(controller.target_id)
            self.assertEqual(env.world.game['target_id'], controller.target_id)
            self.assertEqual(env.world.controller_name, controller.name)
            self.assertEqual(env.world.episode.config['controller'], controller.name)
            self.assertEqual(info['controller'], controller.name)
            self.assertEqual(env.world.episode.counts['target_change'], 1)
            self.assertEqual(info['event_delta']['target_change'], 1)

    def test_completed_live_episode_metrics_do_not_keep_accumulating(self):
        world = World()
        world.start_game(settings={'time_limit':1})
        for _ in range(50):world.tick(.02)
        metrics = dict(world.metrics)
        for _ in range(50):world.tick(.02)
        self.assertEqual(world.metrics,metrics)

    def test_manual_takeover_replaces_oracle_input_with_explicit_input_or_none(self):
        for provide_external in (False, True):
            with self.subTest(provide_external=provide_external):
                world = World()
                world.start_game()
                world.tick(.02)
                world.tick(.02)
                self.assertEqual(world.action_input['source'], 'oracle')
                self.assertLess(world.action_received_tick, world.frame)
                if provide_external:
                    world.note_observation({'frame_id':7}, source='my_model')
                world.command(.1, 0., .2)
                self.assertEqual(world.action_received_tick, world.frame)
                self.assertEqual(world.controller_name, 'external_or_manual')
                if provide_external:
                    self.assertEqual(world.action_input['source'], 'my_model')
                    self.assertEqual(world.action_input['value']['frame_id'], 7)
                else:
                    self.assertIsNone(world.action_input)
                world.finish_game()

    def test_stale_shared_world_owner_cannot_step_change_detections_or_close_new_game(self):
        world = World()
        first, second = PlayEnv(world=world), PlayEnv(world=world)
        try:
            first.reset(seed=1)
            second.reset(seed=2)
            epoch, tick = world.epoch, world.frame
            with self.assertRaises(ValueError):
                first.step(MotionAction())
            with self.assertRaises(ValueError):
                first.set_detections([])
            with self.assertRaises(ValueError):
                first.info()
            first.close()
            self.assertEqual(world.epoch, epoch)
            self.assertEqual(world.frame, tick)
            self.assertEqual(world.game['phase'], 'chasing')
            self.assertIsNone(world.game['end_reason'])
            second.step(MotionAction())
            self.assertGreater(world.frame, tick)
        finally:
            first.close()
            second.close()


if __name__ == '__main__':
    unittest.main()
