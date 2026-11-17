"""Deterministic, metre/radian based world shared by the UI and Python clients."""
from __future__ import annotations

import copy
import math
import threading
import uuid


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

    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        with self.lock:
            self.epoch = uuid.uuid4().hex
            self.time = 0.0
            self.paused = False
            self.rate = 1.0
            self.robot = dict(x=0.0, z=-3.35, heading=0.0, linear=0.0, angular=0.0)
            self.motion = None
            self.last_command = None
            self.command_results = {}
            self.distance = 0.0
            self.speech = ''
            self.speech_id = 0
            self.logs = []
            self.trail = [[0.0, -3.35]]
            self.children = []
            self.game = dict(phase='ready', touched_by=None, touched_at=None, escaped_ids=[], held=False)
            self.obstacles = [dict(x=-4.5, z=0.5, w=0.7, d=1.6), dict(x=4.5, z=0.5, w=0.7, d=1.6)]
            self.set_count(5)
            self.log('가상 환경 준비 · 실제 로봇에 연결하지 않습니다')

    def log(self, message):
        self.logs.append(dict(time=round(self.time, 2), message=message))
        self.logs = self.logs[-100:]

    def set_count(self, count):
        count = int(number(count, 1, 8, 'count'))
        with self.lock:
            if self.game['phase'] in ('approaching', 'escaping'):
                raise ValueError('진행 중인 게임에서는 인원을 바꿀 수 없습니다. 환경을 초기화하세요.')
            old = {c['id']: c for c in self.children}
            self.children = [old.get(i, dict(id=i, name=f'아이 {i+1}', x=(i-(count-1)/2)*0.95,
                z=1.1+(i % 2)*0.95, heading=math.pi, mode='still', moving=False,
                pace=0.48+(i % 3)*0.09, phase=i*1.7, color=self.palette[i], height=1.12+(i % 3)*0.08,
                direction=-1, wave=False)) for i in range(count)]

    def set_child(self, child_id, mode):
        if mode not in ('still', 'walk', 'intermittent', 'wiggle'):
            raise ValueError('mode: still, walk, intermittent, wiggle')
        with self.lock:
            if self.game['phase'] in ('escaping', 'finished'):
                raise ValueError('터치 후에는 모두 출발선으로 도망갑니다. 새 게임에서 행동을 바꿔 주세요.')
            child = next((c for c in self.children if c['id'] == int(child_id)), None)
            if child is None:
                raise ValueError('참가자를 찾을 수 없습니다')
            child['mode'] = mode
            self.log(f"{child['name']} · {dict(still='멈춤',walk='걷기',intermittent='걷다 멈춤',wiggle='제자리 움직임')[mode]}")

    def start_game(self):
        with self.lock:
            count, rate = len(self.children), self.rate
            self.reset()
            self.set_count(count)
            self.rate = rate
            for i, c in enumerate(self.children):
                c.update(x=(i-(count-1)/2)*.95, z=self.home_z, heading=math.pi,
                         home_x=(i-(count-1)/2)*.95, mode='walk', escaped=False, running=False)
            self.game['phase'] = 'approaching'
            for c in self.children:
                c['watched'] = self.robot_watching(c)
            self.log('게임 시작 · 로봇이 뒤돌아 있으면 접근, 바라보면 정지')

    def hold_game(self, held):
        with self.lock:
            if self.game['phase'] != 'approaching':
                raise ValueError('아이들 접근을 멈추는 기능은 터치 전에만 사용할 수 있습니다')
            self.game['held'] = bool(held)
            self.log('아이들 접근 잠깐 멈춤' if held else '아이들 접근 계속')

    def check_touch(self):
        if self.game['phase'] != 'approaching':
            return
        touching = [c for c in self.children if math.hypot(c['x']-self.robot['x'], c['z']-self.robot['z']) <= self.touch_distance]
        if not touching:
            return
        child = min(touching, key=lambda c: (math.hypot(c['x']-self.robot['x'], c['z']-self.robot['z']), c['id']))
        self.game.update(phase='escaping', touched_by=child['id'], touched_at=self.time, held=False)
        for c in self.children:
            c.update(mode='walk', moving=True, wave=False, running=True, escaped=False)
        self.log(f"{child['name']} 술래 터치! · 모두 출발선으로 도망갑니다")

    def robot_watching(self, child):
        """Front hemisphere (including directly sideways) means freeze.

        This is a geometric world rule, not an AI/camera inference. Heading 0
        faces +Z; positive heading rotates left toward -X.
        """
        dx, dz = child['x']-self.robot['x'], child['z']-self.robot['z']
        heading = self.robot['heading']
        return -math.sin(heading)*dx+math.cos(heading)*dz >= -1e-9

    def _advance_game_children(self, dt):
        if self.game['phase'] == 'approaching':
            self.check_touch()
        # Touch is a whole-group transition; do not update only the touching child.
        for c in self.children:
            c['watched'] = self.robot_watching(c)
            if self.game['phase'] == 'finished' or c.get('escaped'):
                c.update(moving=False, running=False, wave=False)
                continue
            escaping = self.game['phase'] == 'escaping'
            can_approach = not self.game['held'] and not c['watched']
            moving = escaping or (can_approach and (c['mode']=='walk' or (c['mode']=='intermittent' and (self.time+c['phase'])%5 < 2.7)))
            c.update(moving=moving or (can_approach and c['mode']=='wiggle'), wave=not escaping and can_approach and c['mode']=='wiggle', running=escaping)
            if not moving:
                continue
            # Aim for slightly different points on the tagger instead of making
            # symmetric children deadlock while converging on the same centre.
            approach_x = self.robot['x']+max(-.6,min(.6,c['home_x']*.2))
            tx, tz = (c['home_x'], self.home_z) if escaping else (approach_x, self.robot['z'])
            dx, dz = tx-c['x'], tz-c['z']
            distance = math.hypot(dx,dz)
            speed = 1.2+c['pace']*.7 if escaping else c['pace']
            step = min(distance, speed*dt)
            if distance > .0001:
                x, z = c['x']+dx/distance*step, c['z']+dz/distance*step
                c['heading'] = math.atan2(dx,dz)
                clear_robot = math.hypot(x-self.robot['x'],z-self.robot['z']) > self.radius+.25
                clear_children = all(o['id']==c['id'] or math.hypot(x-o['x'],z-o['z'])>.45 for o in self.children)
                if clear_robot and clear_children and self.clearance(x,z,exclude_child=c['id'])>.20:
                    c.update(x=x,z=z)
            if escaping and math.hypot(c['home_x']-c['x'], self.home_z-c['z']) < .06:
                c.update(x=c['home_x'],z=self.home_z,escaped=True,moving=False,running=False,mode='still')
                self.game['escaped_ids'].append(c['id'])
                self.log(f"{c['name']} 출발선 도착")
        self.check_touch()
        if self.game['phase']=='escaping' and len(self.game['escaped_ids'])==len(self.children):
            self.game['phase']='finished'
            self.log('전원 출발선 도착 · 이번 게임이 끝났습니다')

    def finish_motion(self, reason):
        if self.motion:
            result = dict(id=self.motion['id'], status=reason, time=round(self.time, 3))
            self.command_results[result['id']] = result
            self.command_results = dict(list(self.command_results.items())[-100:])
            self.last_command = result
            self.motion = None
        self.robot['linear'] = self.robot['angular'] = 0.0

    def command(self, linear, angular, seconds, guard=True):
        linear = number(linear, -0.5, 0.5, 'linear_mps')
        angular = number(angular, -3.0, 3.0, 'angular_rps')
        seconds = number(seconds, 0.02, 30.0, 'seconds')
        with self.lock:
            self.finish_motion('superseded')
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
            if c['id'] != exclude_child:
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

    def tick(self, wall_dt):
        with self.lock:
            if self.paused:
                return
            dt = min(max(wall_dt, 0), .05)*self.rate
            self.time += dt
            game_active = self.game['phase'] != 'ready'
            if game_active:
                self._advance_game_children(dt)
            for c in ([] if game_active else self.children):
                elapsed = self.time+c['phase']
                moving = c['mode'] == 'walk' or (c['mode'] == 'intermittent' and elapsed % 5 < 2.7)
                c['moving'] = moving or c['mode'] == 'wiggle'
                c['wave'] = c['mode'] == 'wiggle'
                if moving:
                    target = c['z']+c['direction']*c['pace']*dt
                    if target < -1.9 or target > 3.2:
                        c['direction'] *= -1
                    else:
                        # Children do not pass through the robot or one another.
                        if math.hypot(c['x']-self.robot['x'], target-self.robot['z']) > self.radius+.3:
                            if all(o['id']==c['id'] or math.hypot(c['x']-o['x'],target-o['z'])>.45 for o in self.children):
                                c['z'] = target
                    c['heading'] = math.pi if c['direction'] < 0 else 0
            if not self.motion:
                return
            m = self.motion
            motion_dt = min(dt, max(0, m['end']-(self.time-dt)))
            v, w = m['linear'], m['angular']
            reason = None
            # Swept, small substeps prevent tunnelling at accelerated playback.
            steps = max(1, math.ceil(motion_dt/.01))
            for _ in range(steps):
                h = self.robot['heading']+w*motion_dt/steps/2
                x = self.robot['x']-math.sin(h)*v*motion_dt/steps
                z = self.robot['z']+math.cos(h)*v*motion_dt/steps
                if abs(v)>0 and self.clearance(x, z) < self.radius+.02:
                    reason = 'collision'
                    break
                if m['guard'] and abs(v)>0 and self.ray(self.robot['heading']+(math.pi if v<0 else 0)) < .20:
                    reason = 'guard'
                    break
                self.robot.update(x=x,z=z,heading=(self.robot['heading']+w*motion_dt/steps+math.pi)%(2*math.pi)-math.pi)
                self.distance += abs(v)*motion_dt/steps
            self.robot.update(linear=v,angular=w)
            if math.hypot(self.trail[-1][0]-self.robot['x'],self.trail[-1][1]-self.robot['z'])>.035:
                self.trail.append([self.robot['x'],self.robot['z']])
                self.trail=self.trail[-1500:]
            if reason or self.time >= m['end']:
                self.finish_motion(reason or 'completed')
                if reason:
                    self.log('가상 장애물 감지 · 주행 정지')
            self.check_touch()

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(dict(epoch=self.epoch,time=round(self.time,3),paused=self.paused,rate=self.rate,
                robot=self.robot,children=self.children,obstacles=self.obstacles,distance=round(self.distance,3),
                motion=self.motion,last_command=self.last_command,speech=self.speech,speech_id=self.speech_id,
                logs=self.logs,trail=self.trail,ultrasonic=self.ultrasonic(),bounds=self.bounds,game=self.game))
