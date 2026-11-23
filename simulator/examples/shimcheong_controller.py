"""Connect the simcheongi driving planner as an ordinary observation-only controller.

simcheongi (Hugging Face ``koreashin/simcheongi``) is a guide-dog robot driving
planner trained for indoor corridor / route following at about 0.25 m/s, and
trained to keep clear of standing people. It was NOT trained or validated on
games, children, or this simulator's rendering. Here the game supplies the
route (by default a straight line from the robot to the chosen child), so the
robot approaches a child only as far as the planner follows that route; it may
slow down or steer around the very child it is meant to tag. Treat results as
an integration / behaviour check, not as a measure of the model or of a game
policy. The model is not a safety system (docs/SHIMCHEONG.md).

What the wrapper reproduces from the robot runtime:

* one model decision every 0.5 s (``DECISION_PERIOD_S``); between decisions
  the last 5 s plan is followed, as the robot driver does;
* the camera history buffer: frames at t0-1.5 / -1.0 / -0.5 / 0 s, taken from
  earlier decisions (the first frame before enough history exists);
* ego history on a 0.1 s grid, seconds since the episode started;
* a simple pure-pursuit follower with the driver's look-ahead / end / align
  rules, clipped by the ``serbot_measured`` physics limits; speed =
  min(v_max, plan speed hint), v_max 0.25 m/s by default as on the robot.

Requirements: ``PlayEnv(..., serbot_sensors=True)`` or the HTTP training reset
with ``serbot_sensors: true``. The optional ``simcheongi`` package (PyTorch) is
imported only when no ``policy`` object is supplied.

python3 -m simulator.examples.shimcheong_controller --game tag --frames blank
python3 -m simulator.examples.shimcheong_controller --game tag --frames sync   # server + open browser tab
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import statistics

from simulator import serbot_sensors
from simulator.contracts import MotionAction, SCHEMA_VERSION
from simulator.controllers import RedLightController
from simulator.motion import validate_physics

DEFAULT_MODEL = 'koreashin/simcheongi'
DECISION_PERIOD_S = .5               # the model's training / robot decision interval
HISTORY_OFFSETS_S = (1.5, 1., .5, 0.)
HISTORY_DT_S = .1
HISTORY_ROWS = 41                    # >= 31 rows (3 s) required once the episode is that long
FRAME_WIDTH, FRAME_HEIGHT = 1280, 720
CAMERA_VFOV_DEG = 43.3               # nominal 70.4 deg horizontal at 16:9 (not calibrated)
MODEL_V_MAX = .25                    # robot speed command: min(0.25, speed_hint)
# Follower rules of the robot driver (docs/SHIMCHEONG.md lists the sources).
LOOKAHEAD_M = .45
LOOKAHEAD_MIN_M = .30
PATH_END_M = .08
PATH_MIN_M = .15
ALIGN_DEG = 110.
V_GO_MIN = .03
ACTIVE_PHASES = dict(tag=('chasing',), freeze_tag=('chasing',), red_light=('approaching', 'escaping'))
ELIGIBLE_STATES = dict(tag=('free', 'rescuing', 'unknown'), freeze_tag=('free', 'rescuing', 'unknown'),
                       red_light=('escaping', 'unknown'))


def load_policy(model=DEFAULT_MODEL, device=None, adapter=None):
    """Import simcheongi lazily; a clear error when it is not installed."""
    try:
        from simcheongi import SimcheongiPolicy
    except ImportError as exc:
        raise ImportError('ShimcheongController needs the optional simcheongi package (PyTorch, '
                          'transformers 5.14.1, Pillow 12.0.0) in your own environment: install the code of '
                          'the Hugging Face repository koreashin/simcheongi, see docs/SHIMCHEONG.md') from exc
    return SimcheongiPolicy.from_pretrained(model, device=device, adapter=adapter)


class BlankFrames:
    """Constant grey 1280x720 frames: a run WITHOUT camera input (plumbing only)."""
    name = 'blank'

    def __init__(self, value=128):
        self.value = int(value)
        self._frame = None

    def __call__(self, observation):
        if self._frame is None:
            import numpy as np
            self._frame = np.full((FRAME_HEIGHT, FRAME_WIDTH, 3), self.value, dtype=np.uint8)
        return self._frame


class SyncCameraFrames:
    """Browser frames rendered for exactly the observation's tick (HTTP stepped session)."""
    name = 'sync'

    def __init__(self, robot, *, epoch=None, fov_deg=CAMERA_VFOV_DEG, timeout=10.):
        self.robot, self.epoch, self.fov_deg, self.timeout = robot, epoch, fov_deg, timeout

    def __call__(self, observation):
        jpeg = self.robot.camera_frame_sync(observation['tick'], self.epoch, width=FRAME_WIDTH, height=FRAME_HEIGHT,
                                            fov_deg=self.fov_deg, timeout=self.timeout)
        import numpy as np
        from PIL import Image
        return np.asarray(Image.open(io.BytesIO(jpeg)).convert('RGB'))


