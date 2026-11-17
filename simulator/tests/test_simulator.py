import json
import math
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from simulator.client import SimRobot, SimulationError
from simulator.engine import World
from simulator.server import SimulationServer


class WorldTests(unittest.TestCase):
    def setUp(self):
        self.world=World()

    def advance(self, seconds):
        for _ in range(round(seconds/.02)):
            self.world.tick(.02)

    def test_motion_units_and_completion(self):
        command=self.world.command(.2,0,1)
        self.advance(1.1)
        self.assertAlmostEqual(self.world.robot['z'],-3.15,places=6)
        self.assertEqual(self.world.command_results[command['id']]['status'],'completed')
        self.assertEqual(self.world.robot['linear'],0)

    def test_left_rotation_faces_negative_x(self):
        self.world.command(0,math.pi/2,1)
        self.advance(1.1)
        self.world.command(.2,0,1)
        self.advance(1.1)
        self.assertAlmostEqual(self.world.robot['x'],-.2,places=5)
        self.assertAlmostEqual(self.world.robot['z'],-3.35,places=5)

    def test_pause_does_not_consume_motion_duration(self):
        self.world.command(.2,0,1)
        self.world.paused=True
        self.advance(1)
        self.assertEqual(self.world.time,0)
        self.world.paused=False
        self.advance(1.1)
        self.assertAlmostEqual(self.world.distance,.2,places=5)

    def test_acceleration_preserves_distance(self):
        self.world.rate=4
        self.world.command(.2,0,1)
        self.advance(.5)
        self.assertAlmostEqual(self.world.distance,.2,places=5)

    def test_child_motion_and_stop(self):
        child=self.world.children[0]
        start=child['z']
        self.world.set_child(0,'walk')
        self.advance(1)
        self.assertLess(child['z'],start)
        self.world.set_child(0,'still')
        stopped=child['z']
        self.advance(1)
        self.assertEqual(child['z'],stopped)

    def test_collision_cannot_tunnel_through_child(self):
        self.world.children[2].update(x=0,z=-2.2)
        command=self.world.command(.5,0,4,guard=False)
        self.advance(4.1)
        self.assertGreaterEqual(abs(self.world.robot['z']+2.2),self.world.radius+.22+.019)
        self.assertEqual(self.world.command_results[command['id']]['status'],'collision')

    def test_guard_stops_before_contact(self):
        self.world.children[2].update(x=0,z=-2.2)
        command=self.world.command(.3,0,5)
        self.advance(5.1)
        self.assertEqual(self.world.command_results[command['id']]['status'],'guard')
        self.assertGreater(self.world.clearance(self.world.robot['x'],self.world.robot['z']),self.world.radius)

    def test_reset_invalidates_pending_motion(self):
        old=self.world.epoch
        self.world.command(.2,0,3)
        self.world.reset()
        self.assertNotEqual(old,self.world.epoch)
        self.assertIsNone(self.world.motion)
        self.assertEqual(self.world.time,0)

    def test_reject_nonfinite_and_invalid_input(self):
        for value in [float('nan'),float('inf'),1.0]:
            with self.assertRaises(ValueError):
                self.world.command(value,0,1)
        with self.assertRaises(ValueError):
            self.world.set_child(0,'made-up')


