"""Independent stepped environments and exact optional control transitions."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from simulator.contracts import MotionAction
from simulator.engine import World
from simulator.environment import PlayEnv


class ConstantPolicy:
    def __init__(self, action=None):
        self.action = action or MotionAction(.2, .3, False)
        self.seeds = []
        self.calls = 0
        self.fail_predict = False
        self.fail_reset = False

    def reset(self, seed=None):
        if self.fail_reset:
            raise RuntimeError('reset failed')
        self.seeds.append(seed)
        self.calls = 0

    def predict(self, observation):
        self.calls += 1
        if self.fail_predict:
            raise RuntimeError('prediction failed')
        # Controller input must be detached; a badly behaved policy cannot
        # change engine state or the stored input by editing its observation.
        observation['robot']['x'] = 12345.
        return self.action


def read_lines(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


class EnvironmentTests(unittest.TestCase):
    def test_independent_instances_reproduce_reset_and_action_sequences(self):
        for game in ('tag', 'freeze_tag', 'red_light'):
            with self.subTest(game=game), PlayEnv(game) as first, PlayEnv(game) as second:
                a, ai = first.reset(seed=17, scenario='open', count=3)
                b, bi = second.reset(seed=17, scenario='open', count=3)
                self.assertIsNot(first.world, second.world)
                self.assertEqual(a, b)
                # Epochs identify separate episode instances, not physics.
                self.assertNotEqual(ai['epoch'], bi['epoch'])
                self.assertEqual({k:v for k,v in ai.items() if k != 'epoch'},
                                 {k:v for k,v in bi.items() if k != 'epoch'})
                for action in ((.2, 0.), (.3, .4), (0., -.3), (-.1, 0.)):
                    a_result, b_result = first.step(action), second.step(action)
                    self.assertEqual(a_result[:4], b_result[:4])
                    self.assertEqual({k:v for k,v in a_result[4].items() if k != 'epoch'},
                                     {k:v for k,v in b_result[4].items() if k != 'epoch'})
                second.step((0., 0.))
                self.assertNotEqual(first.world.frame, second.world.frame)

    def test_point_one_step_is_five_ticks_and_live_clock_does_not_advance(self):
        with PlayEnv(dt=.1) as env:
            initial, _ = env.reset(seed=5)
            before = env.world.snapshot()
            for _ in range(20):
                env.world.tick(.05)
            self.assertEqual(env.world.snapshot(), before)
            observation, _, terminated, truncated, info = env.step((.2, 0.))
            self.assertEqual(observation['tick']-initial['tick'], 5)
            self.assertAlmostEqual(observation['time']-initial['time'], .1)
            self.assertAlmostEqual(info['step_seconds'], .1)
            self.assertFalse(terminated or truncated)

    def test_invalid_explicit_actions_are_atomic_and_do_not_end_episode(self):
        with PlayEnv() as env:
            env.reset()
            for action in ((float('nan'), 0.), {'linear_mps':.8}, {'unknown':1}, True):
                with self.subTest(action=action):
                    before = env.world.snapshot()
                    observation = copy.deepcopy(env.last_observation)
                    with self.assertRaises(ValueError):
                        env.step(action)
                    self.assertEqual(env.world.snapshot(), before)
                    self.assertEqual(env.last_observation, observation)
                    self.assertTrue(env.active)

    def test_invalid_scenario_reset_keeps_active_world_and_policy_state(self):
        policy = ConstantPolicy()
        with PlayEnv(controller=policy) as env:
            env.reset(seed=8, scenario='open')
            env.step()
            before = env.world.snapshot()
            previous_observation = copy.deepcopy(env.last_observation)
            with self.assertRaises(ValueError):
                env.reset(seed=9, scenario='missing-scenario')
            self.assertEqual(env.world.snapshot(), before)
            self.assertEqual(env.last_observation, previous_observation)
            self.assertEqual(policy.seeds, [8])
            self.assertEqual(policy.calls, 1)
            self.assertTrue(env.active)

    def test_controller_is_replaceable_and_reset_each_episode(self):
        policy = ConstantPolicy()
        with PlayEnv(controller=policy) as env:
            initial, _ = env.reset(seed=4)
            observation, _, _, _, _ = env.step()
            self.assertEqual(policy.seeds, [4])
            self.assertEqual(policy.calls, 1)
            self.assertNotEqual(observation['robot']['z'], initial['robot']['z'])
            self.assertLess(abs(env.world.robot['x']), 1.)
            self.assertEqual(env.world.action_input['robot']['x'], initial['robot']['x'])
            env.reset(seed=10)
            self.assertEqual(policy.seeds, [4, 10])
            self.assertEqual(policy.calls, 0)

    def test_no_record_directory_is_created_by_default(self):
        with tempfile.TemporaryDirectory() as temp, PlayEnv() as env:
            directory = Path(temp)/'not-created'
            env.world.record_root = directory
            env.reset()
            env.step((.1, 0.))
            env.close()
            self.assertFalse(directory.exists())

    def test_sensor_mode_never_fills_missing_detections_with_truth(self):
        with PlayEnv(observation_mode='sensor') as env:
            observation, info = env.reset(count=3)
            self.assertFalse(any(observation['child_mask']))
            self.assertEqual(len(env.world.children), 3)
            self.assertIsNone(observation['bounds'])
            self.assertEqual(observation['obstacles'], [])
            self.assertIsNone(observation['game']['target_id'])
            self.assertEqual(observation['source'], 'sensor')
            self.assertTrue(info['evaluation_only'])
            observation, *_ = env.step((0., 0.))
            self.assertFalse(any(observation['child_mask']))

    def test_explicit_sensor_detections_are_validated_and_used_as_input(self):
        policy = ConstantPolicy(MotionAction())
        with PlayEnv(controller=policy, observation_mode='sensor') as env:
            env.reset(count=3)
            detections = [dict(id=500, relative_x=1., relative_z=2., state='caught')]
            env.set_detections(detections)
            detections[0]['relative_x'] = 999.
            self.assertEqual(env.last_observation['children'][0]['relative_x'], 1.)
            self.assertEqual(env.last_observation['children'][0]['state'], 'unknown')
            self.assertEqual(env.last_observation['children'][0]['id'], 500)
            before = copy.deepcopy(env.last_observation)
            with self.assertRaises(ValueError):
                env.set_detections([dict(id=500, relative_x=float('nan'), relative_z=2.)])
            self.assertEqual(env.last_observation, before)
            observation, *_ = env.step()
            self.assertEqual(sum(observation['child_mask']), 1)
            self.assertEqual(env.world.action_input['children'][0]['id'], 500)

    def test_custom_reward_gets_aligned_transition_and_accumulates(self):
        calls = []
        def reward(previous, action, observation, info):
            calls.append((copy.deepcopy(previous), action, copy.deepcopy(observation), copy.deepcopy(info)))
            return 2.5
        with PlayEnv(reward_fn=reward) as env:
            initial, _ = env.reset()
            following, reward_value, _, _, info = env.step((.2, 0.))
            self.assertEqual(reward_value, 2.5)
            self.assertEqual(calls[0][0], initial)
            self.assertEqual(calls[0][1], MotionAction(.2))
            self.assertEqual(calls[0][2], following)
            self.assertAlmostEqual(calls[0][3]['step_seconds'], .1)
            self.assertEqual(info['metrics']['reward_total'], 2.5)
            self.assertEqual(env.step((.2, 0.))[-1]['metrics']['reward_total'], 5.)

    def test_custom_reward_fault_stops_motion_and_ends_episode(self):
        for reward_fn in (lambda *args: float('nan'), lambda *args: 1/0):
            with self.subTest(reward=reward_fn), PlayEnv(reward_fn=reward_fn) as env:
                env.reset()
                with self.assertRaises((ValueError, ZeroDivisionError)):
                    env.step((.4, 0.))
                self.assertFalse(env.active)
                self.assertEqual(env.world.game['end_reason'], 'reward_error')
                self.assertEqual(env.world.robot['linear'], 0.)
                self.assertEqual(env.world.robot['angular'], 0.)

    def test_controller_failure_and_invalid_prediction_stop_motion(self):
        for bad_action in (None, (.8, 0.)):
            policy = ConstantPolicy()
            with self.subTest(bad_action=bad_action), PlayEnv(controller=policy) as env:
                env.reset()
                env.step()
                self.assertGreater(env.world.robot['linear'], 0.)
                if bad_action is None:
                    policy.fail_predict = True
                else:
                    policy.action = bad_action
                with self.assertRaises((RuntimeError, ValueError)):
                    env.step()
                self.assertFalse(env.active)
                self.assertEqual(env.world.game['end_reason'], 'controller_error')
                self.assertEqual(env.world.robot['linear'], 0.)
                self.assertEqual(env.world.robot['angular'], 0.)

    def test_controller_reset_fault_leaves_new_episode_stopped(self):
        policy = ConstantPolicy()
        with PlayEnv(controller=policy) as env:
            env.reset()
            env.step()
            policy.fail_reset = True
            with self.assertRaises(RuntimeError):
                env.reset(seed=1)
            self.assertFalse(env.active)
            self.assertEqual(env.world.game['end_reason'], 'controller_error')
            self.assertEqual(env.world.robot['linear'], 0.)

    def test_manual_and_stepped_actions_use_identical_motion_integration(self):
        with PlayEnv(physics={'enabled':True}) as env:
            env.reset(seed=3, scenario='open', count=1)
            live = World()
            live.start_game('tag', False, seed=3, scenario='open', count=1, physics={'enabled':True})
            live.command(.2, .4, seconds=1., guard=False)
            for _ in range(4):
                env.step(MotionAction(.2, .4, False))
                for _ in range(5):
                    live.tick(.02)
                self.assertEqual(live.robot, env.world.robot)
                self.assertEqual(live.children, env.world.children)

    def test_manual_command_cannot_silently_override_a_recorded_step_action(self):
        with PlayEnv() as env:
            initial, _ = env.reset(scenario='open')
            try:
                env.world.command(.5, 0., seconds=1., guard=False)
            except ValueError:
                # Rejecting a live command while explicitly stepped is valid.
                pass
            observation, *_ = env.step(MotionAction())
            self.assertAlmostEqual(observation['robot']['x'], initial['robot']['x'])
            self.assertAlmostEqual(observation['robot']['z'], initial['robot']['z'])
            self.assertEqual(observation['robot']['linear'], 0.)

    def test_close_is_idempotent_and_closed_environment_cannot_restart(self):
        env = PlayEnv()
        env.reset()
        env.step((.2, 0.))
        env.close()
        env.close()
        self.assertEqual(env.world.robot['linear'], 0.)
        with self.assertRaises(ValueError): env.step((0., 0.))
        with self.assertRaises(ValueError): env.reset()


class TransitionTests(unittest.TestCase):
    def test_recorded_control_boundaries_and_short_final_step_align(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)/'episode'
            with PlayEnv(dt=.14, reward_fn=lambda *args: .75) as env:
                previous, _ = env.reset(seed=5, record=True, record_dir=directory, settings={'time_limit':1})
                returned = []
                while env.active:
                    action = MotionAction(.1, 0., False)
                    following, reward, terminated, truncated, info = env.step(action)
                    returned.append((previous, action, following, reward, terminated, truncated, info))
                    previous = following
                records = read_lines(directory/'transitions.jsonl')
                self.assertEqual(len(records), len(returned))
                self.assertEqual(len(records), 8)
                for record, (before, action, after, reward, terminated, truncated, info) in zip(records, returned):
                    self.assertEqual(record['observation'], before)
                    self.assertEqual(record['action'], action.to_dict())
                    self.assertEqual(record['next_observation'], after)
                    self.assertEqual(record['start_tick'], before['tick'])
                    self.assertEqual(record['end_tick'], after['tick'])
                    self.assertEqual(record['reward'], reward)
                    self.assertEqual(record['terminated'], terminated)
                    self.assertEqual(record['truncated'], truncated)
                    self.assertEqual(record['event_delta'], info['event_delta'])
                self.assertEqual(records[-1]['end_tick']-records[-1]['start_tick'], 1)
                self.assertAlmostEqual(records[-1]['end_time']-records[-1]['start_time'], .02)
                self.assertTrue(records[-1]['truncated'])
                self.assertFalse(records[-1]['terminated'])
                summary = json.loads((directory/'summary.json').read_text())
                self.assertEqual(summary['metrics']['reward_total'], .75*8)
                with self.assertRaises(ValueError):
                    env.step((0., 0.))


if __name__ == '__main__':
    unittest.main()
