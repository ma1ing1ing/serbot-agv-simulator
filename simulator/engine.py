"""Deterministic, metre/radian based world shared by the UI and Python clients."""
from __future__ import annotations

import copy
import math
from pathlib import Path
import threading
import uuid

from . import games, replay, scenarios
from .contracts import MotionAction, make_observation
from .controllers import RuleController
from .motion import integrate, validate_physics
from . import recording as episode_recording


def number(value, low, high, name):
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name}: {low} ~ {high} 범위의 유한한 수를 입력하세요")
    return value


class World:
    radius = 0.39
    touch_distance = 0.74  # Robot/child bodies plus a short arm-reach margin.
    home_z = 3.2
    bounds = (-5.5, 5.5, -4.5, 4.5)
    palette = ['#e9aa50', '#5c9e91', '#7e89c9', '#d57c77', '#a3ad6e', '#659dc0', '#c08ab3', '#ae8d65']

    def __init__(self, record_root=None):
        self.record_root = Path(record_root or Path(__file__).resolve().parents[1]/'artifacts/episodes')
        self.episode = None
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        with self.lock:
            if self.episode is not None and not self.episode.closed:
                self.finish_game('reset')
            self.episode = None
            self.observation = None
            self.external_detections = []
            self.external_detection_time = None
            self.execution_mode = 'realtime'
            self.training_action = None
            self.physics = validate_physics()
            self.controller = RuleController()
            self.controller_name = 'manual'
            self.controller_observation_mode = 'oracle'
            self.scenario = None
            self.requested_action = MotionAction().to_dict()
            self.action_input = None
            self.action_received_tick = 0
            self.control_dt = .02
            self.metrics = dict(min_distance=None, blocked_attempts=0, near_miss_steps=0,
                                angular_change=0., linear_change=0., max_abs_acceleration=0.,
                                max_abs_angular_acceleration=0., samples=0, reward_total=0., administrative_stops=0, emergency_stops=0,
                                max_emergency_deceleration=0.)
            self.frame = 0
            self.accumulator = 0.
            self.contacts = set()
            self.rules = dict(games.DEFAULTS)
            self.touch_distance = games.DEFAULTS['catch_distance']
            self.epoch = uuid.uuid4().hex
            self.time = 0.0
            self.paused = False
            self.rate = 1.0
            self.robot = dict(x=0.0, z=-3.35, heading=0.0, linear=0.0, angular=0.0, vx=0., vz=0.)
            self.motion = None
            self.last_command = None
            self.command_results = {}
            self.distance = 0.0
            self.speech = ''
            self.speech_id = 0
            self.logs = []
            self.trail = [[0.0, -3.35]]
            self.children = []
            self.replay = None
            self.game = dict(mode='tag', phase='ready', touched_by=None, touched_at=None,
                             escaped_ids=[], caught_ids=[], held=False, auto_chase=True, target_id=None)
            self.obstacles = []
            self.set_count(5)
            self.log('가상 환경 준비 · 실제 로봇에 연결하지 않습니다')

    def log(self, message):
        self.logs.append(dict(time=round(self.time, 2), message=message))
        self.logs = self.logs[-100:]

    def set_count(self, count):
        count = int(number(count, 1, 8, 'count'))
        with self.lock:
            if self.replay is not None or self.game['phase'] in ('approaching', 'escaping', 'chasing'):
                raise ValueError('진행 중인 게임에서는 인원을 바꿀 수 없습니다. 환경을 초기화하세요.')
            old = {c['id']: c for c in self.children}
            self.children = [old.get(i, dict(id=i, name=f'아이 {i+1}', x=(i-(count-1)/2)*0.95,
                z=1.1+(i % 2)*0.95, heading=math.pi, mode='still', moving=False,
                pace=0.48+(i % 3)*0.09, phase=i*1.7, color=self.palette[i], height=1.12+(i % 3)*0.08,
                direction=-1, wave=False, caught=False, speed=0.0, vx=0., vz=0., motion_time=i*.17, motion_kind='idle')) for i in range(count)]

    def set_child(self, child_id, mode):
        if mode not in ('still', 'walk', 'intermittent', 'wiggle'):
            raise ValueError('mode: still, walk, intermittent, wiggle')
        with self.lock:
            if self.replay is not None:
                raise ValueError('기록 재생에서는 아이별 행동을 바꿀 수 없습니다. 다른 놀이 모드를 시작하세요.')
            if self.game['phase']=='chasing':
                raise ValueError('술래잡기 중에는 아이들이 스스로 도망갑니다. 전체 잠깐 멈춤을 사용하세요.')
            if self.game['phase'] in ('escaping', 'finished'):
                raise ValueError('터치 후에는 모두 출발선으로 도망갑니다. 새 게임에서 행동을 바꿔 주세요.')
            child = next((c for c in self.children if c['id'] == int(child_id)), None)
            if child is None:
                raise ValueError('참가자를 찾을 수 없습니다')
            child['mode'] = mode
            self.log(f"{child['name']} · {dict(still='멈춤',walk='걷기',intermittent='걷다 멈춤',wiggle='제자리 움직임')[mode]}")

    def start_game(self, mode='tag', auto_chase=True, *, replay_count=16, clip_id='active',
                   seed=0, settings=None, record=False, record_dir=None, split='interactive',
                   scenario='open', physics=None, observation_mode='oracle', count=None,
                   execution_mode='realtime', control_dt=.02, controller_name=None):
        config = games.options(mode, seed, settings) if mode != 'playground_a' else None
        physical = validate_physics(physics)
        if controller_name is not None and (not isinstance(controller_name,str) or not controller_name or len(controller_name)>120):
            raise ValueError('controller_name must be a short nonempty string')
        group_count = min(len(self.children),8) if count is None else count
        if isinstance(group_count,bool) or not isinstance(group_count,int) or not 1 <= group_count <= 8:
            raise ValueError('count: 1..8 integer')
        if execution_mode not in ('realtime','stepped'):
            raise ValueError('execution_mode: realtime or stepped')
        control_dt = number(control_dt,.02,1.,'control_dt')
        if abs(control_dt/.02-round(control_dt/.02)) > 1e-8:
            raise ValueError('control_dt must be a multiple of .02')
        if observation_mode not in ('oracle', 'sensor'):
            raise ValueError('observation_mode: oracle or sensor')
        scenario = 'open' if scenario is None else scenario
        prepared = scenarios.prepare_scenario(scenario, group_count, seed, game=mode) if mode != 'playground_a' else None
        if not isinstance(record, bool):
            raise ValueError('record는 bool이어야 합니다')
        if split not in ('train', 'validation', 'test', 'interactive'):
            raise ValueError('split: train, validation, test, interactive')
        directory = Path(record_dir) if record_dir is not None else self.record_root/f'{mode}-{seed}-{uuid.uuid4().hex[:12]}'
        if record and directory.exists():
            raise ValueError('기록 폴더가 이미 존재합니다')
        if mode=='playground_a':
            recording=replay.load()
            count=int(number(replay_count,1,len(recording.tracks),'replay_count'))
            playback=replay.Playback(recording,clip_id,count)
            with self.lock:
                self.reset()
                self.set_count(min(count,8))
                templates=copy.deepcopy(self.children)
                self.children=[]
                for i,ident in enumerate(playback.ids):
                    child=copy.deepcopy(templates[i%len(templates)])
                    colors=self.palette+['#bc6645','#608455','#995d83','#4a8b96','#be9d3b','#6d6fa7','#96754c','#619c82']
                    child.update(id=i,source_id=ident,name=f'기록 {ident}',color=colors[i%len(colors)],
                                 phase=i*1.7,mode='walk',visible=False,trail=[],segment_id=None,display_scale=.6)
                    self.children.append(child)
                self.replay=playback
                self.rate=8.0
                self.game.update(mode=mode,phase='replaying',auto_chase=False,target_id=None)
                playback.update(self)
                self.log('Playground A 기록 재생 · 공간 맞춤 · 8× · 술래 역할/로봇 반응 없음')
            return
        with self.lock:
            count, rate = group_count, min(self.rate,4.0)
            self.reset()
            self.set_count(count)
            self.rate = rate
            self.game['mode'] = mode
            games.start(self, mode, auto_chase, seed, config)
            self.physics = physical
            self.execution_mode = execution_mode
            self.control_dt = control_dt
            self.controller_observation_mode = observation_mode
            self.controller.reset(seed)
            self.controller_name = controller_name or ('rule' if auto_chase else 'external_or_manual')
            if prepared is not None:
                scenarios.apply_scenario(self, prepared, seed)
                for child, behavior in zip(self.children, prepared['behavior_types']):
                    games.apply_behavior(child, config['child_behavior'] if config['child_behavior'] != 'mixed' else behavior)
            self.episode = episode_recording.Episode(self, directory if record else None, split=split)
            self.emit('episode_start', mode=mode)
            self.episode.update(self, {})

    def emit(self, kind, actor=None, target=None, **details):
        if self.episode is not None:
            self.episode.event(self, kind, actor, target, **details)
        labels = dict(freeze='얼음', thaw='얼음 해제', movement_detected='움직임 적발 · 탈락',
                      stop_response='시선에 반응해 정지', escape='출발선 도착')
        if kind in labels:
            ident = target if isinstance(target, int) else actor
            self.log((f'아이 {ident+1} · ' if isinstance(ident, int) else '')+labels[kind])

    def contact(self, actor, target, blocked):
        key = (actor, target)
        if blocked and key not in self.contacts:
            self.emit('collision_prevented', actor=actor, target=target, reason='body_clearance')
            if actor == 'robot':
                self.metrics['blocked_attempts'] += 1
        if blocked:
            self.contacts.add(key)
        else:
            self.contacts.discard(key)

    def finish_game(self, reason='user_stopped'):
        with self.lock:
            if self.replay is None and self.game['phase'] not in ('ready', 'finished'):
                games.finish(self, reason)
            if self.episode is not None and not self.episode.closed:
                self.episode.sample(self)
                self.episode.close(self)

    def note_observation(self, value, source='external'):
        if not isinstance(value, dict) or not isinstance(source, str):
            raise ValueError('observation은 객체, source는 문자열이어야 합니다')
        import json
        json.dumps(value, allow_nan=False)
        with self.lock:
            if self.episode is None or self.episode.closed:
                raise ValueError('진행 중인 게임이 필요합니다')
            self.episode.observation = dict(source=source[:80], time=self.time, tick=self.frame, value=copy.deepcopy(value))

    def hold_game(self, held):
        with self.lock:
            if self.replay is not None:
                self.game['held'] = bool(held)
                self.replay.update(self)
                return
            if self.game['phase'] in ('ready', 'finished'):
                raise ValueError('진행 중인 게임이 필요합니다')
            self.game['held'] = bool(held)
            if held:
                self.finish_motion('held')
                for c in self.children:
                    games.stop(c)
            self.emit('hold_change', held=bool(held))
            self.log('놀이 잠깐 멈춤' if held else '놀이 계속')

    def seek_replay(self, elapsed):
        with self.lock:
            if self.replay is None:
                raise ValueError('Playground A 기록을 먼저 시작하세요')
            elapsed=number(elapsed,0,self.replay.clip['duration'],'elapsed')
            self.replay.seek(self,elapsed)

    def check_touch(self):
        if self.replay is None and self.game['phase'] not in ('ready', 'finished'):
            games.check_touch(self)

    def robot_watching(self, child):
        """Front hemisphere (including directly sideways) means freeze.

        This is a geometric world rule, not an AI/camera inference. Heading 0
        faces +Z; positive heading rotates left toward -X.
        """
        dx, dz = child['x']-self.robot['x'], child['z']-self.robot['z']
        heading = self.robot['heading']
        return -math.sin(heading)*dx+math.cos(heading)*dz >= -1e-9

    def _advance_game_children(self, dt):
        if self.replay is not None:
            self.replay.update(self, dt)
        else:
            games.advance_children(self, dt)

    def finish_motion(self, reason, *, emergency=True):
        if self.motion:
            result = dict(id=self.motion['id'], status=reason, time=round(self.time, 3))
            self.command_results[result['id']] = result
            self.command_results = dict(list(self.command_results.items())[-100:])
            self.last_command = result
            self.motion = None
        if emergency:
            if abs(self.robot['linear'])+abs(self.robot['angular']) > 1e-9:
                self.metrics['administrative_stops'] += 1
            self.robot['linear'] = self.robot['angular'] = self.robot['vx'] = self.robot['vz'] = 0.0

    def command(self, linear, angular, seconds, guard=True):
        linear = number(linear, -0.5, 0.5, 'linear_mps')
        angular = number(angular, -3.0, 3.0, 'angular_rps')
        seconds = number(seconds, 0.02, 30.0, 'seconds')
        with self.lock:
            if self.execution_mode == 'stepped':
                raise ValueError('use PlayEnv.step() or training_step() in stepped mode')
            self.game['auto_chase'] = False
            self.controller_name = 'external_or_manual'
            self.action_received_tick = self.frame
            self.action_input = copy.deepcopy(self.episode.observation) if self.episode is not None else None
            self.observation = None
            self.emit('robot_command', actor='robot', linear=linear, angular=angular, seconds=seconds, guard=bool(guard))
            self.finish_motion('superseded', emergency=False)
            command_id = uuid.uuid4().hex
            self.motion = dict(id=command_id, end=self.time+seconds, linear=linear, angular=angular, guard=bool(guard))
            self.log(f'주행 명령 · {linear:+.2f} m/s · {angular:+.2f} rad/s · {seconds:g}s')
            return dict(id=command_id, epoch=self.epoch, status='running')

    def clearance(self, x, z, exclude_child=None):
        xmin, xmax, zmin, zmax = self.bounds
        distances = [x-xmin, xmax-x, z-zmin, zmax-z]
        for b in self.obstacles:
            dx = max(abs(x-b['x'])-b['w']/2, 0)
            dz = max(abs(z-b['z'])-b['d']/2, 0)
            distances.append(math.hypot(dx, dz))
        for c in self.children:
            if c['id'] != exclude_child and c.get('visible',True):
                distances.append(math.hypot(x-c['x'], z-c['z'])-0.22)
        return min(distances)

    def ray(self, angle, max_range=8.0):
        r = self.robot
        for i in range(1, int(max_range/.04)+1):
            d = i*.04
            if self.clearance(r['x']-math.sin(angle)*d, r['z']+math.cos(angle)*d) < .015:
                return round(max(0, d-self.radius), 3)
        return max_range-self.radius

    def ultrasonic(self):
        with self.lock:
            h = self.robot['heading']
            return dict(front_min_cm=round(self.ray(h)*100, 1), rear_min_cm=round(self.ray(h+math.pi)*100, 1),
                        left_min_cm=round(self.ray(h+math.pi/2)*100, 1), right_min_cm=round(self.ray(h-math.pi/2)*100, 1), simulated=True)

    def lidar(self):
        with self.lock:
            inc = 2*math.pi/72
            return dict(ok=True, simulated=True, angle_min=0, angle_max=2*math.pi-inc,
                        angle_increment=inc, range_min=0, range_max=8, ranges=[self.ray(self.robot['heading']+i*inc) for i in range(72)])

    def observe(self, mode='oracle'):
        with self.lock:
            return make_observation(self, mode)

    def set_controller(self, controller, *, observation_mode='oracle'):
        if observation_mode not in ('oracle', 'sensor') or not callable(getattr(controller, 'predict', None)) or not callable(getattr(controller, 'reset', None)):
            raise ValueError('controller must provide reset(seed) and predict(observation)')
        with self.lock:
            if self.execution_mode == 'stepped':
                raise ValueError('configure the PlayEnv controller before reset')
            controller.reset(self.game.get('seed', 0))
            self.controller = controller
            self.controller_observation_mode = observation_mode
            self.finish_motion('superseded', emergency=False)
            self.game['auto_chase'] = True
            self.controller_name = getattr(controller,'name',controller.__class__.__name__)
            self.emit('controller_change',actor='robot',controller=self.controller_name,automatic=True)

    def controller_intent(self, controller):
        self.controller_name = getattr(controller,'name',controller.__class__.__name__)
        target = getattr(controller,'target_id',None)
        if target != self.game.get('target_id'):
            self.emit('target_change',actor='robot',target=target,previous=self.game.get('target_id'))
        self.game['target_id'] = target
        looking = getattr(controller,'looking',self.game.get('looking'))
        if looking != self.game.get('looking'):
            self.game['looking'] = looking
            self.emit('gaze_turn',actor='robot',looking=looking)

    def set_detections(self, detections):
        # Validate the complete input before installing it.
        with self.lock:
            checked = make_observation(self, 'sensor', detections=detections)
            self.external_detections = copy.deepcopy(detections)
            self.external_detection_time = self.time
            return checked

    def tick(self, wall_dt):
        with self.lock:
            if self.paused or self.execution_mode != 'realtime':
                return
            self.accumulator += min(max(wall_dt, 0), .05)*self.rate
            while self.accumulator >= .02-1e-10:
                self.accumulator = max(0., self.accumulator-.02)
                self._advance_one()

    def advance(self, action, ticks=5):
        action = MotionAction.from_value(action)
        if isinstance(ticks, bool) or not isinstance(ticks, int) or not 1 <= ticks <= 500:
            raise ValueError('ticks: 1..500 integer')
        with self.lock:
            if self.execution_mode != 'stepped':
                raise ValueError('explicit stepping requires stepped execution mode')
            if self.paused or self.game['held']:
                raise ValueError('resume the environment before stepping')
            if self.replay is not None or self.game['phase'] in ('ready','finished'):
                raise ValueError('reset an active game before stepping')
            self.training_action = action
            self.requested_action = action.to_dict()
            self.action_received_tick = self.frame
            self.control_dt = ticks*.02
            self.action_input = copy.deepcopy(self.observation)
            try:
                for _ in range(ticks):
                    self._advance_one()
                    if self.game['phase'] == 'finished':
                        break
            finally:
                self.training_action = None

    def _advance_one(self):
        dt = .02
        was_finished = self.game['phase'] == 'finished'
        previous = {'robot':dict(self.robot), **{c['id']:dict(c) for c in self.children}}
        action = self.training_action
        automatic = self.execution_mode == 'realtime' and self.game.get('auto_chase') and self.replay is None and self.game['phase'] not in ('ready','finished') and not self.game['held'] and self.motion is None
        self.last_motion_status = None
        if automatic:
            self.observation = make_observation(self, self.controller_observation_mode)
            self.action_input = copy.deepcopy(self.observation)
            self.action_received_tick = self.frame
            try:
                action = MotionAction.from_value(self.controller.predict(copy.deepcopy(self.observation)))
            except Exception:
                self.finish_game('controller_error')
                self.game['auto_chase'] = False
                self.log('제어기 오류 · 게임을 멈췄습니다')
                return
            self.controller_intent(self.controller)
        if action is not None:
            self.requested_action = action.to_dict()
        self.frame += 1
        self.time = round(self.time+dt, 9)
        game_active = self.game['phase'] != 'ready'
        if game_active:
            self._advance_game_children(dt)
        else:
            self._idle_children(dt)
        if game_active and (self.game['held'] or self.game['phase'] == 'finished'):
            action = None
        elif self.motion is not None:
            command = self.motion
            remaining = max(0., command['end']-(self.time-dt))
            requested = MotionAction(command['linear'], command['angular'], command['guard'])
            action = requested if remaining > 1e-9 else MotionAction(guard=command['guard'])
            self.requested_action = action.to_dict()
            duration = min(dt, remaining)
            reason = integrate(self, action, duration if duration > 1e-9 else dt, self.physics)
            if duration > 1e-9 and duration < dt and reason is None:
                reason = integrate(self, MotionAction(guard=command['guard']), dt-duration, self.physics)
            self.last_motion_status = reason
            if reason or (self.time >= command['end']-1e-9 and abs(self.robot['linear']) < 1e-9 and abs(self.robot['angular']) < 1e-9):
                self.finish_motion(reason or 'completed')
            action = None
        elif action is not None or abs(self.robot['linear']) > 1e-9 or abs(self.robot['angular']) > 1e-9:
            action = action or MotionAction()
            self.requested_action = action.to_dict()
            self.last_motion_status = integrate(self, action, dt, self.physics)
        if game_active:
            self.check_touch()
        for ident, actor in [('robot',self.robot)]+[(c['id'],c) for c in self.children]:
            old = previous[ident]
            actor['vx'] = (actor['x']-old['x'])/dt
            actor['vz'] = (actor['z']-old['z'])/dt
        if not was_finished:
            self._update_metrics(previous['robot'],dt)
        if self.episode is not None:
            self.episode.update(self,previous)
        if math.hypot(self.trail[-1][0]-self.robot['x'],self.trail[-1][1]-self.robot['z']) > .035:
            self.trail.append([self.robot['x'],self.robot['z']])
            self.trail = self.trail[-1500:]

    def _idle_children(self, dt):
        for c in self.children:
            elapsed = self.time+c['phase']
            moving = c['mode']=='walk' or (c['mode']=='intermittent' and elapsed % 5 < 2.7)
            c['moving'] = moving or c['mode']=='wiggle'
            c['wave'] = c['mode']=='wiggle'
            if moving:
                target = c['z']+c['direction']*c['pace']*dt
                if target < -1.9 or target > 3.2:
                    c['direction'] *= -1
                elif math.hypot(c['x']-self.robot['x'],target-self.robot['z']) > self.radius+.3 and all(o['id']==c['id'] or math.hypot(c['x']-o['x'],target-o['z'])>.45 for o in self.children):
                    c['z'] = target
                c['heading'] = math.pi if c['direction'] < 0 else 0

    def _update_metrics(self, previous, dt):
        if self.game['held']:
            return
        m = self.metrics
        m['samples'] += 1
        distances = [games.distance(c,self.robot) for c in self.children if c.get('visible',True)]
        if distances:
            nearest = min(distances)
            m['min_distance'] = nearest if m['min_distance'] is None else min(m['min_distance'],nearest)
            m['near_miss_steps'] += int(nearest < .8)
        # Game end/hold/explicit stop are administrative stops, not ordinary
        # controller acceleration. Report geometric emergency braking separately.
        dv = abs(self.robot['linear']-previous['linear'])
        dw = abs(self.robot['angular']-previous['angular'])
        if self.game['phase'] == 'finished' or self.game['held']:
            return
        if self.last_motion_status in ('collision','guard'):
            m['emergency_stops'] += 1
            m['max_emergency_deceleration'] = max(m['max_emergency_deceleration'],dv/dt)
            return
        m['linear_change'] += dv
        m['angular_change'] += dw
        m['max_abs_acceleration'] = max(m['max_abs_acceleration'],dv/dt)
        m['max_abs_angular_acceleration'] = max(m['max_abs_angular_acceleration'],dw/dt)

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(dict(epoch=self.epoch,time=round(self.time,3),paused=self.paused,rate=self.rate,
                robot=self.robot,children=self.children,obstacles=self.obstacles,distance=round(self.distance,3),
                motion=self.motion,last_command=self.last_command,speech=self.speech,speech_id=self.speech_id,
                logs=self.logs,trail=self.trail,ultrasonic=self.ultrasonic(),bounds=self.bounds,game=self.game,
                replay=self.replay.snapshot() if self.replay is not None else None,
                episode=self.episode.metadata() if self.episode is not None else None,
                execution_mode=self.execution_mode,metrics=self.metrics,physics=self.physics,scenario=self.scenario))
