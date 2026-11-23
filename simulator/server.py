#!/usr/bin/env python3
"""Local-only simulation API. The open browser renders the virtual camera."""
from __future__ import annotations

import argparse
import json
import mimetypes
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from simulator.engine import World, number
from simulator import replay
from simulator.environment import PlayEnv

STATIC = Path(__file__).parent/'static'


class SimulationServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address):
        self.closed = threading.Event()
        self.frame_lock = threading.Condition()
        super().__init__(address, Handler)
        self.world = World()
        self.frame = None
        self.frame_id = 0
        self.frame_at = 0
        self.frame_time = 0
        self.frame_epoch = None
        self.publisher = secrets.token_urlsafe(24)
        threading.Thread(target=self.loop,daemon=True).start()

    def loop(self):
        previous = time.monotonic()
        while not self.closed.wait(.02):
            now=time.monotonic()
            self.world.tick(now-previous)
            previous=now

    def camera_meta(self):
        with self.frame_lock:
            age=time.monotonic()-self.frame_at if self.frame else None
            return dict(ready=bool(self.frame and age<2.5 and self.frame_epoch==self.world.epoch),
                        frame_id=self.frame_id,age_seconds=round(age,3) if age is not None else None,
                        sim_time=self.frame_time,width=640,height=480,epoch=self.frame_epoch)

    def server_close(self):
        self.closed.set()
        if hasattr(self, 'world'):
            self.world.finish_game('server_closed')
        with self.frame_lock:
            self.frame_lock.notify_all()
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'

    def log_message(self, *args):
        pass

    def send(self, data, status=200, kind='application/json; charset=utf-8', extra=None):
        if isinstance(data,(dict,list)):
            data=json.dumps(data,ensure_ascii=False,allow_nan=False).encode()
        if isinstance(data,str):
            data=data.encode()
        self.send_response(status)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        for k,v in (extra or {}).items():
            self.send_header(k,str(v))
        self.end_headers()
        self.wfile.write(data)

    def local_request(self):
        hosts={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        host=self.headers.get('Host','')
        origin=self.headers.get('Origin')
        return host in hosts and (not origin or origin in {f'http://{h}' for h in hosts})

    def do_GET(self):
        if not self.local_request():
            self.send({'error':'로컬 주소에서만 사용할 수 있습니다'},403)
            return
        parsed=urlsplit(self.path)
        path=parsed.path
        if path=='/api/state':
            state=self.server.world.snapshot()
            state['camera']=self.server.camera_meta()
            self.send(state)
        elif path=='/api/observation':
            try:
                self.send(self.server.world.observe(parse_qs(parsed.query).get('mode',['oracle'])[0]))
            except ValueError as exc:
                self.send({'error':str(exc)},400)
        elif path=='/api/session':
            self.send(dict(publisher=self.server.publisher))
        elif path=='/api/replay':
            self.send(replay.metadata())
        elif path=='/api/episode':
            with self.server.world.lock:
                episode=self.server.world.episode
                self.send(episode.metadata() if episode else {'recording':False})
        elif path=='/api/camera/meta':
            self.send(self.server.camera_meta())
        elif path=='/api/camera.jpg':
            with self.server.frame_lock:
                meta=self.server.camera_meta()
                if not meta['ready']:
                    self.send({'error':'카메라 영상이 없습니다. 시뮬레이터 탭을 열어 두세요.',**meta},503)
                else:
                    self.send(self.server.frame,kind='image/jpeg',extra={'X-Frame-ID':meta['frame_id'],'X-Sim-Time':meta['sim_time']})
        elif path=='/api/camera/stream.mjpg':
            self.stream()
        elif path=='/api/ultrasonic':
            self.send(self.server.world.ultrasonic())
        elif path=='/api/lidar':
            self.send(self.server.world.lidar())
        elif path=='/api/command':
            ident=parse_qs(parsed.query).get('id',[''])[0]
            with self.server.world.lock:
                motion=self.server.world.motion
                result=self.server.world.command_results.get(ident)
                if not result and motion and motion['id']==ident:
                    result=dict(id=ident,status='running')
                self.send(result or dict(id=ident,status='unknown'))
        else:
            target=(STATIC/('index.html' if path=='/' else path.lstrip('/'))).resolve()
            if not target.is_relative_to(STATIC.resolve()) or not target.is_file():
                self.send({'error':'Not found'},404)
            else:
                kind=mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
                self.send(target.read_bytes(),kind=kind)

    def stream(self):
        if not self.server.camera_meta()['ready']:
            self.send({'error':'시뮬레이터 탭을 먼저 열어 두세요'},503)
            return
        self.send_response(200)
        self.send_header('Content-Type','multipart/x-mixed-replace; boundary=frame')
        self.send_header('Cache-Control','no-store')
        self.send_header('Connection','close')
        self.end_headers()
        self.close_connection=True
        last=-1
        try:
            while not self.server.closed.is_set():
                with self.server.frame_lock:
                    self.server.frame_lock.wait_for(lambda:self.server.frame_id!=last or self.server.closed.is_set(),timeout=2)
                    if not self.server.camera_meta()['ready']:
                        return
                    frame=self.server.frame
                    last=self.server.frame_id
                self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(frame)).encode()+b'\r\n\r\n'+frame+b'\r\n')
                self.wfile.flush()
        except (BrokenPipeError,ConnectionResetError):
            pass

    def do_POST(self):
        if not self.local_request():
            self.send({'error':'로컬 주소에서만 사용할 수 있습니다'},403)
            return
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=1_000_000:
                raise ValueError('잘못된 요청 크기')
            raw=self.rfile.read(size)
            path=urlsplit(self.path).path
            if path=='/api/camera/frame':
                if not secrets.compare_digest(self.headers.get('X-Publisher',''),self.server.publisher):
                    self.send({'error':'잘못된 렌더러 세션'},403)
                    return
                if not raw.startswith(b'\xff\xd8') or not raw.endswith(b'\xff\xd9'):
                    raise ValueError('JPEG 영상이 필요합니다')
                frame_time=number(self.headers.get('X-Sim-Time',0),0,1e12,'sim_time')
                with self.server.frame_lock:
                    if self.headers.get('X-Epoch')!=self.server.world.epoch:
                        self.send({'error':'재설정 이전의 프레임입니다'},409)
                        return
                    self.server.frame=raw
                    self.server.frame_id+=1
                    self.server.frame_at=time.monotonic()
                    self.server.frame_time=frame_time
                    self.server.frame_epoch=self.server.world.epoch
                    self.server.frame_lock.notify_all()
                self.send({'ok':True})
                return
            if 'application/json' not in self.headers.get('Content-Type',''):
                raise ValueError('Content-Type: application/json이 필요합니다')
            data=json.loads(raw)
            if not isinstance(data,dict):
                raise ValueError('JSON 객체가 필요합니다')
            with self.server.world.lock:
                self._dispatch_post(path,data)
        except (ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
            self.send({'error':str(exc)},400)
        except (BrokenPipeError,ConnectionResetError):
            pass
        except OSError:
            self.send({'error':'저장 공간과 기록 폴더의 쓰기 권한을 확인하세요.'},500)

    def _dispatch_post(self,path,data):
        w=self.server.world
        training_routes = {'/api/training/reset','/api/training/step','/api/training/close',
                           '/api/robot/stop','/api/detections','/api/episode/observation','/api/game/finish'}
        if w.execution_mode == 'stepped' and path not in training_routes:
            self.send({'error':'학습 단계 실행 중입니다. training_close() 후 실시간 제어를 사용하세요.'},409)
            return
        if path=='/api/training/reset':
            env=PlayEnv(data.get('mode','tag'),observation_mode=data.get('observation_mode','oracle'),
                        dt=data.get('dt',.1),physics=data.get('physics'),world=w,
                        serbot_sensors=data.get('serbot_sensors',False))
            observation,info=env.reset(seed=data.get('seed',0),scenario=data.get('scenario','open'),
                count=data.get('count',5),settings=data.get('settings'),record=data.get('record',False))
            self.server.training_env=env
            self.send(dict(observation=observation,info=info))
            return
        if path=='/api/training/step':
            env=getattr(self.server,'training_env',None)
            if env is None:
                raise ValueError('training_reset()으로 먼저 시작하세요')
            if data.get('epoch',w.epoch) != w.epoch:
                self.send({'error':'재설정 이전의 학습 요청입니다'},409)
                return
            observation,reward,terminated,truncated,info=env.step(data.get('action'))
            self.send(dict(observation=observation,reward=reward,terminated=terminated,truncated=truncated,info=info))
            return
        if path=='/api/training/close':
            if data.get('epoch',w.epoch) != w.epoch:
                self.send({'error':'재설정 이전의 학습 종료 요청입니다'},409)
                return
            env=getattr(self.server,'training_env',None)
            if env is not None:
                env.close()
            w.reset()
            self.server.training_env=None
            self.send({'ok':True,'execution_mode':w.execution_mode})
            return
        if path=='/api/detections':
            env=getattr(self.server,'training_env',None)
            if env is not None and env.active:
                env.set_detections(data.get('detections'))
            else:
                w.set_detections(data.get('detections'))
            self.send({'ok':True})
            return
        if path=='/api/robot/command':
            self.send(w.command(data.get('linear_mps',0),data.get('angular_rps',0),data.get('seconds',.5),data.get('guard',True)))
        elif path=='/api/robot/stop':
            with w.lock:
                w.game['auto_chase']=False
                w.finish_motion('stopped')
                w.emit('robot_stop',actor='robot')
                w.log('로봇 정지')
                if w.execution_mode == 'stepped':
                    w.finish_game('emergency_stop')
                    env=getattr(self.server,'training_env',None)
                    if env is not None:env.active=False
            self.send({'ok':True})
        elif path=='/api/robot/say':
            text=str(data.get('text',''))[:200]
            with w.lock:
                w.speech=text
                w.speech_id+=1
                w.log('로봇 음성 출력 · '+text)
            self.send({'ok':True})
        elif path=='/api/world/reset':
            w.reset()
            self.send({'ok':True})
        elif path=='/api/game/start':
            w.start_game(data.get('mode','tag'),data.get('auto_chase',True),
                         replay_count=data.get('replay_count',16),clip_id=data.get('clip_id','active'),
                         seed=data.get('seed',0),settings=data.get('settings'),record=data.get('record',False),
                         scenario=data.get('scenario','open'),physics=data.get('physics'),observation_mode=data.get('observation_mode','oracle'),
                         serbot_sensors=data.get('serbot_sensors',False))
            self.send({'ok':True,'game':w.snapshot()['game']})
        elif path=='/api/replay/seek':
            w.seek_replay(data.get('elapsed',0))
            self.send({'ok':True,'replay':w.snapshot()['replay']})
        elif path=='/api/game/auto':
            with w.lock:
                if w.replay is not None or w.game['phase'] in ('ready','finished'):
                    raise ValueError('진행 중인 놀이에서만 자동 제어를 켤 수 있습니다')
                w.finish_motion('superseded')
                w.game['auto_chase']=bool(data.get('enabled',True))
                w.emit('controller_change',actor='robot',automatic=w.game['auto_chase'])
            self.send({'ok':True,'game':w.snapshot()['game']})
        elif path=='/api/episode/observation':
            w.note_observation(data.get('value'),data.get('source','external'))
            self.send({'ok':True})
        elif path=='/api/game/finish':
            w.finish_game()
            env=getattr(self.server,'training_env',None)
            if env is not None:env.active=False
            self.send({'ok':True,'game':w.snapshot()['game']})
        elif path=='/api/game/hold':
            w.hold_game(data.get('held',True))
            self.send({'ok':True,'game':w.snapshot()['game']})
        elif path=='/api/world/config':
            with w.lock:
                paused=bool(data.get('paused',w.paused))
                rate=number(data.get('rate',w.rate),.25,16 if w.replay is not None else 4,'rate')
                count=int(number(data.get('count',len(w.children)),1,16 if w.replay is not None else 8,'count'))
                if count!=len(w.children):
                    w.set_count(count)
                w.paused,w.rate=paused,rate
            self.send({'ok':True})
        elif path=='/api/children':
            mode=data.get('mode','still')
            if data.get('id') is None:
                for c in list(w.snapshot()['children']):
                    w.set_child(c['id'],mode)
            else:
                w.set_child(data['id'],mode)
            self.send({'ok':True})
        else:
            self.send({'error':'Not found'},404)


def main():
    parser=argparse.ArgumentParser(description='SerBot AGV 3D simulator — local only')
    parser.add_argument('--port',type=int,default=8767)
    args=parser.parse_args()
    server=SimulationServer(('127.0.0.1',args.port))
    print(f'SerBot AGV Simulator: http://127.0.0.1:{server.server_port}',flush=True)
    print('카메라를 제공하려면 브라우저 탭을 열어 두세요. Ctrl+C로 종료합니다.',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__=='__main__':
    main()
