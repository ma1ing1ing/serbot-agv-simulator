import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from simulator.evaluate import load_controller, outcome, run


class TrackingIdle:
    def __init__(self):
        self.seed = None
        self.ticks = []

    def reset(self, seed=None):
        self.seed = seed
        self.ticks = []

    def predict(self, observation):
        self.ticks.append(observation['tick'])
        return dict(linear_mps=0., angular_rps=0.)


class EvaluationTests(unittest.TestCase):
    def test_same_suite_uses_fresh_controllers_and_optional_output_only(self):
        made = []
        def factory():
            policy = TrackingIdle()
            made.append(policy)
            return policy
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'evaluation.json'
            report = run(scenarios=('standard', 'dense'), seeds=(4, 9), settings={'time_limit':1},
                         controllers={'test':factory}, output=output)
            self.assertEqual(len(report['rows']), 4)
            self.assertEqual(len(made), 4)
            self.assertEqual([p.seed for p in made], [4, 9, 4, 9])
            self.assertTrue(all(p.ticks == sorted(set(p.ticks)) for p in made))
            self.assertTrue(all(p.ticks[0] == 0 for p in made))
            self.assertTrue(all(row['end_reason'] == 'time_limit' for row in report['rows']))
            self.assertFalse(report['recording'])
            self.assertEqual(json.loads(output.read_text())['aggregate'][0]['episodes'], 4)
            self.assertEqual([p.name for p in Path(temp).iterdir()], ['evaluation.json'])
            with self.assertRaises(ValueError):
                run(scenarios=('standard',), seeds=(0,), settings={'time_limit':1}, output=output)

    def test_defaults_compare_both_baselines_in_one_open_room(self):
        report = run(seeds=(0,), count=1, settings={'time_limit':1})
        self.assertEqual(report['scenarios'], ['open'])
        self.assertEqual(report['scenario_group'], 'open_room')
        self.assertEqual({row['controller'] for row in report['rows']}, {'rule', 'idle'})
        self.assertEqual(len(report['rows']), 2)
        self.assertTrue(all(row['scenario'] == 'open' for row in report['rows']))
        self.assertEqual(len(report['aggregate']), 2)

    def test_outcomes_are_game_specific_and_not_a_cross_game_score(self):
        def world(mode, reason, **extra):
            game = dict(mode=mode, end_reason=reason, caught_ids=[], frozen_ids=[],
                        eliminated_ids=[], escaped_ids=[], touched_by=None, **extra)
            return SimpleNamespace(game=game, children=[{}, {}], episode=None)
        tag = world('tag', 'time_limit'); tag.game['caught_ids'] = [0]
        freeze = world('freeze_tag', 'all_frozen'); freeze.game['frozen_ids'] = [0, 1]
        red = world('red_light', 'pursuit_complete'); red.game.update(caught_ids=[0], escaped_ids=[1])
        self.assertEqual(outcome(tag)['score_definition'], 'caught_fraction')
        self.assertEqual(outcome(tag)['task_score'], .5)
        self.assertTrue(outcome(freeze)['task_success'])
        self.assertFalse(outcome(red)['task_success'])
        self.assertEqual(outcome(red)['escaped'], 1)

    def test_custom_loader_and_invalid_inputs(self):
        self.assertTrue(callable(load_controller('simulator.controllers:IdleController')))
        for reference in ('', 'simulator.controllers', ':IdleController'):
            with self.assertRaises(ValueError):
                load_controller(reference)
        for options in ({'game':'cops_robbers'}, {'seeds':(-1,)}, {'seeds':(0,0)},
                        {'scenarios':('missing',)}, {'count':0}):
            with self.assertRaises(ValueError):
                run(**options)


if __name__ == '__main__':
    unittest.main()
