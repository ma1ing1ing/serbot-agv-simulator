"""Tick-synchronized camera protocol over a local TCP server.

A fake renderer thread plays the browser's role (poll /api/state, upload the
pending frame). JPEG bytes are fixtures; real WebGL rendering is checked
separately with an open browser tab (docs/SHIMCHEONG.md).
"""
import importlib.util
import io
import json
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from simulator.client import SimRobot, SimulationError
from simulator.server import SimulationServer


def fixture(tick):
    return b'\xff\xd8tick=' + str(tick).encode() + b'\xff\xd9'


class FakeRenderer(threading.Thread):
    def __init__(self, url, publisher, make_jpeg=fixture):
        super().__init__(daemon=True)
        self.url, self.publisher, self.make_jpeg = url, publisher, make_jpeg
        self.halt = threading.Event()
        self.uploads = []

    def run(self):
        while not self.halt.wait(.02):
            with urlopen(self.url+'/api/state') as response:
                state = json.loads(response.read())
            request = state.get('camera_sync')
            if not request or request['tick'] != request['state_tick']:
                continue
            post = Request(self.url+'/api/camera/frame', data=self.make_jpeg(request['tick']), headers={
                'Content-Type': 'image/jpeg', 'X-Publisher': self.publisher, 'X-Epoch': state['epoch'],
                'X-Sim-Time': str(state['time']), 'X-Sim-Tick': str(request['tick']), 'X-Sync-ID': request['id']})
            try:
                with urlopen(post) as response:
                    self.uploads.append((request['tick'], request['width'], request['height'], response.status))
            except HTTPError as exc:
                self.uploads.append((request['tick'], request['width'], request['height'], exc.code))

    def wait_uploads(self, count, timeout=5.):
        # The server answers the waiting client as soon as it stores the frame,
        # which can be before this thread has read its own POST response.
        deadline = time.monotonic()+timeout
        while len(self.uploads) < count and time.monotonic() < deadline:
            time.sleep(.005)
        return len(self.uploads)


class SyncCameraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = SimulationServer(('127.0.0.1', 0))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.robot = SimRobot(self.url)
        self.renderer = None

    def tearDown(self):
        if self.renderer is not None:
            self.renderer.halt.set()
            self.renderer.join(timeout=2)
        self.robot.training_close()
        self.server.world.paused = False

    def start_renderer(self, **kwargs):
        self.renderer = FakeRenderer(self.url, self.server.publisher, **kwargs)
        self.renderer.start()

    def test_frame_belongs_to_the_requested_tick(self):
        first = self.robot.training_reset(mode='tag', seed=3, serbot_sensors=True, physics='serbot_measured')
        self.start_renderer()
        tick = first['observation']['tick']
        self.assertEqual(self.robot.camera_frame_sync(tick, width=1280, height=720, fov_deg=43.3, timeout=5), fixture(tick))
        step = self.robot.training_step({'linear_mps': .2, 'angular_rps': .3})
        tick = step['observation']['tick']
        self.assertEqual(tick, 5)
        self.assertEqual(self.robot.camera_frame_sync(tick, width=1280, height=720, fov_deg=43.3, timeout=5), fixture(5))
        # A repeated request for the same tick and size is served from the last frame.
        self.assertEqual(self.renderer.wait_uploads(2), 2)
        self.assertEqual(self.robot.camera_frame_sync(tick, width=1280, height=720, fov_deg=43.3, timeout=5), fixture(5))
        time.sleep(.1)                       # several renderer polls: none may upload again
        self.assertEqual(len(self.renderer.uploads), 2)
        self.assertEqual([u[1:] for u in self.renderer.uploads], [(1280, 720, 200)]*2)
        with urlopen(self.url+'/api/state') as response:
            self.assertNotIn('camera_sync', json.loads(response.read()))

    def test_wrong_tick_epoch_or_advancing_world_is_rejected(self):
        result = self.robot.training_reset(mode='tag', seed=1)
        epoch = result['info']['epoch']
        for tick, ident in ((7, epoch), (0, 'stale-epoch')):
            with self.subTest(tick=tick, epoch=ident), self.assertRaisesRegex(SimulationError, '409'):
                self.robot.camera_frame_sync(tick, ident, timeout=1)
        self.robot.training_close()
        self.robot.start_game('tag', auto_chase=False)
        with self.server.world.lock:
            epoch, tick = self.server.world.epoch, self.server.world.frame
        with self.assertRaisesRegex(SimulationError, '409'):
            self.robot.camera_frame_sync(tick, epoch, timeout=1)
        for path in ('/api/camera/sync.jpg?tick=x&epoch=e', '/api/camera/sync.jpg?epoch=e', '/api/camera/sync.jpg?tick=0&epoch=e&width=5000'):
            with self.subTest(path=path), self.assertRaisesRegex(SimulationError, '400'):
                self.robot._request(path, binary=True)

    def test_missing_renderer_times_out_and_clears_the_request(self):
        result = self.robot.training_reset(mode='tag', seed=2)
        started = time.monotonic()
        with self.assertRaisesRegex(SimulationError, '504'):
            self.robot.camera_frame_sync(result['observation']['tick'], timeout=.2)
        self.assertLess(time.monotonic()-started, 3)
        self.assertIsNone(self.server.sync_request)

    def test_paused_realtime_world_can_be_rendered(self):
        self.robot.start_game('freeze_tag', auto_chase=False)
        with self.server.world.lock:
            self.server.world.paused = True
            epoch, tick = self.server.world.epoch, self.server.world.frame
        self.start_renderer()
        self.assertEqual(self.robot.camera_frame_sync(tick, epoch, timeout=5), fixture(tick))

    def test_unrequested_or_mismatched_upload_is_rejected(self):
        self.robot.training_reset(mode='tag', seed=4)
        post = Request(self.url+'/api/camera/frame', data=fixture(0), headers={
            'Content-Type': 'image/jpeg', 'X-Publisher': self.server.publisher, 'X-Epoch': self.server.world.epoch,
            'X-Sim-Time': '0', 'X-Sim-Tick': '0', 'X-Sync-ID': 'not-requested'})
        with self.assertRaises(HTTPError) as caught:
            urlopen(post)
        self.assertEqual(caught.exception.code, 409)
        caught.exception.close()

    @unittest.skipUnless(importlib.util.find_spec('numpy') and importlib.util.find_spec('PIL'), 'numpy/Pillow not installed')
    def test_sync_frame_source_decodes_model_size_rgb(self):
        from PIL import Image
        from simulator.examples.shimcheong_controller import SyncCameraFrames

        def jpeg(tick):
            buffer = io.BytesIO()
            Image.new('RGB', (1280, 720), (90, 120, 150)).save(buffer, 'JPEG')
            return buffer.getvalue()
        result = self.robot.training_reset(mode='tag', seed=5, serbot_sensors=True)
        self.start_renderer(make_jpeg=jpeg)
        frame = SyncCameraFrames(self.robot, timeout=5)(result['observation'])
        self.assertEqual(frame.shape, (720, 1280, 3))


if __name__ == '__main__':
    unittest.main()
