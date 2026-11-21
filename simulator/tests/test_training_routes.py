"""Exercise stepped HTTP ownership and the public SDK without TCP sockets."""
import copy
import unittest

from simulator.client import SimRobot, SimulationError
from simulator.tests import test_http_routes as routes


class TrainingRoutes(unittest.TestCase):
    request = routes.RouteTests.request

    def setUp(self):
        routes.RouteTests.setUp(self)

    def test_live_mutations_are_excluded_and_wall_clock_is_frozen(self):
        status,result=self.request('/api/training/reset',{'mode':'freeze_tag','seed':7})
        self.assertEqual(status,200)
        self.assertEqual(result['observation']['tick'],0)
        self.assertEqual(self.world.execution_mode,'stepped')
        before=self.world.snapshot()
        self.world.tick(.05)
        self.assertEqual(self.world.snapshot(),before)
        for path,data in (('/api/game/start',{}),('/api/world/reset',{}),('/api/world/config',{'rate':4}),
                          ('/api/robot/command',{'linear_mps':.3}),('/api/game/auto',{'enabled':True})):
            self.assertEqual(self.request(path,data)[0],409)
            self.assertEqual(self.world.snapshot(),before)
        status,following=self.request('/api/training/step',{'action':{'linear_mps':.2}})
        self.assertEqual(status,200)
        self.assertEqual(following['observation']['tick'],5)
        self.assertAlmostEqual(following['observation']['time'],.1)
        self.assertEqual(self.request('/api/training/close',{})[0],200)
        self.assertEqual(self.world.execution_mode,'realtime')
        self.assertEqual(self.world.game['phase'],'ready')
        self.assertEqual(self.request('/api/game/start',{})[0],200)

    def test_invalid_reset_and_action_leave_active_session_unchanged(self):
        self.request('/api/training/reset',{})
        previous=self.server.training_env
        before=self.world.snapshot()
        for data in ({'scenario':'missing'},{'count':9},{'dt':.03},{'physics':{'max_linear':9}}):
            self.assertEqual(self.request('/api/training/reset',data)[0],400)
            self.assertEqual(self.world.snapshot(),before)
            self.assertIs(self.server.training_env,previous)
        for action in ({'linear_mps':2},None,{'angular_rps':float('nan')}):
            self.assertEqual(self.request('/api/training/step',{'action':action})[0],400)
            self.assertEqual(self.world.snapshot(),before)

    def test_sensor_inputs_are_explicit_and_reach_the_actual_step_input(self):
        self.request('/api/training/reset',{'observation_mode':'sensor'})
        self.assertFalse(any(self.request('/api/observation?mode=sensor')[1]['child_mask']))
        detections=[dict(id=77,relative_x=1,relative_z=2)]
        self.assertEqual(self.request('/api/detections',{'detections':detections})[0],200)
        self.request('/api/training/step',{'action':{'linear_mps':0}})
        self.assertEqual(self.world.action_input['children'][0]['id'],77)
        self.assertEqual(self.world.action_input['source'],'sensor')
        self.assertEqual(self.request('/api/observation?mode=unknown')[0],400)

    def test_stale_epoch_request_is_rejected(self):
        old=self.request('/api/training/reset',{})[1]['info']['epoch']
        self.request('/api/training/reset',{'seed':1})
        before=self.world.snapshot()
        self.assertEqual(self.request('/api/training/step',{'epoch':old,'action':{}})[0],409)
        self.assertEqual(self.world.snapshot(),before)
        self.assertEqual(self.request('/api/training/close',{'epoch':old})[0],409)
        self.assertEqual(self.world.snapshot(),before)

    def test_sdk_trains_against_actual_http_handler_and_tracks_epoch(self):
        robot=SimRobot()
        def request(path,data=None,**kwargs):
            status,result=self.request(path,data)
            if status!=200:raise SimulationError(result['error'])
            return result
        robot._request=request
        start=robot.training_reset(mode='tag',seed=9,count=2,settings={'time_limit':1})
        self.assertEqual(start['info']['seed'],9)
        self.assertEqual(robot.observation()['source'],'oracle')
        following=robot.training_step({'linear_mps':.1,'guard':False})
        self.assertEqual(following['observation']['tick'],5)
        robot.set_detections([dict(id=99,relative_x=1,relative_z=1)])
        self.assertEqual(robot.observation('sensor')['children'][0]['id'],99)
        robot.training_close()
        self.assertIsNone(robot._training_epoch)

    def test_stop_and_finish_interrupt_training_safely(self):
        for endpoint in ('/api/robot/stop','/api/game/finish'):
            self.request('/api/training/reset',{})
            self.request('/api/training/step',{'action':{'linear_mps':.3,'guard':False}})
            self.assertGreater(self.world.robot['linear'],0)
            self.assertEqual(self.request(endpoint,{})[0],200)
            self.assertEqual(self.world.robot['linear'],0)
            self.assertEqual(self.world.game['phase'],'finished')
            self.assertFalse(self.server.training_env.active)
            self.assertEqual(self.request('/api/training/step',{'action':{}})[0],400)


if __name__=='__main__':unittest.main()