def _wrap(angle):
    return (angle+math.pi) % (2*math.pi)-math.pi


class ShimcheongController:
    """simcheongi planner + pure-pursuit follower behind the reset/predict contract.

    ``policy``: an object with ``plan(frames, lidar, ego_history, route, *,
    ultrasonic, session)`` and ``reset(session)`` (default: SimcheongiPolicy
    loaded from ``model``). ``frame_source(observation)`` returns an RGB uint8
    (720, 1280, 3) frame: ``BlankFrames()`` or ``SyncCameraFrames(robot)``.
    ``route_fn(observation, pose)`` may replace the game route; it returns
    model-frame points [(x, y), ...] starting at the robot, or None to stop.
    """
    name = 'shimcheong'

    def __init__(self, policy=None, *, frame_source, model=DEFAULT_MODEL, device=None, adapter=None,
                 route_fn=None, physics='serbot_measured', v_max=MODEL_V_MAX, guard=True, session='sim'):
        if not callable(frame_source):
            raise ValueError('frame_source must be callable, e.g. BlankFrames() or SyncCameraFrames(robot)')
        if route_fn is not None and not callable(route_fn):
            raise ValueError('route_fn must be callable')
        if not isinstance(guard, bool):
            raise ValueError('guard must be a bool')
        self.physics = validate_physics(physics)
        v_max = float(v_max)
        if not math.isfinite(v_max) or v_max <= 0:
            raise ValueError('v_max must be positive')
        self.v_max = min(v_max, self.physics['max_linear'])
        self.w_max = self.physics['max_angular']
        self.frame_source, self.route_fn, self.guard, self.session = frame_source, route_fn, guard, session
        self._policy, self._model, self._device, self._adapter = policy, model, device, adapter
        self.model_version = getattr(policy, 'model_version', 'injected') if policy is not None else \
            'simcheongi:'+str(model)+(':'+str(adapter) if adapter else '')
        self._red_light = RedLightController()
        self.target_id = None
        self.looking = True

    @property
    def policy(self):
        if self._policy is None:
            self._policy = load_policy(self._model, self._device, self._adapter)
        return self._policy

    def reset(self, seed=None):
        self.policy.reset(self.session)      # loads the model on first use
        self._red_light.reset(seed)
        self.target_id = None
        self.looking = True
        self.poses = []                      # (t, x, y, unwrapped yaw) at every predict call
        self.frames = []                     # (t, frame) taken at decisions
        self.plan = None
        self.decided_at = None
        self.decisions = 0
        self.latencies = []
        self.last_request = None

    # ------------------------------------------------------------------ inputs
    def _record_pose(self, t, x, y, yaw):
        if self.poses:
            last = self.poses[-1]
            yaw = last[3]+_wrap(yaw-last[3])
            if t <= last[0]+1e-9:
                self.poses[-1] = (last[0], x, y, yaw)
                return
        self.poses.append((t, x, y, yaw))
        horizon = self.poses[-1][0]-(HISTORY_ROWS+2)*HISTORY_DT_S
        while len(self.poses) > 2 and self.poses[1][0] < horizon:
            self.poses.pop(0)

    def _pose_at(self, t):
        poses = self.poses
        if t <= poses[0][0]:
            return poses[0][1:]
        for (t0, *a), (t1, *b) in zip(poses, poses[1:]):
            if t <= t1+1e-9:
                f = 0. if t1 <= t0 else min(1., max(0., (t-t0)/(t1-t0)))
                return tuple(p+(q-p)*f for p, q in zip(a, b))
        return poses[-1][1:]

    def ego_history(self, t0):
        """(n, 4) rows (t, x, y, yaw) on the 0.1 s grid ending at t0, oldest first."""
        rows = []
        for k in range(HISTORY_ROWS):
            t = round(t0-k*HISTORY_DT_S, 6)
            if t < self.poses[0][0]-1e-6:
                break
            rows.append((t, *self._pose_at(t)))
        return rows[::-1]

    def _frame_at(self, t):
        chosen = self.frames[0][1]
        for time_, frame in self.frames:
            if time_ <= t+1e-6:
                chosen = frame
        return chosen

    def game_route(self, observation, pose):
        """Straight route from the robot to the nearest eligible child (0.3 m target hysteresis)."""
        mode = observation['game']['mode']
        candidates = [c for c, mask in zip(observation['children'], observation['child_mask'])
                      if mask and c['state'] in ELIGIBLE_STATES[mode]]
        if not candidates:
            self.target_id = None
            return None
        target = min(candidates, key=lambda c: (c['distance']-(.3 if c['id'] == self.target_id else 0.), c['id']))
        self.target_id = target['id']
        robot = observation['robot']
        h, right, forward = robot['heading'], target['relative_x'], target['relative_z']
        cx = robot['x']+math.cos(h)*right-math.sin(h)*forward
        cz = robot['z']+math.sin(h)*right+math.cos(h)*forward
        return [(pose[0], pose[1]), serbot_sensors.to_model_frame(cx, cz)]

    # ------------------------------------------------------------------ control
    def _stop(self):
        self.plan = None
        return MotionAction(guard=self.guard)

    def predict(self, observation):
        if observation.get('schema_version') != SCHEMA_VERSION:
            raise ValueError('unsupported observation schema_version')
        sensors = observation.get('serbot')
        if not isinstance(sensors, dict) or sensors.get('schema') != serbot_sensors.SCHEMA:
            raise ValueError('ShimcheongController needs serbot_sensors=True '
                             '(PlayEnv, evaluate --serbot-sensors or HTTP training_reset)')
        t = float(observation['time'])
        pose = (sensors['pose']['x'], sensors['pose']['y'], sensors['pose']['yaw'])
        self._record_pose(t, *pose)
        game = observation['game']
        mode = game['mode']
        if mode not in ACTIVE_PHASES:
            raise ValueError('unsupported game: '+str(mode))
        if game['held'] or game['phase'] not in ACTIVE_PHASES[mode]:
            self.target_id = None
            return self._stop()
        if mode == 'red_light' and game['phase'] == 'approaching':
            # The planner has no gaze skill: the rule baseline turns, clipped to the robot's turn rate.
            action = self._red_light.predict(observation)
            self.looking, self.target_id = self._red_light.looking, None
            self.plan = None
            w = max(-self.w_max, min(self.w_max, action.angular_rps))
            return MotionAction(0., w, guard=self.guard)
        route = self.route_fn(observation, pose) if self.route_fn is not None else self.game_route(observation, pose)
        if route is None:
            return self._stop()
        if self.decided_at is None or t-self.decided_at >= DECISION_PERIOD_S-1e-6:
            self._decide(observation, t, pose, route, sensors)
        return self._follow(pose)

    def _decide(self, observation, t, pose, route, sensors):
        self.frames.append((t, self.frame_source(observation)))
        self.frames = [item for item in self.frames if item[0] >= t-HISTORY_OFFSETS_S[0]-DECISION_PERIOD_S-1e-6]
        frames = [self._frame_at(t-offset) for offset in HISTORY_OFFSETS_S]
        history = self.ego_history(t)
        self.last_request = dict(time=t, tick=observation['tick'], history=history, route=route)
        result = self.policy.plan(frames, sensors['lidar_m'], history, route,
                                  ultrasonic=sensors['ultrasonic_m'], session=self.session)
        path = [(float(p[0]), float(p[1])) for p in result.trajectory_world]
        self.plan = dict(path=[(pose[0], pose[1])]+path, cursor=0.,
                         speed=min(self.v_max, max(0., float(result.speed_hint))))
        self.decided_at = t
        self.decisions += 1
        latency = getattr(result, 'latency_s', None)
        if isinstance(latency, (int, float)):
            self.latencies.append(float(latency))

    def _follow(self, pose):
        """Pure pursuit on the last plan, as the robot driver follows a model path."""
        if self.plan is None:
            return MotionAction(guard=self.guard)
        path, x, y, yaw = self.plan['path'], *pose
        lengths = [math.hypot(b[0]-a[0], b[1]-a[1]) for a, b in zip(path, path[1:])]
        total = sum(lengths)
        if total < PATH_MIN_M or self.plan['speed'] < V_GO_MIN:
            return MotionAction(guard=self.guard)
        best, arc = (math.inf, self.plan['cursor']), 0.
        for (a, b), length in zip(zip(path, path[1:]), lengths):
            if arc+length >= self.plan['cursor']-.05 and length > 1e-9:
                f = max(0., min(1., ((x-a[0])*(b[0]-a[0])+(y-a[1])*(b[1]-a[1]))/(length*length)))
                d = math.hypot(a[0]+f*(b[0]-a[0])-x, a[1]+f*(b[1]-a[1])-y)
                if d < best[0]:
                    best = (d, arc+f*length)
            arc += length
        self.plan['cursor'] = s = max(self.plan['cursor'], best[1])
        if total-s < PATH_END_M:
            return MotionAction(guard=self.guard)
        goal, arc = path[-1], 0.
        for (a, b), length in zip(zip(path, path[1:]), lengths):
            if arc+length >= s+LOOKAHEAD_M and length > 1e-9:
                f = (s+LOOKAHEAD_M-arc)/length
                goal = (a[0]+f*(b[0]-a[0]), a[1]+f*(b[1]-a[1]))
                break
            arc += length
        dx, dy = goal[0]-x, goal[1]-y
        fx, fy = math.cos(yaw)*dx+math.sin(yaw)*dy, -math.sin(yaw)*dx+math.cos(yaw)*dy
        alpha = math.atan2(fy, fx)
        if abs(alpha) > math.radians(ALIGN_DEG):
            return MotionAction(0., math.copysign(self.w_max, alpha), guard=self.guard)
        kappa = 2*math.sin(alpha)/max(math.hypot(fx, fy), LOOKAHEAD_MIN_M)
        v = self.plan['speed']
        w = v*kappa
        if abs(w) > self.w_max:
            v, w = self.w_max/abs(kappa), math.copysign(self.w_max, w)
        return MotionAction(v, w, guard=self.guard)


