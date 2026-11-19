"""Recorded movement must keep a shared clock and must not invent missing data."""
import copy
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from simulator.engine import World
from simulator import replay
from simulator.tests.test_http_routes import RouteTests


def recording():
    return replay.Recording(dict(schema_version=1,assumptions={},source={'title':'test recording'},clips=[
        dict(id='active',name='Test',start=100.0,duration=12.0)],tracks=[
        dict(id=2,segments=[[[100.,0.,0.],[101.,2.,0.],[102.,4.,0.]],
                            [[110.,6.,1.],[112.,6.,3.]]]),
        dict(id=9,segments=[[[100.,0.,2.],[106.,0.,8.],[112.,0.,14.]]])]))


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.recording=recording()
        self.loader=patch('simulator.replay.load',return_value=self.recording)
        self.loader.start()
        self.addCleanup(self.loader.stop)
        self.world=World()

    def start(self):
        self.world.start_game('playground_a',replay_count=2)
        self.world.rate=1

    def test_interpolation_and_gap_are_distinct(self):
        self.assertEqual(self.recording.sample(2,100.5)[:4],(1.,0.,2.,0.))
        self.assertIsNone(self.recording.sample(2,105.))
        self.assertIsNone(self.recording.sample(2,99.))
        self.assertEqual(self.recording.sample(2,112.)[:2],(6.,3.))

    def test_shared_clock_uniform_fit_and_no_robot_reaction(self):
        self.start()
        w=self.world
        w.seek_replay(.5)
        first,second=w.children
        distance=math.hypot(first['x']-second['x'],first['z']-second['z'])
        self.assertAlmostEqual(distance/w.replay.scale,math.hypot(1,2.5))
        # Moving the robot onto the observed participant does not synthesize a
        # tag or divert the recorded path.
        w.robot.update(x=first['x'],z=first['z'])
        w.tick(.02)
        self.assertEqual(w.game['caught_ids'],[])
        self.assertFalse(w.game['auto_chase'])
        self.assertEqual(w.snapshot()['replay']['source_time'],100.52)

    def test_gap_hides_child_and_removes_it_from_sensors(self):
        self.start()
        w=self.world
        w.seek_replay(5.)
        self.assertFalse(w.children[0]['visible'])
        self.assertEqual(w.children[0]['trail'],[])
        x,z=w.children[0]['x'],w.children[0]['z']
        self.assertEqual(w.clearance(x,z),w.clearance(x,z,exclude_child=0))
        w.seek_replay(10.5)
        self.assertTrue(w.children[0]['visible'])
        self.assertEqual(len(w.children[0]['trail']),1)

    def test_hold_pause_seek_and_finish(self):
        self.start()
        w=self.world
        w.hold_game(True)
        children=copy.deepcopy(w.children)
        for _ in range(10):w.tick(.05)
        self.assertEqual(w.children,children)
        self.assertEqual(w.replay.elapsed,0)
        w.hold_game(False)
        w.paused=True
        before=w.snapshot();w.tick(.05)
        self.assertEqual(before,w.snapshot())
        w.paused=False
        w.seek_replay(12)
        self.assertEqual(w.game['phase'],'finished')
        self.assertTrue(all(not c['moving'] for c in w.children))
        w.tick(.05)
        self.assertEqual(w.replay.elapsed,12)
        w.seek_replay(1)
        self.assertEqual(w.game['phase'],'replaying')
        self.assertTrue(all(len(c['trail'])==1 for c in w.children))

    def test_failed_start_or_seek_does_not_change_world(self):
        self.start()
        before=self.world.snapshot()
        for options in ({'clip_id':'missing','replay_count':2},{'replay_count':3}):
            with self.assertRaises(ValueError):self.world.start_game('playground_a',**options)
            self.assertEqual(before,self.world.snapshot())
        with self.assertRaises(ValueError):self.world.seek_replay(float('nan'))
        self.assertEqual(before,self.world.snapshot())

    def test_reset_and_game_switch_remove_recorded_state(self):
        self.start()
        with self.assertRaises(ValueError):self.world.set_child(0,'still')
        self.world.start_game('tag',auto_chase=False)
        self.assertIsNone(self.world.replay)
        self.assertTrue(all('source_id' not in c for c in self.world.children))
        self.start();self.world.reset()
        self.assertEqual(self.world.game['phase'],'ready')
        self.assertIsNone(self.world.snapshot()['replay'])


class ReplayRouteTests(unittest.TestCase):
    request=RouteTests.request

    def setUp(self):
        RouteTests.setUp(self)
        loader=patch('simulator.replay.load',return_value=recording())
        loader.start();self.addCleanup(loader.stop)

    def test_replay_api_start_config_seek_and_return_to_tag(self):
        self.assertTrue(self.request('/api/replay')[1]['available'])
        status,data=self.request('/api/game/start',dict(mode='playground_a',replay_count=2))
        self.assertEqual(status,200)
        self.assertEqual(data['game']['phase'],'replaying')
        self.assertEqual(self.request('/api/world/config',{'rate':16,'paused':True})[0],200)
        self.assertEqual(self.world.rate,16)
        self.assertEqual(self.request('/api/replay/seek',{'elapsed':5})[0],200)
        self.assertFalse(self.world.children[0]['visible'])
        self.assertEqual(self.request('/api/replay/seek',{'elapsed':99})[0],400)
        self.assertEqual(self.request('/api/game/start',{'mode':'tag'})[0],200)
        self.assertIsNone(self.world.replay)
        self.assertLessEqual(self.world.rate,4)


class LocalReplayTests(unittest.TestCase):
    def test_downloaded_data_all_clips_have_moving_finite_tracks(self):
        if not replay.PACK_PATH.exists():self.skipTest('local recording not prepared')
        w=World()
        for clip in replay.load().clips:
            w.start_game('playground_a',clip_id=clip['id'])
            self.assertEqual(len(w.children),16)
            before=[(c['x'],c['z']) for c in w.children]
            w.seek_replay(30)
            self.assertTrue(any(math.hypot(c['x']-a,c['z']-b)>.05 for c,(a,b) in zip(w.children,before)))
            for c in w.children:
                self.assertTrue(math.isfinite(c['x']) and math.isfinite(c['z']))
                if c['visible']:
                    self.assertLessEqual(abs(c['x']),3.401)
                    self.assertLessEqual(abs(c['z']),2.401)

    def test_missing_local_file_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(replay,'PACK_PATH',Path(directory)/'missing.json'):
            self.assertFalse(replay.metadata()['available'])
            with self.assertRaisesRegex(ValueError,'Playground A'):
                replay.load()


if __name__=='__main__':unittest.main()
