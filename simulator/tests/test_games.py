"""Game transitions and deterministic synthetic child behaviour."""
import copy
import math
import unittest
from unittest.mock import Mock

from simulator.engine import World
from simulator import games
from simulator.tests.test_http_routes import RouteTests


def advance(world, seconds):
    for _ in range(round(seconds/.02)):
        world.tick(.02)


class PlayTests(unittest.TestCase):
    def test_same_seed_and_fixed_steps_are_reproducible_across_rates(self):
        for mode in games.MODES:
            a, b = World(), World()
            a.start_game(mode, seed=45); b.start_game(mode, seed=45)
            advance(a, 4)
            b.rate = 4
            advance(b, 1)
            self.assertEqual(a.children, b.children)
            self.assertEqual(a.robot, b.robot)
            self.assertEqual(a.game, b.game)

    def test_seeds_change_profiles_and_initial_positions(self):
        a, b = World(), World()
        a.start_game(seed=1); b.start_game(seed=2)
        self.assertNotEqual(a.children, b.children)
        self.assertNotEqual(a.children[0]['profile'], b.children[0]['profile'])

    def test_freeze_then_rescue_requires_continuous_contact_and_immunity(self):
        w = World(); w.set_count(2); w.start_game('freeze_tag', False)
        w.emit=Mock(wraps=w.emit)
        w.robot.update(x=0, z=0)
        w.children[0].update(x=0, z=.7)
        w.children[1].update(x=3, z=0)
        w.check_touch()
        self.assertEqual(w.children[0]['state'], 'frozen')
        self.assertEqual(w.game['frozen_ids'], [0])
        w.robot.update(x=-4, z=-3)
        w.children[1].update(x=0, z=1.4)
        advance(w, .3)
        self.assertEqual(w.children[0]['state'], 'frozen')
        w.children[1].update(x=3, z=0)
        advance(w, .02)
        w.children[1].update(x=0, z=1.4)
        advance(w, .4)
        self.assertEqual(w.children[0]['state'], 'frozen')
        advance(w, .22)
        self.assertEqual(w.children[0]['state'], 'free')
        self.assertEqual(w.game['caught_ids'], [])
        self.assertEqual(sum(c.args[0]=='thaw' for c in w.emit.call_args_list), 1)
        w.robot.update(x=w.children[0]['x'], z=w.children[0]['z']-.7)
        w.check_touch()
        self.assertEqual(w.children[0]['state'], 'free')

    def test_last_frozen_child_finishes_and_events_are_not_duplicated(self):
        w = World(); w.set_count(1); w.start_game('freeze_tag', False)
        w.emit=Mock(wraps=w.emit)
        w.children[0].update(x=0, z=w.robot['z']+.7)
        advance(w, .2)
        self.assertEqual(w.game['end_reason'], 'all_frozen')
        self.assertEqual(sum(c.args[0]=='freeze' for c in w.emit.call_args_list), 1)
        self.assertEqual(sum('게임 종료' in entry['message'] for entry in w.logs), 1)

    def test_delayed_stop_is_detected_but_fast_stop_survives(self):
        w = World()
        w.start_game('red_light', False, count=2, settings={'stop_reaction': 'delayed'})
        w.emit=Mock(wraps=w.emit)
        w.robot['heading'] = 3.141592653589793
        advance(w, 1)
        w.children[0]['profile']['reaction_time'] = .6
        w.children[1]['profile']['reaction_time'] = .1
        w.robot['heading'] = 0
        advance(w, .4)
        self.assertEqual(w.children[0]['state'], 'eliminated')
        self.assertEqual(w.children[1]['state'], 'stopped')
        self.assertEqual(sum(c.args[0]=='movement_detected' for c in w.emit.call_args_list), 1)
        self.assertEqual(sum(c.args[0]=='stop_response' for c in w.emit.call_args_list), 1)

    def test_delayed_stop_checks_signal_grace_and_sight(self):
        for case in ('in_view', 'offscreen', 'occluded', 'behind_child', 'still'):
            with self.subTest(case=case):
                w = World()
                count = 2 if case == 'behind_child' else 1
                w.start_game('red_light', False, count=count, settings={'stop_reaction': 'delayed'})
                child = w.children[0]
                child.update(x=0., z=.25, heading=math.pi, moving=True)
                child['profile']['reaction_time'] = .65
                if case == 'offscreen':
                    child.update(x=3., z=-2.2)
                elif case == 'occluded':
                    w.obstacles = [dict(x=0., z=-1.8, w=1.1, d=.35)]
                elif case == 'behind_child':
                    w.children[1].update(x=0., z=-1.25, mode='still')
                elif case == 'still':
                    child.update(moving=False)
                advance(w, .30)
                self.assertNotIn('escort', w.game)
                advance(w, .08)
                if case == 'in_view':
                    self.assertEqual(w.game['escort']['child_id'], 0)
                    self.assertEqual(child['state'], 'eliminated')
                else:
                    self.assertNotIn('escort', w.game)
                    self.assertEqual(w.game['eliminated_ids'], [])
                    if case != 'still':
                        self.assertTrue(child['moving'])

    def test_escort_walks_child_to_the_side_and_resumes_with_remaining_children(self):
        w = World()
        w.start_game('red_light', scenario='standard', settings={'stop_reaction': 'delayed'})
        for _ in range(500):
            w.tick(.02)
            if 'escort' in w.game:
                break
        escort = w.game['escort']
        child = w.children[escort['child_id']]
        start = dict(x=child['x'], z=child['z'])
        waiting = [(c['id'], c['x'], c['z']) for c in w.children if c is not child]
        self.assertEqual(escort['stage'], 'pickup')
        self.assertFalse(child['moving'])
        visited = {escort['stage']}
        for _ in range(2400):
            w.tick(.02)
            if 'escort' not in w.game:
                break
            visited.add(escort['stage'])
        self.assertNotIn('escort', w.game)
        self.assertEqual(visited, {'pickup', 'lead', 'return'})
        self.assertGreater(games.distance(child, start), 1.)
        self.assertLessEqual(games.distance(child, escort['drop']), .2)
        self.assertEqual(waiting, [(c['id'], c['x'], c['z']) for c in w.children if c is not child])
        self.assertEqual(w.episode.counts['escort_complete'], 1)
        self.assertEqual(w.episode.counts['escort_return'], 1)
        self.assertEqual(w.game['phase'], 'approaching')
        advance(w, 4)
        self.assertTrue(any(c['moving'] for c in w.children if c is not child))

    def test_red_light_group_reacts_on_the_same_tick_as_rotation(self):
        w = World()
        w.start_game('red_light', False, physics={'enabled': False}, settings={'trajectory_difficulty': 'simple'})
        w.robot['heading'] = math.pi/2 - .01
        for child in w.children:
            child['profile']['reaction_time'] = .65
        initial = [(child['x'], child['z']) for child in w.children]
        w.tick(.02)
        self.assertTrue(w.game['watching'])
        self.assertTrue(all(c['state'] == 'stopped' for c in w.children))
        self.assertEqual(initial, [(c['x'], c['z']) for c in w.children])

        w.command(0., 1., .02)
        w.tick(.02)
        self.assertFalse(w.game['watching'])
        self.assertTrue(all(c['state'] == 'approaching' and c['moving'] for c in w.children))
        self.assertTrue(all(c['z'] < z for c, (_, z) in zip(w.children, initial)))

        moving_positions = [(c['x'], c['z']) for c in w.children]
        w.command(0., -1., .02)
        w.tick(.02)
        self.assertTrue(w.game['watching'])
        self.assertTrue(all(c['state'] == 'stopped' and not c['moving'] for c in w.children))
        self.assertEqual(moving_positions, [(c['x'], c['z']) for c in w.children])
        advance(w, .8)
        self.assertEqual(w.game['eliminated_ids'], [])

    def test_red_light_default_round_releases_all_children_at_first_touch(self):
        for timing in ('timed', 'settled'):
            with self.subTest(timing=timing):
                w = World()
                w.start_game('red_light', settings={'gaze_timing': timing})
                for _ in range(1500):
                    w.tick(.02)
                    if w.game['phase'] == 'escaping':
                        break
                self.assertEqual(w.game['phase'], 'escaping')
                self.assertEqual(w.game['eliminated_ids'], [])
                self.assertTrue(all(c['state'] == 'escaping' and c['action'] == 'escape' for c in w.children))
                advance(w, .8)
                self.assertTrue(all(c['running'] for c in w.children))
                self.assertEqual(w.game['caught_ids'], [])
                advance(w, w.rules['chase_duration'])
                self.assertEqual(w.game['end_reason'], 'pursuit_complete')
                self.assertEqual(set(w.game['escaped_ids']) | set(w.game['caught_ids']), set(range(5)))

    def test_red_light_automatic_gaze_and_post_touch_chase(self):
        w = World(); w.start_game('red_light')
        w.emit=Mock(wraps=w.emit)
        advance(w, 4)
        self.assertGreater(sum(c.args[0]=='gaze_turn' for c in w.emit.call_args_list), 0)
        self.assertNotEqual(w.robot['heading'], 0)
        w.children[0].update(x=w.robot['x'], z=w.robot['z']+.7)
        w.check_touch()
        self.assertEqual(w.game['phase'], 'escaping')
        self.assertEqual(sum('술래 터치!' in entry['message'] for entry in w.logs), 1)
        self.assertTrue(all(c['state'] == 'escaping' for c in w.children if not c['caught']))

    def test_timeout_and_hold_and_pause_apply_to_every_game(self):
        for mode in games.MODES:
            w = World(); w.start_game(mode, settings={'time_limit':1})
            w.hold_game(True)
            before = copy.deepcopy(w.children)
            advance(w, 2)
            self.assertEqual(w.game['elapsed'], 0)
            self.assertEqual(before, w.children)
            w.hold_game(False)
            w.paused = True; advance(w, 1)
            self.assertEqual(w.game['elapsed'], 0)
            w.paused = False; advance(w, 1)
            self.assertEqual(w.game['end_reason'], 'time_limit')
            self.assertEqual(w.game['phase'], 'finished')

    def test_bad_settings_are_atomic_and_removed_game_is_rejected(self):
        w = World(); w.start_game()
        before = w.snapshot()
        for kwargs in ({'seed':-1}, {'seed':1.5}, {'settings':{'unknown':1}},
                       {'settings':{'time_limit':float('nan')}}, {'settings':{'look_duration':9}},
                       {'mode':'cops_robbers'}):
            with self.assertRaises(ValueError):
                w.start_game(**kwargs)
            self.assertEqual(w.snapshot(), before)

    def test_all_modes_and_populations_stay_in_bounds_without_body_contact(self):
        for mode in games.MODES:
            for count in (1, 5, 8):
                w = World(); w.set_count(count); w.start_game(mode, seed=count)
                advance(w, 5)
                for c in w.children:
                    self.assertGreater(w.clearance(c['x'], c['z'], exclude_child=c['id']), .249)
                    self.assertGreater(games.distance(c, w.robot), w.radius+.22)


class PlayRouteTests(unittest.TestCase):
    request = RouteTests.request

    def setUp(self):
        RouteTests.setUp(self)

    def test_games_seed_settings_and_finish(self):
        for mode in games.MODES:
            status, result = self.request('/api/game/start', dict(mode=mode, seed=4, settings={'time_limit':60}))
            self.assertEqual(status, 200)
            self.assertEqual(result['game']['mode'], mode)
            self.assertEqual(result['game']['seed'], 4)
            self.assertEqual(self.request('/api/game/auto', {'enabled':False})[0], 200)
            self.assertEqual(self.request('/api/game/finish', {})[0], 200)
            self.assertEqual(self.world.game['end_reason'], 'user_stopped')

    def test_invalid_options_return_400_without_reset(self):
        before = self.world.epoch
        for options in ({'mode':'cops_robbers'}, {'seed':-2}, {'settings':{'rescue_hold':0}}):
            self.assertEqual(self.request('/api/game/start', options)[0], 400)
            self.assertEqual(self.world.epoch, before)


if __name__ == '__main__':
    unittest.main()
