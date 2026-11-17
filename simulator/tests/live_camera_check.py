"""Opt-in end-to-end check: requires the server and an active browser tab.

python3 -m unittest simulator.tests.live_camera_check -v
Resets the virtual world before/after the check. Never touches real hardware.
"""
import time
import unittest
from urllib.request import urlopen

from simulator.client import SimRobot


class LiveCameraCheck(unittest.TestCase):
    def test_render_motion_stream_and_camera(self):
        robot=SimRobot()
        robot._request('/api/world/reset',{})
        try:
            def fresh(after=-1, sim_time=-1):
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    meta=robot.camera_metadata()
                    if meta['ready'] and meta['frame_id']>after and meta['sim_time']>=sim_time:
                        return meta,robot.camera_frame()
                    time.sleep(.04)
                self.fail('가상 카메라 프레임이 도착하지 않습니다. 브라우저 탭을 활성화하세요.')

            meta,before=fresh()
            self.assertTrue(before.startswith(b'\xff\xd8') and before.endswith(b'\xff\xd9'))
            robot._request('/api/children',{'mode':'walk'})
            positions=[c['z'] for c in robot.status()['children']]
            time.sleep(.35)
            robot._request('/api/children',{'mode':'still'})
            self.assertNotEqual(positions,[c['z'] for c in robot.status()['children']])
            result=robot.command_velocity(angular_rps=.5,seconds=.6)
            self.assertEqual(result['status'],'completed')
            self.assertAlmostEqual(robot.status()['robot']['heading'],.3,places=4)
            new_meta,after=fresh(meta['frame_id'],result['time'])
            self.assertNotEqual(before,after,'실제 렌더링 카메라가 로봇 회전을 반영해야 합니다')
            with urlopen(robot.camera_stream_url,timeout=5) as stream:
                self.assertIn('multipart/x-mixed-replace',stream.headers['Content-Type'])
                self.assertEqual(stream.readline().strip(),b'--frame')
                length=None
                while True:
                    line=stream.readline().strip()
                    if not line: break
                    if line.lower().startswith(b'content-length:'): length=int(line.split(b':')[1])
                self.assertIsNotNone(length)
                jpeg=stream.read(length)
                self.assertTrue(jpeg.startswith(b'\xff\xd8') and jpeg.endswith(b'\xff\xd9'))
            print(f'\nLive camera: {len(after):,} JPEG bytes, {new_meta["width"]}×{new_meta["height"]}; child motion, robot rotation and MJPEG verified.')
        finally:
            robot._request('/api/world/reset',{})
