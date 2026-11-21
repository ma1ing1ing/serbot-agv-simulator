import copy
import math
import unittest

from simulator.engine import World
from simulator.scenarios import GROUPS, apply_scenario, names, prepare_scenario


class ScenarioTests(unittest.TestCase):
    def test_default_ready_reset_and_games_use_one_obstacle_free_room(self):
        w = World()
        self.assertEqual(w.obstacles, [])
        for mode in ('tag', 'freeze_tag', 'red_light'):
            for scenario in ('open', None):
                w.start_game(mode, False, scenario=scenario)
                self.assertEqual(w.obstacles, [])
                self.assertEqual(w.scenario['name'], 'open')
                self.assertEqual(w.scenario['obstacles'], [])
        w.reset()
        self.assertEqual(w.obstacles, [])

    def test_every_layout_is_valid_for_all_games_and_group_sizes(self):
        for game in ('tag', 'freeze_tag', 'red_light'):
            for name in names():
                for count in range(1, 9):
                    for seed in (0, 7, 100):
                        with self.subTest(game=game, name=name, count=count, seed=seed):
                            spec = prepare_scenario(name, count, seed, game=game)
                            self.assertEqual(len(spec['children']), count)
                            self.assertEqual(len(spec['behavior_types']), count)
                            if game == 'red_light':
                                self.assertTrue(all(child['z'] == 3.2 for child in spec['children']))

    def test_splits_are_different_layout_families_not_just_new_seeds(self):
        self.assertFalse(set(GROUPS['train']) & set(GROUPS['validation']))
        self.assertFalse(set(GROUPS['train']) & set(GROUPS['test']))
        self.assertFalse(set(GROUPS['validation']) & set(GROUPS['test']))
        baseline = prepare_scenario('standard', 8, 0)
        held_out = prepare_scenario('dense', 8, 0)
        self.assertNotEqual(baseline['obstacles'], held_out['obstacles'])
        self.assertNotEqual(baseline['children'], held_out['children'])

    def test_preparation_is_seeded_and_detached(self):
        first = prepare_scenario('cross_room', 5, 91)
        self.assertEqual(first, prepare_scenario('cross_room', 5, 91))
        self.assertNotEqual(first['children'], prepare_scenario('cross_room', 5, 92)['children'])
        second = prepare_scenario(first, 5, 91)
        second['children'][0]['x'] = 999
        self.assertNotEqual(first, second)

    def test_application_keeps_valid_body_clearances_and_records_metadata(self):
        for game in ('tag', 'freeze_tag', 'red_light'):
            for name in names():
                w = World(); w.set_count(8); w.start_game(game, False)
                spec = prepare_scenario(name, 8, 3, game=game)
                apply_scenario(w, spec, seed=3)
                self.assertEqual(w.scenario, spec)
                self.assertEqual(w.obstacles, spec['obstacles'])
                for child in w.children:
                    self.assertGreater(w.clearance(child['x'], child['z'], exclude_child=child['id']), .249)
                    self.assertGreater(math.hypot(child['x']-w.robot['x'], child['z']-w.robot['z']), .8)
                    self.assertEqual(child['behavior_type'], child['profile']['behavior_type'])

    def test_bad_custom_scenario_is_atomic(self):
        w = World(); w.start_game()
        before = w.snapshot()
        invalid = prepare_scenario('standard', 5, 0)
        invalid['children'][1].update(invalid['children'][0], id=1)
        with self.assertRaises(ValueError):
            apply_scenario(w, invalid)
        self.assertEqual(w.snapshot(), before)

    def test_reject_invalid_fields_and_episode_mismatches(self):
        for kwargs in ({'name':'unknown'}, {'count':0}, {'count':True}, {'seed':-1},
                       {'seed':True}, {'game':'cops_robbers'}):
            with self.assertRaises(ValueError):
                prepare_scenario(**kwargs)
        spec = prepare_scenario('standard')
        with self.assertRaises(ValueError):
            prepare_scenario(spec, count=4)
        for value in (float('nan'), float('inf'), None):
            invalid = copy.deepcopy(spec)
            invalid['robot']['x'] = value
            with self.assertRaises(ValueError):
                prepare_scenario(invalid)
        invalid = copy.deepcopy(spec)
        invalid['obstacles'][0]['w'] = -1
        with self.assertRaises(ValueError):
            prepare_scenario(invalid)


if __name__ == '__main__':
    unittest.main()
