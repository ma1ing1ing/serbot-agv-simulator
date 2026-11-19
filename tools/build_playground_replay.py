#!/usr/bin/env python3
"""Prepare an offline Playground A replay. No dependencies or network required.

Coordinates and time are retained in source units. Their physical calibration is
not established by the distributed CSV. The viewer uses an explicit display fit.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics

COMMIT = 'c8981a2cfbe5b522275dd29dde58f75afbeec5fe'
SOURCE = f'https://raw.githubusercontent.com/centeio/GraphSD/{COMMIT}/graphsd/datasets/data/playground_a_position_data_anonymized.csv'
SHA256 = '5a87933b243a774f36a7cd28473df33f2e07aabfdda6ff3050d3d3d2e251f62c'
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1]/'simulator/data/playground_a.local.json'


def build(source, destination):
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != SHA256:
        raise ValueError('검사한 Playground A 배포본과 SHA-256이 다릅니다')
    tracks = {}
    with source.open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ['id', 'time', 'x', 'y']:
            raise ValueError('id,time,x,y CSV가 필요합니다')
        for row in reader:
            ident, time, x, y = (float(row[k]) for k in reader.fieldnames)
            if not all(math.isfinite(v) for v in (ident,time,x,y)) or ident != int(ident):
                raise ValueError('잘못된 좌표 또는 ID')
            tracks.setdefault(int(ident), []).append([time,x,y])
    deltas, speeds = [], []
    for points in tracks.values():
        points.sort()
        for a,b in zip(points,points[1:]):
            delta = b[0]-a[0]
            if delta <= 0:
                raise ValueError('같은 참가자의 시간은 중복 없이 증가해야 합니다')
            deltas.append(delta)
    interval = statistics.median(deltas)
    max_gap = interval*2.5
    for points in tracks.values():
        for a,b in zip(points,points[1:]):
            delta = b[0]-a[0]
            if delta <= max_gap:
                speeds.append(math.hypot(b[1]-a[1],b[2]-a[2])/delta)
    # Extreme changes are excluded, not clipped into fabricated trajectories.
    median = statistics.median(speeds)
    mad = statistics.median(abs(v-median) for v in speeds)
    jump_limit = max(median+20*mad, sorted(speeds)[int(.995*(len(speeds)-1))]*2)
    segments, rejected = [], 0
    for ident, points in sorted(tracks.items()):
        pieces, current = [], [points[0]]
        for point in points[1:]:
            old = current[-1]
            delta = point[0]-old[0]
            jump = math.hypot(point[1]-old[1],point[2]-old[2])/delta > jump_limit
            if delta > max_gap or jump:
                if len(current)>1:
                    pieces.append(current)
                current = [point]
                rejected += 1
            else:
                current.append(point)
        if len(current)>1:
            pieces.append(current)
        segments.append(dict(id=ident,segments=pieces))
    # Shared time windows, not individually restarted tracks. All 16 IDs remain
    # on their original common clock; sparse observations stay absent.
    clips = [dict(id='active',name='움직임 관찰 · 2분',start=4380.0,duration=120.0),
             dict(id='group',name='함께 움직이기 · 2분',start=3780.0,duration=120.0),
             dict(id='early',name='다른 놀이 구간 · 2분',start=2430.0,duration=120.0)]
    pack = dict(schema_version=1,source=dict(title='Playground A / GraphSD',url=SOURCE,
                commit=COMMIT,sha256=digest,rows=sum(map(len,tracks.values()))),
                assumptions=dict(coordinate_unit='unverified source unit',
                    time_unit='unverified source time unit',
                    playback='one source time unit per simulation second before rate scaling',
                    median_sample_interval=interval,max_interpolation_gap=max_gap,
                    jump_speed_limit=jump_limit,excluded_transitions=rejected,
                    roles_available=False,spatial_fit='one uniform scale and a rigid rotation per clip'),
                clips=clips,tracks=segments)
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(pack,separators=(',',':'),allow_nan=False)+'\n')
    return pack


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv',type=Path)
    parser.add_argument('--output',type=Path,default=DEFAULT_OUTPUT)
    args=parser.parse_args()
    data=build(args.csv,args.output)
    print(f"Playground A: {len(data['tracks'])}명 · {data['source']['rows']}개 좌표 → {args.output}")
