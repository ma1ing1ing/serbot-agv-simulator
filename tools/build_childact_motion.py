#!/usr/bin/env python3
"""Build local animation loops from ChildACT poses, using only the stdlib.

This is a 2-D projected-angle approximation, not 3-D motion reconstruction.
No pixels, metric trajectories, calibrated FPS or depth are present in the ZIP.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import struct
import zipfile

CHANNELS = ['rightHip', 'leftHip', 'rightKnee', 'leftKnee',
            'rightShoulder', 'leftShoulder', 'rightElbow', 'leftElbow', 'lean']
SOURCE = 'https://zenodo.org/records/14603227'
EXPECTED_MD5 = 'd1d6cfe12f0221463280803c8b0eb581'


def read_pose(data):
    """Read the numeric NPY subset in this dataset. Never deserialize pickle."""
    if data[:6] != b'\x93NUMPY' or data[6] not in (1, 2, 3):
        raise ValueError('Unsupported NPY header')
    start = 10 if data[6] == 1 else 12
    size = struct.unpack('<H' if start == 10 else '<I', data[8:start])[0]
    header = ast.literal_eval(data[start:start+size].decode('latin1').strip())
    shape = header['shape']
    if header['descr'] != '<f4' or header['fortran_order'] or len(shape) != 3 or shape[1:] != (25, 3):
        raise ValueError(f'Expected BODY_25-compatible float32 array: {header}')
    count = math.prod(shape)
    if len(data) != start+size+4*count:
        raise ValueError('Unexpected NPY payload size')
    values = struct.unpack('<'+'f'*count, data[start+size:])
    if not all(math.isfinite(v) for v in values):
        raise ValueError('Non-finite pose')
    # Reject multi-person frames rather than silently changing subject identity.
    if shape[0] != 1:
        return None
    return [values[i:i+3] for i in range(0, 75, 3)]


def clamp(value, low, high):
    return max(low, min(high, value))


def pose_angles(pose, direction, aspect):
    if pose is None:
        return [None]*len(CHANNELS)

    def vector(a, b):
        if min(pose[a][2], pose[b][2]) < .18:
            return None
        x, y = aspect*(pose[b][0]-pose[a][0]), pose[b][1]-pose[a][1]
        return (x, y) if math.hypot(x, y) > .018 else None

    def swing(a, b, limit):
        v = vector(a, b)
        return clamp(-direction*math.atan2(v[0], v[1]), -limit, limit) if v else None

    def bend(a, b, c):
        u, v = vector(a, b), vector(b, c)
        if not u or not v:
            return None
        cosine = (u[0]*v[0]+u[1]*v[1])/(math.hypot(*u)*math.hypot(*v))
        return math.acos(clamp(cosine, -1, 1))

    torso = vector(8, 1)
    return [swing(9, 10, 1.05), swing(12, 13, 1.05),
            None if (v := bend(9, 10, 11)) is None else clamp(v, 0, 2.1),
            None if (v := bend(12, 13, 14)) is None else clamp(v, 0, 2.1),
            swing(2, 3, 1.15), swing(5, 6, 1.15),
            None if (v := bend(2, 3, 4)) is None else -clamp(v, .12, 2.2),
            None if (v := bend(5, 6, 7)) is None else -clamp(v, .12, 2.2),
            clamp(direction*math.atan2(torso[0], -torso[1]), -.12, .32) if torso else None]


def interpolate_short_gaps(values, max_gap=12):
    result = list(values)
    good = [i for i, value in enumerate(values) if value is not None]
    for a, b in zip(good, good[1:]):
        if b-a-1 > max_gap:
            continue
        for i in range(a+1, b):
            t = (i-a)/(b-a)
            result[i] = values[a]*(1-t)+values[b]*t
    return result


def build_clip(archive, name, entries, aspect):
    poses = {idx: read_pose(archive.read(info)) for idx, info in entries}
    low, high = min(poses), max(poses)
    roots = [(idx, p[8][0]) for idx, p in sorted(poses.items()) if p and p[8][2] >= .3]
    drift = statistics.median([(b[1]-a[1])/(b[0]-a[0]) for a, b in zip(roots, roots[1:])]) if len(roots)>2 else 0
    direction = 1 if drift >= 0 else -1
    raw = [pose_angles(poses.get(i), direction, aspect) for i in range(low, high+1)]
    coverage = sum(v is not None for row in raw for v in row)/(len(raw)*len(CHANNELS))
    if coverage < .7:
        return None
    columns = [interpolate_short_gaps([row[j] for row in raw]) for j in range(len(CHANNELS))]
    rows = []
    for i in range(len(raw)):
        row = []
        for column in columns:
            neighbors = column[max(0,i-2):i+3]
            row.append(sum(neighbors)/len(neighbors) if all(v is not None for v in neighbors) else None)
        rows.append(row)
    best = None
    # Find a genuinely observed, near-periodic stride instead of inventing a sine.
    for start in range(2, len(rows)-14, 2):
        for period in range(12, min(80, len(rows)-start-2), 2):
            stop = start+period
            window = rows[start:stop+1]
            if any(v is None for row in window for v in row):
                continue
            amplitudes = [max(row[j] for row in window)-min(row[j] for row in window) for j in (0,1)]
            amplitude = sum(amplitudes)/2
            if min(amplitudes) < .08 or amplitude > 1.8:
                continue
            error = sum((rows[start][j]-rows[stop][j])**2 for j in range(8))/8
            velocity_error = sum(((rows[start+1][j]-rows[start][j])-(rows[stop][j]-rows[stop-1][j]))**2 for j in range(8))/8
            score = error+velocity_error*2+.025/(amplitude+.1)+.04*(1-coverage)
            if best is None or score < best[0]:
                best = (score, start, stop)
    if best is None:
        return None
    score, start, stop = best
    # Close the loop gradually; preserve the source's interior angle variation.
    loop = [row[:] for row in rows[start:stop+1]]
    for i, row in enumerate(loop):
        t = i/(len(loop)-1)
        for j in range(len(CHANNELS)):
            row[j] -= t*(rows[stop][j]-rows[start][j])
    # Resample by original frame number, including interpolated missing frames.
    samples = []
    for i in range(64):
        position = i/64*(len(loop)-1)
        a = int(position); t = position-a; b = min(a+1,len(loop)-1)
        samples.append([round(loop[a][j]*(1-t)+loop[b][j]*t, 5) for j in range(len(CHANNELS))])
    return dict(score=score, source_directory=name, source_start_frame=low+start,
                source_end_frame=low+stop, valid_value_fraction=round(coverage,3),
                screen_direction=direction, samples=samples)


def build(source, destination, aspect=4/3):
    digest = hashlib.md5(source.read_bytes()).hexdigest()
    if digest != EXPECTED_MD5:
        raise ValueError('ZIP checksum differs from the inspected ChildACT v1 release')
    clips = {}
    with zipfile.ZipFile(source) as archive:
        groups = {}
        for info in archive.infolist():
            match = re.fullmatch(r'pose/((run|jog|walk)\d+)/frame(\d+)\.npy', info.filename)
            if match:
                groups.setdefault((match[2],match[1]),[]).append((int(match[3]),info))
        for action in ('walk','jog','run'):
            candidates = []
            for (kind,name), entries in sorted(groups.items()):
                if kind != action or len(entries)<24:
                    continue
                clip = build_clip(archive,name,entries,aspect)
                if clip:
                    candidates.append(clip)
            if not candidates:
                raise ValueError(f'No reliable {action} cycle; do not substitute fabricated data')
            clip = min(candidates,key=lambda c:c['score'])
            clip.pop('score')
            clip['duration_seconds'] = {'walk':1.05,'jog':.86,'run':.72}[action]
            clips[action] = clip
            print(action,clip['source_directory'],clip['source_start_frame'],clip['source_end_frame'],flush=True)
    result = dict(schema_version=1,source=dict(title='ChildACT',url=SOURCE,archive_md5=digest),
        method='projected-2d-joint-angles',
        assumptions=dict(joint_order='OpenPose BODY_25-compatible (inferred)',
                         image_aspect=aspect,source_fps=None,depth_available=False,
                         metric_trajectory_available=False,
                         playback_timing='chosen for simulation, not measured source timing',
                         elbow_and_knee_bend_direction='anatomical approximation'),
        channels=CHANNELS,clips=clips)
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(result,separators=(',',':'),allow_nan=False)+'\n')
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zip',type=Path)
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'simulator/static/motions/childact.local.json')
    parser.add_argument('--aspect',type=float,default=4/3)
    args=parser.parse_args()
    if not math.isfinite(args.aspect) or not .5 <= args.aspect <= 3:
        parser.error('--aspect must be between .5 and 3')
    build(args.zip,args.output,args.aspect)
