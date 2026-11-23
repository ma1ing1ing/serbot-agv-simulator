"""Opt-in SerBot sensor layout for the simcheongi driving model (docs/SHIMCHEONG.md).

The ranges are cast exactly against the same shapes that ``World.clearance``
and ``World.ray`` use (room walls, box obstacles, children as 0.22 m circles),
without the 4 cm marching step of ``World.ray``. Nothing here changes the
world; it only reads the current tick. Disabled by default.

Frames (all metres / radians):

* sim world: X, Z on the floor, heading 0 faces +Z, positive heading turns left.
* model world frame: x = Z, y = -X, yaw = heading (counter-clockwise positive).
* rig frame: origin at the lidar centre, 0.025 m behind the body centre;
  x forward, y left, angles counter-clockwise from straight ahead.
"""
from __future__ import annotations

import math

SCHEMA = 'serbot-sensors/1'
LIDAR_BEAMS = 400
LIDAR_STEP_DEG = 360./LIDAR_BEAMS            # beam i points i*0.9 deg CCW from straight ahead
LIDAR_MIN_M, LIDAR_MAX_M = .10, 12.          # outside this range a beam reports 0.0 (no return)
LIDAR_BEHIND_CENTRE_M = .025                 # lidar centre behind the body centre
ULTRA_NAMES = ('left', 'front_left', 'front_right', 'right', 'rear_left', 'rear_right')
ULTRA_LAYOUT = ((0., .165, 90.), (.225, .08, 0.), (.225, -.08, 0.),       # (x, y, facing deg), rig frame
                (0., -.165, -90.), (-.225, .08, 180.), (-.225, -.08, 180.))
US_MIN_M, US_MAX_M = .04, 4.                 # 4.0 = no echo
US_CONE_DEG = 15.                            # half-angle of the simulated echo cone
US_CONE_RAYS = 5
CHILD_RADIUS_M = .22                         # same body circle as World.clearance


def to_model_frame(x, z):
    """Sim floor point (X, Z) -> model world frame (x, y)."""
    return z, -x


def to_sim_frame(x, y):
    """Model world frame (x, y) -> sim floor point (X, Z)."""
    return -y, x


def rig_pose(world):
    """(x, y, yaw) of the lidar centre in the model world frame."""
    r = world.robot
    h = r['heading']
    cx, cz = r['x']+math.sin(h)*LIDAR_BEHIND_CENTRE_M, r['z']-math.cos(h)*LIDAR_BEHIND_CENTRE_M
    x, y = to_model_frame(cx, cz)
    return x, y, h


def _room_exit(px, pz, dx, dz, bounds):
    xmin, xmax, zmin, zmax = bounds
    best = math.inf
    if dx > 1e-12:
        best = min(best, (xmax-px)/dx)
    elif dx < -1e-12:
        best = min(best, (xmin-px)/dx)
    if dz > 1e-12:
        best = min(best, (zmax-pz)/dz)
    elif dz < -1e-12:
        best = min(best, (zmin-pz)/dz)
    return max(0., best)


def _circle(px, pz, dx, dz, cx, cz, radius):
    ox, oz = px-cx, pz-cz
    c = ox*ox+oz*oz-radius*radius
    if c <= 0.:
        return 0.
    b = ox*dx+oz*dz
    disc = b*b-c
    if b >= 0. or disc < 0.:
        return math.inf
    return -b-math.sqrt(disc)


def _box(px, pz, dx, dz, x0, x1, z0, z1):
    near, far = -math.inf, math.inf
    for p, d, lo, hi in ((px, dx, x0, x1), (pz, dz, z0, z1)):
        if abs(d) < 1e-12:
            if not lo <= p <= hi:
                return math.inf
            continue
        a, b = (lo-p)/d, (hi-p)/d
        near, far = max(near, min(a, b)), min(far, max(a, b))
    if near > far or far < 0.:
        return math.inf
    return max(0., near)


def cast(world, x, z, angle, max_range=LIDAR_MAX_M, *, inflate=0.):
    """Distance from sim point (x, z) along sim heading ``angle`` to the first
    surface, or None beyond ``max_range``. The robot body is not a target.
    ``inflate`` grows every shape (World.ray hits at clearance < 0.015)."""
    dx, dz = -math.sin(angle), math.cos(angle)
    xmin, xmax, zmin, zmax = world.bounds
    best = _room_exit(x, z, dx, dz, (xmin+inflate, xmax-inflate, zmin+inflate, zmax-inflate))
    for b in world.obstacles:
        hw, hd = b['w']/2+inflate, b['d']/2+inflate
        best = min(best, _box(x, z, dx, dz, b['x']-hw, b['x']+hw, b['z']-hd, b['z']+hd))
    for c in world.children:
        if c.get('visible', True):
            best = min(best, _circle(x, z, dx, dz, c['x'], c['z'], CHILD_RADIUS_M+inflate))
    return best if best <= max_range else None


def lidar(world):
    """(400,) ranges from the lidar centre, beam i at i*0.9 deg CCW; 0.0 = no return."""
    r = world.robot
    h = r['heading']
    ox, oz = r['x']+math.sin(h)*LIDAR_BEHIND_CENTRE_M, r['z']-math.cos(h)*LIDAR_BEHIND_CENTRE_M
    ranges = []
    for i in range(LIDAR_BEAMS):
        d = cast(world, ox, oz, h+math.radians(i*LIDAR_STEP_DEG))
        ranges.append(round(d, 4) if d is not None and LIDAR_MIN_M <= d <= LIDAR_MAX_M else 0.)
    return ranges


def ultrasonic(world):
    """(6,) echo ranges in ULTRA_NAMES order: nearest hit inside a narrow cone, 4.0 = no echo."""
    r = world.robot
    h = r['heading']
    ox, oz = r['x']+math.sin(h)*LIDAR_BEHIND_CENTRE_M, r['z']-math.cos(h)*LIDAR_BEHIND_CENTRE_M
    offsets = [-US_CONE_DEG+2*US_CONE_DEG*k/(US_CONE_RAYS-1) for k in range(US_CONE_RAYS)]
    result = []
    for fx, fy, facing in ULTRA_LAYOUT:
        # rig (forward fx, left fy) -> sim floor: forward = (-sin h, cos h), left = (-cos h, -sin h)
        sx = ox-math.sin(h)*fx-math.cos(h)*fy
        sz = oz+math.cos(h)*fx-math.sin(h)*fy
        hits = [cast(world, sx, sz, h+math.radians(facing+o), US_MAX_M) for o in offsets]
        hits = [d for d in hits if d is not None]
        result.append(round(max(US_MIN_M, min(hits)), 4) if hits else US_MAX_M)
    return result


def observe(world):
    """The ``observation['serbot']`` block for the current tick."""
    x, y, yaw = rig_pose(world)
    return dict(schema=SCHEMA, pose=dict(x=x, y=y, yaw=yaw), lidar_m=lidar(world), ultrasonic_m=ultrasonic(world))
