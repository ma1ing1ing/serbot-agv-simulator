"""Synchronized recorded trajectories, independent of synthetic tag behavior."""
from __future__ import annotations

from bisect import bisect_right
from functools import lru_cache
import json
import math
from pathlib import Path

PACK_PATH = Path(__file__).parent/'data/playground_a.local.json'


class Recording:
    def __init__(self, pack):
        if pack.get('schema_version') != 1 or not pack.get('tracks') or not pack.get('clips'):
            raise ValueError('지원하지 않는 Playground A 궤적 형식')
        self.source = pack['source']
        self.assumptions = pack['assumptions']
        self.clips = pack['clips']
        self.tracks = {}
        for track in pack['tracks']:
            pieces = []
            for segment in track['segments']:
                if len(segment)<2 or any(len(p)!=3 or not all(math.isfinite(v) for v in p) for p in segment):
                    raise ValueError('잘못된 궤적 좌표')
                times = [p[0] for p in segment]
                if any(b<=a for a,b in zip(times,times[1:])):
                    raise ValueError('궤적 시간이 증가하지 않습니다')
                if pieces and times[0]<=pieces[-1][0][-1]:
                    raise ValueError('궤적 구간이 겹칩니다')
                pieces.append((times,segment))
            if not pieces or track['id'] in self.tracks:
                raise ValueError('비어 있거나 중복된 참가자 궤적')
            self.tracks[track['id']] = pieces

    def sample(self, ident, time):
        for times, points in self.tracks[ident]:
            if times[0]<=time<=times[-1]:
                index=min(max(0,bisect_right(times,time)-1),len(points)-2)
                a,b=points[index:index+2]
                delta=b[0]-a[0]
                alpha=(time-a[0])/delta
                return (a[1]+(b[1]-a[1])*alpha,a[2]+(b[2]-a[2])*alpha,
                        (b[1]-a[1])/delta,(b[2]-a[2])/delta,times[0])
        return None


@lru_cache(maxsize=2)
def _read(path, modified_ns):
    return Recording(json.loads(Path(path).read_text()))


def load():
    try:
        return _read(str(PACK_PATH),PACK_PATH.stat().st_mtime_ns)
    except FileNotFoundError as exc:
        raise ValueError('Playground A 궤적이 없습니다. tools/build_playground_replay.py로 CSV를 변환하세요.') from exc


def metadata():
    try:
        recording=load()
        return dict(available=True,participants=len(recording.tracks),clips=recording.clips,
                    source=recording.source,assumptions=recording.assumptions)
    except (ValueError,OSError) as exc:
        return dict(available=False,error=str(exc),clips=[])


class Playback:
    def __init__(self, recording, clip_id, count):
        self.recording=recording
        self.clip=next((c for c in recording.clips if c['id']==clip_id),None)
        if self.clip is None:
            raise ValueError('지원하지 않는 재생 구간')
        self.ids=sorted(recording.tracks)[:count]
        start,end=self.clip['start'],self.clip['start']+self.clip['duration']
        points=[]
        for ident in self.ids:
            for _,segment in recording.tracks[ident]:
                points.extend(p[1:] for p in segment if start<=p[0]<=end)
            for boundary in (start,end):
                sample=recording.sample(ident,boundary)
                if sample:
                    points.append(sample[:2])
        if len(points)<2:
            raise ValueError('이 구간에는 재생할 위치 기록이 없습니다')
        xmin,xmax=min(p[0] for p in points),max(p[0] for p in points)
        ymin,ymax=min(p[1] for p in points),max(p[1] for p in points)
        self.center=((xmin+xmax)/2,(ymin+ymax)/2)
        width,height=max(xmax-xmin,.001),max(ymax-ymin,.001)
        straight=min(6.8/width,4.8/height)
        rotated=min(6.8/height,4.8/width)
        self.rotated=rotated>straight
        self.scale=max(straight,rotated)
        self.elapsed=0.0
        self.revision=0

    def vector(self,x,y):
        return (y*self.scale,-x*self.scale) if self.rotated else (x*self.scale,y*self.scale)

    def update(self, world, dt=0):
        if world.game['phase']=='replaying' and not world.game['held']:
            self.elapsed=min(self.clip['duration'],self.elapsed+dt)
        source_time=self.clip['start']+self.elapsed
        finished=self.elapsed>=self.clip['duration']
        for child in world.children:
            sample=self.recording.sample(child['source_id'],source_time)
            if sample is None:
                child.update(visible=False,moving=False,running=False,speed=0.0,motion_kind='idle',trail=[])
                child['segment_id']=None
                continue
            sx,sy,vx,vy,segment=sample
            x,z=self.vector(sx-self.center[0],sy-self.center[1])
            dx,dz=self.vector(vx,vy)
            speed=math.hypot(dx,dz)
            stopped=world.game['held'] or finished
            moving=speed>.006 and not stopped
            kind='run' if speed>.65 else 'jog' if speed>.35 else 'walk'
            previous_segment=child.get('segment_id')
            child.update(x=x,z=z,visible=True,segment_id=segment,
                         moving=moving,running=moving and kind=='run',
                         speed=0.0 if stopped else speed,motion_kind=kind if moving else 'idle')
            if moving:
                child['heading']=math.atan2(dx,dz)
                child['motion_time']+=dt*speed/({'walk':.44,'jog':.62,'run':.85}[kind])
            if previous_segment!=segment:
                child['trail']=[]
            trail=child['trail']
            if not trail or math.hypot(x-trail[-1][0],z-trail[-1][1])>.018:
                trail.append([x,z])
                child['trail']=trail[-400:]
        if finished and world.game['phase']!='finished':
            world.game['phase']='finished'
            world.log('Playground A 기록 재생 완료 · 다시 재생하거나 시간 막대를 이동하세요')

    def seek(self, world, elapsed):
        self.elapsed=elapsed
        self.revision+=1
        world.game['phase']='finished' if elapsed>=self.clip['duration'] else 'replaying'
        for child in world.children:
            child.update(trail=[],segment_id=None,motion_time=0.0)
        self.update(world)

    def snapshot(self):
        return dict(elapsed=round(self.elapsed,3),duration=self.clip['duration'],
                    source_time=round(self.clip['start']+self.elapsed,3),clip=self.clip,
                    revision=self.revision,scale=self.scale,rotated=self.rotated,
                    coordinate_unit='display fit; source metric calibration unverified',
                    source=self.recording.source)