class GameTests(unittest.TestCase):
    def setUp(self):
        self.world=World()

    def advance(self,seconds):
        for _ in range(round(seconds/.02)):
            self.world.tick(.02)

    def test_touch_by_one_child_makes_everyone_flee_including_still_children(self):
        w=self.world
        w.start_game()
        for c in w.children:
            w.set_child(c['id'],'still')
            c['z']=2.0
        w.children[1].update(x=0,z=w.robot['z']+.70)
        self.advance(.02)
        self.assertEqual(w.game['phase'],'escaping')
        self.assertEqual(w.game['touched_by'],1)
        self.assertTrue(all(c['moving'] and c['running'] and c['mode']=='walk' for c in w.children))
        positions=[c['z'] for c in w.children]
        self.advance(.2)
        self.assertTrue(all(c['z']>=z for c,z in zip(w.children,positions)))

    def test_full_round_finishes_for_every_supported_group_size(self):
        for count in range(1,9):
            with self.subTest(count=count):
                w=World()
                w.set_count(count)
                w.start_game()
                w.robot['heading']=math.pi
                for _ in range(1800):
                    w.tick(.02)
                    if w.game['phase']=='finished':
                        break
                self.assertEqual(w.game['phase'],'finished')
                self.assertEqual(len(w.game['escaped_ids']),count)
                self.assertTrue(all(c['escaped'] and not c['moving'] and abs(c['z']-w.home_z)<.001 for c in w.children))
                self.assertEqual(sum('술래 터치!' in log['message'] for log in w.logs),1)

    def test_approach_is_not_the_old_back_and_forth_patrol(self):
        w=self.world
        w.start_game()
        w.robot['heading']=math.pi
        self.advance(8)
        self.assertEqual(w.game['phase'],'approaching')
        self.assertLess(min(c['z'] for c in w.children),-1.9)

    def test_nearby_but_not_touching_does_not_trigger(self):
        w=self.world
        w.start_game()
        w.hold_game(True)
        w.children[2].update(x=0,z=w.robot['z']+w.touch_distance+.01)
        self.advance(.1)
        self.assertEqual(w.game['phase'],'approaching')

    def test_hold_stops_approach_but_cannot_stop_group_escape(self):
        w=self.world
        w.start_game()
        w.hold_game(True)
        positions=[(c['x'],c['z']) for c in w.children]
        self.advance(1)
        self.assertEqual(positions,[(c['x'],c['z']) for c in w.children])
        w.children[2].update(x=0,z=w.robot['z']+.70)
        self.advance(.02)
        self.assertFalse(w.game['held'])
        with self.assertRaises(ValueError):
            w.hold_game(True)
        with self.assertRaises(ValueError):
            w.set_child(0,'still')

    def test_world_pause_freezes_escape(self):
        w=self.world
        w.start_game()
        w.children[2].update(x=0,z=w.robot['z']+.70)
        self.advance(.02)
        w.paused=True
        before=w.snapshot()
        self.advance(2)
        after=w.snapshot()
        self.assertEqual(before['children'],after['children'])
        self.assertEqual(before['time'],after['time'])

    def test_restart_clears_touch_and_invalidates_motion_and_camera_epoch(self):
        w=self.world
        w.set_count(7)
        w.rate=2
        w.start_game()
        w.children[2].update(x=0,z=w.robot['z']+.7)
        self.advance(.02)
        old=w.epoch
        w.command(.1,0,5)
        w.start_game()
        self.assertNotEqual(w.epoch,old)
        self.assertIsNone(w.motion)
        self.assertEqual(w.rate,2)
        self.assertEqual(len(w.children),7)
        self.assertEqual(w.game['phase'],'approaching')
        self.assertIsNone(w.game['touched_by'])
        self.assertTrue(all(c['z']==w.home_z for c in w.children))

    def test_population_cannot_change_mid_round(self):
        self.world.start_game()
        with self.assertRaises(ValueError):
            self.world.set_count(8)
        self.assertEqual(len(self.world.children),5)

    def test_children_freeze_when_tagger_faces_them_including_wiggle(self):
        w=self.world
        w.start_game()
        w.set_child(0,'wiggle')
        positions=[(c['x'],c['z']) for c in w.children]
        self.advance(2)
        self.assertEqual(positions,[(c['x'],c['z']) for c in w.children])
        self.assertTrue(all(c['watched'] and not c['moving'] and not c['wave'] for c in w.children))

    def test_turn_away_approach_then_turn_back_freeze(self):
        w=self.world
        w.start_game()
        w.robot['heading']=math.pi
        before=[c['z'] for c in w.children]
        self.advance(1)
        self.assertTrue(all(c['z']<z for c,z in zip(w.children,before)))
        w.robot['heading']=0
        stopped=[(c['x'],c['z']) for c in w.children]
        self.advance(1)
        self.assertEqual(stopped,[(c['x'],c['z']) for c in w.children])
        self.assertTrue(all(not c['moving'] for c in w.children))

    def test_gaze_is_relative_to_robot_position_and_handles_angle_wrap(self):
        w=self.world
        w.robot.update(x=2,z=1,heading=math.pi/2)
        self.assertTrue(w.robot_watching(dict(x=1,z=1)))
        self.assertFalse(w.robot_watching(dict(x=3,z=1)))
        # Side-on is not clearly behind, so the child waits.
        self.assertTrue(w.robot_watching(dict(x=2,z=3)))
        for heading in (math.pi,-math.pi,3*math.pi):
            w.robot['heading']=heading
            self.assertFalse(w.robot_watching(dict(x=2,z=3)))

    def test_gaze_does_not_stop_escape(self):
        w=self.world
        w.start_game()
        for c in w.children:
            c['z']=2
        w.children[2].update(x=0,z=w.robot['z']+.70)
        self.advance(.02)
        self.assertEqual(w.game['phase'],'escaping')
        before=[c['z'] for c in w.children]
        self.advance(.2)
        self.assertTrue(all(c['z']>z for c,z in zip(w.children,before)))
        self.assertTrue(all(c['running'] for c in w.children))


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=SimulationServer(('127.0.0.1',0))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.url=f'http://127.0.0.1:{cls.server.server_port}'
        cls.robot=SimRobot(cls.url)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.server.world.reset()
        with self.server.frame_lock:
            self.server.frame=None

    def test_camera_never_returns_stale_frame(self):
        with self.assertRaises(SimulationError):
            self.robot.camera_frame()
        with self.server.frame_lock:
            self.server.frame=b'\xff\xd8test\xff\xd9'
            self.server.frame_at=0
        self.assertFalse(self.robot.camera_metadata()['ready'])
        with self.assertRaises(SimulationError):
            self.robot.camera_frame()

    def test_camera_publisher_then_real_binary_endpoint(self):
        # Protocol fixture only; renderer-generated JPEGs are verified in browser QA.
        jpeg=b'\xff\xd8fixture\xff\xd9'
        request=Request(self.url+'/api/camera/frame',data=jpeg,headers={
            'Content-Type':'image/jpeg','X-Publisher':self.server.publisher,
            'X-Epoch':self.server.world.epoch,'X-Sim-Time':'0'})
        with urlopen(request) as response:
            self.assertEqual(response.status,200)
        self.assertEqual(self.robot.camera_frame(),jpeg)
        self.server.world.reset()
        self.assertFalse(self.robot.camera_metadata()['ready'])

    def test_sdk_wait_and_stop(self):
        result=self.robot.command_velocity(.1,0,seconds=.1)
        self.assertEqual(result['status'],'completed')
        command=self.robot.command_velocity(.1,0,seconds=3,wait=False)
        self.robot.stop()
        self.assertEqual(self.robot._request('/api/command?id='+command['id'])['status'],'stopped')

    def test_motion_supersession_is_observable(self):
        first=self.robot.command_velocity(.1,seconds=3,wait=False)
        self.robot.command_velocity(0,.2,seconds=.1)
        self.assertEqual(self.robot._request('/api/command?id='+first['id'])['status'],'superseded')

    def test_sensors_and_compatibility(self):
        self.assertEqual(len(self.robot.lidar_scan()['ranges']),72)
        self.assertIn('front_min_cm',self.robot.ultrasonic())
        result=self.robot.forward(speed=4,seconds=.1)
        self.assertEqual(result['status'],'completed')
        result=self.robot.spin_left(speed=3,seconds=.1)
        self.assertEqual(result['status'],'completed')
        with self.assertRaises(ValueError):
            self.robot.forward(speed=11)

    def test_reject_cross_origin_command(self):
        request=Request(self.url+'/api/robot/command',data=b'{}',headers={'Content-Type':'application/json','Origin':'https://other-site.example'})
        with self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code,403)
        error.exception.close()

    def test_bad_command_does_not_mutate_state(self):
        with self.assertRaises(SimulationError):
            self.robot.command_velocity(linear_mps=2,seconds=.1)
        self.assertIsNone(self.server.world.motion)

    def test_game_api_and_sdk(self):
        self.robot.start_game()
        self.assertEqual(self.robot.status()['game']['phase'],'approaching')
        self.robot.hold_children()
        self.assertTrue(self.robot.status()['game']['held'])
        self.robot.hold_children(False)
        self.assertFalse(self.robot.status()['game']['held'])
        with self.assertRaises(SimulationError):
            self.robot._request('/api/world/config',{'count':8,'rate':4,'paused':True})
        state=self.robot.status()
        self.assertEqual(state['rate'],1)
        self.assertFalse(state['paused'])
        self.assertEqual(len(state['children']),5)

    def test_rotation_commands_control_children_via_api(self):
        self.robot.start_game()
        before=self.robot.status()['children']
        self.assertTrue(all(c['watched'] for c in before))
        self.robot.command_velocity(angular_rps=3,seconds=math.pi/3)
        away=self.robot.status()['children']
        self.assertTrue(all(not c['watched'] for c in away))
        self.assertTrue(any(c['z']<b['z'] for c,b in zip(away,before)))
        self.robot.command_velocity(angular_rps=-3,seconds=math.pi/3)
        facing=self.robot.status()['children']
        self.assertTrue(all(c['watched'] and not c['moving'] for c in facing))
        time_before=[(c['x'],c['z']) for c in facing]
        # A zero-velocity command lets simulation time advance through the API.
        self.robot.command_velocity(seconds=.1)
        self.assertEqual(time_before,[(c['x'],c['z']) for c in self.robot.status()['children']])


if __name__=='__main__':
    unittest.main()
