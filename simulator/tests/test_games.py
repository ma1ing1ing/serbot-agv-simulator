"""Game transitions and deterministic synthetic child behaviour."""
import copy
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
        w = World(); w.set_count(2); w.start_game('red_light', False)
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
