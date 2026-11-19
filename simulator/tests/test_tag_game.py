import math
import unittest

from simulator.engine import World


class TagTests(unittest.TestCase):
    def setUp(self):
        self.world=World()

    def advance(self,seconds):
        for _ in range(round(seconds/.02)):
            self.world.tick(.02)

    def test_default_game_is_tag_and_ignores_robots_gaze(self):
        w=self.world
        w.start_game(auto_chase=False)
        before=[(c['x'],c['z']) for c in w.children]
        self.advance(1)
        self.assertEqual(w.game['phase'],'chasing')
        self.assertEqual(w.game['mode'],'tag')
        self.assertTrue(any((c['x'],c['z'])!=p for c,p in zip(w.children,before)))

    def test_near_child_runs_away(self):
        w=self.world
        w.set_count(1);w.start_game(auto_chase=False)
        c=w.children[0]
        w.robot.update(x=c['x'],z=c['z']-1.6)
        c['heading']=0
        before=math.hypot(c['x']-w.robot['x'],c['z']-w.robot['z'])
        self.advance(.5)
        after=math.hypot(c['x']-w.robot['x'],c['z']-w.robot['z'])
        self.assertGreater(after,before)
        self.assertTrue(c['running'])
        self.assertGreater(c['motion_time'],0)

    def test_catch_affects_only_nearby_child_and_is_not_repeated(self):
        w=self.world;w.start_game(auto_chase=False)
        w.game['held']=True
        c=w.children[0];c.update(x=0,z=w.robot['z']+.70)
        self.advance(.5)
        self.assertEqual(w.game['caught_ids'],[0])
        self.assertTrue(c['caught'])
        self.assertFalse(c['moving'])
        self.assertEqual(w.game['phase'],'chasing')
        self.assertTrue(all(not child['caught'] for child in w.children[1:]))
        self.assertEqual(sum('아이 1 잡힘' in log['message'] for log in w.logs),1)

    def test_distance_selects_walk_jog_and_run(self):
        for distance,kind in [(4.0,'walk'),(3.1,'jog'),(1.8,'run')]:
            with self.subTest(distance=distance):
                w=World();w.set_count(1);w.start_game(auto_chase=False)
                child=w.children[0];child['heading']=0
                w.robot.update(x=child['x'],z=child['z']-distance)
                w.tick(.02)
                self.assertEqual(child['motion_kind'],kind)

    def test_last_catch_finishes_game(self):
        w=self.world;w.set_count(1);w.start_game(auto_chase=False)
        w.children[0].update(x=0,z=w.robot['z']+.70)
        self.advance(.1)
        self.assertEqual(w.game['phase'],'finished')
        self.assertEqual(w.game['caught_ids'],[0])
        self.assertEqual(w.robot['linear'],0)

    def test_autopilot_moves_and_manual_command_takes_over(self):
        w=self.world;w.start_game()
        start=dict(w.robot)
        self.advance(2)
        self.assertGreater(math.hypot(w.robot['x']-start['x'],w.robot['z']-start['z']),.25)
        self.assertIsNotNone(w.game['target_id'])
        w.command(0,1,.1)
        self.assertFalse(w.game['auto_chase'])
        self.advance(.2)
        stopped=dict(w.robot)
        self.advance(.5)
        self.assertEqual(w.robot,stopped)

    def test_hold_and_world_pause_freeze_tag(self):
        w=self.world;w.start_game();self.advance(.5)
        w.hold_game(True);self.advance(.02)
        before=w.snapshot()
        self.advance(1)
        self.assertEqual(w.children,before['children'])
        self.assertEqual(w.robot,before['robot'])
        w.hold_game(False);w.paused=True
        before=w.snapshot();self.advance(1)
        self.assertEqual(w.snapshot(),before)

    def test_all_group_sizes_and_rates_respect_collisions(self):
        for count in (1,5,8):
            for rate in (1,4):
                with self.subTest(count=count,rate=rate):
                    w=World();w.set_count(count);w.start_game();w.rate=rate
                    for _ in range(500):
                        w.tick(.02)
                        for c in w.children:
                            self.assertTrue(math.isfinite(c['x']) and math.isfinite(c['z']))
                            self.assertGreater(w.clearance(c['x'],c['z'],exclude_child=c['id']),.249)
                            self.assertGreater(math.hypot(c['x']-w.robot['x'],c['z']-w.robot['z']),w.radius+.22)
                        self.assertGreater(w.clearance(w.robot['x'],w.robot['z']),w.radius)

    def test_restart_preserves_count_and_rate_and_clears_catches(self):
        w=self.world;w.set_count(7);w.rate=2;w.start_game()
        old=w.epoch;w.game['caught_ids']=[0];w.children[0]['caught']=True
        w.start_game(auto_chase=False)
        self.assertNotEqual(old,w.epoch)
        self.assertEqual(w.rate,2)
        self.assertEqual(len(w.children),7)
        self.assertEqual(w.game['caught_ids'],[])
        self.assertTrue(all(not c['caught'] for c in w.children))

    def test_invalid_mode_does_not_reset_the_world(self):
        epoch=self.world.epoch
        with self.assertRaises(ValueError): self.world.start_game('unknown')
        self.assertEqual(self.world.epoch,epoch)

    def test_active_tag_rejects_population_and_manual_child_overrides(self):
        w=self.world;w.start_game()
        with self.assertRaises(ValueError):w.set_count(6)
        with self.assertRaises(ValueError):w.set_child(0,'still')


if __name__=='__main__':
    unittest.main()
