"""Python adapter for the simulator. Never imports or contacts robot hardware."""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class SimulationError(RuntimeError):
    pass


class SimRobot:
    """Camera and motion interface for your own AI program.

    ``command_velocity`` uses m/s and rad/s. Familiar SerBot speed units use
    approximate conversion factors, not a measured AGV motor calibration.
    """
    def __init__(self, url=None, *, metres_per_speed=.025, radians_per_speed=.24):
        self.url=(url or os.environ.get('SERBOT_SIM_URL','http://127.0.0.1:8767')).rstrip('/')
        self.metres_per_speed=metres_per_speed
        self.radians_per_speed=radians_per_speed

    @classmethod
    def from_env(cls):
        return cls()

    def _request(self, path, data=None, *, binary=False):
        body=None if data is None else json.dumps(data,allow_nan=False).encode()
        request=Request(self.url+path,data=body,headers={'Content-Type':'application/json'})
        try:
            with urlopen(request,timeout=5) as response:
                raw=response.read()
                return raw if binary else json.loads(raw)
        except HTTPError as exc:
            try:
                detail=exc.read().decode(errors='replace')
            finally:
                exc.close()
            raise SimulationError(f'시뮬레이터 HTTP {exc.code}: {detail}') from exc
        except URLError as exc:
            raise SimulationError('시뮬레이터 서버를 먼저 실행하세요: python3 -m simulator.server') from exc

    def status(self):
        return self._request('/api/state')

    def camera_frame(self, output_path=None):
        """Actual 640×480 virtual camera JPEG; a fresh browser renderer is required."""
        frame=self._request('/api/camera.jpg',binary=True)
        if output_path is not None:
            path=Path(output_path)
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(frame)
        return frame

    def camera_metadata(self):
        return self._request('/api/camera/meta')

    @property
    def camera_stream_url(self):
        return self.url+'/api/camera/stream.mjpg'

    def command_velocity(self, linear_mps=0.0, angular_rps=0.0, *, seconds=.5, wait=True, guard=True, timeout=130):
        command=self._request('/api/robot/command',dict(linear_mps=linear_mps,angular_rps=angular_rps,seconds=seconds,guard=guard))
        if not wait:
            return command
        deadline=time.monotonic()+timeout
        try:
            while time.monotonic()<deadline:
                result=self._request('/api/command?'+urlencode({'id':command['id']}))
                if result['status']!='running':
                    if result['status']=='unknown':
                        raise SimulationError('환경이 재설정되었거나 명령 결과가 만료되었습니다')
                    return result
                time.sleep(.04)
            self.stop()
            raise SimulationError('명령 대기 시간 초과. 일시정지 상태를 확인하세요.')
        except KeyboardInterrupt:
            self.stop()
            raise

    def stop(self):
        return self._request('/api/robot/stop',{})

    def start_game(self):
        """Reset and start a round; any child's touch makes everyone flee."""
        return self._request('/api/game/start',{})

    def hold_children(self, held=True):
        """Pause/resume approaching children before the tag; never overrides fleeing."""
        return self._request('/api/game/hold',{'held':held})

    @staticmethod
    def _speed(value):
        value=float(value)
        if not math.isfinite(value) or abs(value)>10:
            raise ValueError('시뮬레이터의 SerBot 호환 속도 범위는 -10 ~ 10입니다')
        return value

    def forward(self, *, speed=10, seconds=.3, **kwargs):
        return self.command_velocity(self._speed(speed)*self.metres_per_speed,seconds=seconds,**kwargs)

    def backward(self, *, speed=10, seconds=.3, **kwargs):
        return self.command_velocity(-self._speed(speed)*self.metres_per_speed,seconds=seconds,**kwargs)

    def spin_left(self, *, speed=8, seconds=.3, **kwargs):
        return self.command_velocity(angular_rps=self._speed(speed)*self.radians_per_speed,seconds=seconds,**kwargs)

    def spin_right(self, *, speed=8, seconds=.3, **kwargs):
        return self.command_velocity(angular_rps=-self._speed(speed)*self.radians_per_speed,seconds=seconds,**kwargs)

    def drive(self, *, linear=0, angular=0, seconds=.3, guard_direction='auto', **kwargs):
        return self.command_velocity(self._speed(linear)*self.metres_per_speed,self._speed(angular)*self.radians_per_speed,
                                     seconds=seconds,guard=guard_direction!='none',**kwargs)

    def wheels(self, left, right, *, seconds=.3, guard_direction='auto', **kwargs):
        left,right=self._speed(left),self._speed(right)
        return self.command_velocity((left-right)/2*self.metres_per_speed,-(left+right)/2*self.radians_per_speed,
                                     seconds=seconds,guard=guard_direction!='none',**kwargs)

    raw=wheels

    def move(self, direction, *, speed=10, seconds=.3, **kwargs):
        methods={'forward':self.forward,'backward':self.backward,'spin-left':self.spin_left,'spin-right':self.spin_right}
        if direction not in methods:
            raise ValueError(f'지원하지 않는 방향: {direction}')
        return methods[direction](speed=speed,seconds=seconds,**kwargs)

    def sequence(self, steps, *, stop_between=False):
        results=[]
        for step in steps:
            data=step.to_dict() if hasattr(step,'to_dict') else dict(step)
            seconds=data.get('seconds',.3)
            guard=data.get('guard_direction','auto')!='none' and data.get('guard',True)
            if 'direction' in data:
                result=self.move(data['direction'],speed=data.get('speed',10),seconds=seconds,guard=guard)
            elif 'left' in data or 'right' in data:
                result=self.wheels(data.get('left',0),data.get('right',0),seconds=seconds,guard_direction='auto' if guard else 'none')
            else:
                result=self.drive(linear=data.get('linear',0),angular=data.get('angular',0),seconds=seconds,guard_direction='auto' if guard else 'none')
            results.append(result)
            if result['status']!='completed':
                break
            if stop_between:
                self.stop()
        return results

    def ultrasonic(self, *, count=1, **kwargs):
        count=int(count)
        if not 1<=count<=100:
            raise ValueError('count는 1 ~ 100입니다')
        samples=[self._request('/api/ultrasonic') for _ in range(count)]
        return samples[0] if count==1 else samples

    def lidar_scan(self):
        return self._request('/api/lidar')

    def say(self,text):
        return self._request('/api/robot/say',{'text':text})

    def goal(self,name,**kwargs):
        if name in ('forward','backward','spin-left','spin-right'):
            return self.move(name,**kwargs)
        methods={'stop':self.stop,'ultra':self.ultrasonic,'lidar':self.lidar_scan}
        if name not in methods:
            raise ValueError(f'시뮬레이터에서 지원하지 않는 goal: {name}')
        return methods[name](**kwargs)