def create_controller():
    """Factory for controller_client / evaluate: blank frames, model from SIMCHEONGI_MODEL."""
    return ShimcheongController(model=os.environ.get('SIMCHEONGI_MODEL', DEFAULT_MODEL),
                                device=os.environ.get('SIMCHEONGI_DEVICE') or None, frame_source=BlankFrames())


def _summary(controller, info, args, terminated, truncated):
    latencies = controller.latencies
    return dict(game=args.game, frames=args.frames, seed=args.seed, decisions=controller.decisions,
                model_version=controller.model_version, terminated=terminated, truncated=truncated,
                end_reason=info.get('end_reason'), metrics=info.get('metrics', {}),
                median_latency_s=statistics.median(latencies) if latencies else None)


def main():
    parser = argparse.ArgumentParser(description='심청이 주행 모델을 게임 제어기로 한 판 연결')
    parser.add_argument('--game', choices=tuple(ACTIVE_PHASES), default='tag')
    parser.add_argument('--frames', choices=('blank', 'sync'), default='blank',
                        help='blank: 서버 없이 회색 영상, sync: 서버와 열린 브라우저 탭의 tick 동기 영상')
    parser.add_argument('--model', default=DEFAULT_MODEL, help='Hugging Face 저장소 이름 또는 로컬 폴더')
    parser.add_argument('--adapter', default=None, help='선택: LoRA 어댑터 폴더')
    parser.add_argument('--device', default=None, help='cpu 또는 cuda (생략 시 자동)')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--count', type=int, default=5)
    parser.add_argument('--time-limit', type=float, default=30.)
    parser.add_argument('--catch-distance', type=float, default=.85,
                        help='잡힘 중심 거리(m). 가드가 켜진 로봇이 접촉 없이 잡을 수 있게 기본 0.85')
    parser.add_argument('--v-max', type=float, default=MODEL_V_MAX)
    args = parser.parse_args()
    settings = {'time_limit': args.time_limit, 'catch_distance': args.catch_distance}
    try:
        if args.frames == 'blank':
            from simulator.environment import PlayEnv
            controller = ShimcheongController(model=args.model, adapter=args.adapter, device=args.device,
                                              frame_source=BlankFrames(), v_max=args.v_max)
            env = PlayEnv(game=args.game, controller=controller, physics='serbot_measured', serbot_sensors=True)
            try:
                env.reset(seed=args.seed, count=args.count, settings=settings)
                terminated = truncated = False
                while not (terminated or truncated):
                    _, _, terminated, truncated, info = env.step()
            finally:
                env.close()
        else:
            from simulator.client import SimRobot
            robot = SimRobot()
            controller = ShimcheongController(model=args.model, adapter=args.adapter, device=args.device,
                                              frame_source=SyncCameraFrames(robot), v_max=args.v_max)
            controller.reset(args.seed)       # load the model before the stepped session starts
            try:
                result = robot.training_reset(mode=args.game, seed=args.seed, count=args.count, dt=.1,
                                              settings=settings, physics='serbot_measured', serbot_sensors=True)
                controller.reset(args.seed)
                observation, info = result['observation'], result['info']
                terminated = truncated = False
                while not (terminated or truncated):
                    step = robot.training_step(controller.predict(observation))
                    observation, info = step['observation'], step['info']
                    terminated, truncated = step['terminated'], step['truncated']
            finally:
                robot.training_close()
        print(json.dumps(_summary(controller, info, args, terminated, truncated),
                         ensure_ascii=False, allow_nan=False, indent=2))
    except (ValueError, ImportError, RuntimeError) as exc:
        parser.exit(1, str(exc)+'\n')


if __name__ == '__main__':
    main()
