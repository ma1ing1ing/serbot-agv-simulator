"""Rule-based tag trajectories. These are synthetic, not ChildACT trajectories."""
from __future__ import annotations

import math


def angle_delta(target, current):
    return (target-current+math.pi) % (2*math.pi)-math.pi


def start(world, auto_chase):
    world.game.update(mode='tag', phase='chasing', caught_ids=[], held=False,
                      auto_chase=bool(auto_chase), target_id=None)
    for i, child in enumerate(world.children):
        child.update(x=(i-(len(world.children)-1)/2)*.85,
                     z=.3+(i%2)*1.15, heading=(i*.9)%(2*math.pi),
                     caught=False, running=False, moving=False, wave=False,
                     mode='walk', stamina=1.0, resting=False, speed=0.0,
                     motion_time=i*.17, motion_kind='walk', watched=False)
    world.log('술래잡기 시작 · 로봇은 술래, 아이들은 자유롭게 도망갑니다')


def check_catches(world):
    if world.game.get('mode') != 'tag' or world.game['phase'] != 'chasing':
        return
    for child in world.children:
        if child['caught']:
            continue
        if math.hypot(child['x']-world.robot['x'],child['z']-world.robot['z']) <= world.touch_distance:
            child.update(caught=True,moving=False,running=False,speed=0.0,motion_kind='idle')
            world.game['caught_ids'].append(child['id'])
            world.log(f"{child['name']} 잡힘 · {len(world.game['caught_ids'])}/{len(world.children)}명")
    if len(world.game['caught_ids']) == len(world.children):
        world.game.update(phase='finished',target_id=None)
        world.finish_motion('game_finished')
        world.log('모두 잡았습니다 · 술래잡기 완료')


def advance_children(world, dt):
    check_catches(world)
    # Substeps keep avoidance meaningful at 4x playback and large wall_dt.
    steps = max(1,math.ceil(dt/.025))
    for _ in range(steps):
        step = dt/steps
        for child in world.children:
            if world.game['phase'] != 'chasing' or child['caught'] or world.game['held']:
                child.update(moving=False,running=False,speed=0.0,motion_kind='idle')
                continue
            dx,dz = child['x']-world.robot['x'],child['z']-world.robot['z']
            distance = math.hypot(dx,dz)
            # Each child has a distinct deterministic wandering rhythm.
            wander = world.time*.33+child['phase']
            urgency = max(0,(3.5-distance)/3.5)
            vx = math.sin(wander)*.55+dx/max(distance,.05)*urgency*2.8
            vz = math.cos(wander*.81)*.55+dz/max(distance,.05)*urgency*2.8
            for other in world.children:
                if other['id'] == child['id']:
                    continue
                ox,oz = child['x']-other['x'],child['z']-other['z']
                separation = math.hypot(ox,oz)
                if separation < 1.0:
                    vx += ox/max(separation,.05)*(1-separation)*1.8
                    vz += oz/max(separation,.05)*(1-separation)*1.8
            desired = math.atan2(vx,vz)
            if child['resting'] and child['stamina'] > .65:
                child['resting'] = False
            if child['stamina'] < .12:
                child['resting'] = True
            running = distance < 2.8 and not child['resting']
            jogging = 2.8 <= distance < 3.5 and not child['resting']
            target_speed = (.83+(child['id']%3)*.06) if running else (.56+(child['id']%3)*.04) if jogging else (.15 if child['resting'] else .40+(child['id']%3)*.04)
            child['stamina'] = max(0,min(1,child['stamina']+step*(-.13 if running else -.04 if jogging else .22)))
            # Choose a feasible turn, preferring clearance before the next corner.
            best = None
            for offset in (0,.35,-.35,.7,-.7,1.1,-1.1,1.6,-1.6,2.3,-2.3,math.pi):
                heading = desired+offset
                x = child['x']+math.sin(heading)*target_speed*step
                z = child['z']+math.cos(heading)*target_speed*step
                if not child_clear(world,child,x,z):
                    continue
                future_x,future_z = x+math.sin(heading)*.40,z+math.cos(heading)*.40
                clearance = min(world.clearance(future_x,future_z,exclude_child=child['id']),1)
                score = math.cos(offset)+min(clearance,.5)*1.6-abs(angle_delta(heading,child['heading']))*.04
                if best is None or score > best[0]:
                    best = (score,heading)
            moved = False
            if best:
                turn = max(-3.8*step,min(3.8*step,angle_delta(best[1],child['heading'])))
                child['heading'] += turn
                x = child['x']+math.sin(child['heading'])*target_speed*step
                z = child['z']+math.cos(child['heading'])*target_speed*step
                if child_clear(world,child,x,z):
                    child.update(x=x,z=z)
                    moved = True
                else:
                    # Turn in place until the new direction clears the obstruction.
                    child['heading'] += turn
            child.update(moving=moved,running=running and moved,speed=target_speed if moved else 0,
                         motion_kind='run' if running and moved else 'jog' if jogging and moved else 'walk' if moved else 'idle')
            if moved:
                child['motion_time'] += step*target_speed/(.85 if running else .62 if jogging else .44)
        check_catches(world)


def child_clear(world, child, x, z):
    return (world.clearance(x,z,exclude_child=child['id']) > .25
            and math.hypot(x-world.robot['x'],z-world.robot['z']) > world.radius+.25)


def advance_robot(world, dt):
    if world.game.get('mode') != 'tag' or world.game['phase'] != 'chasing' or not world.game['auto_chase']:
        return
    if world.game['held']:
        world.robot.update(linear=0.0,angular=0.0)
        return
    available = [c for c in world.children if not c['caught']]
    if not available:
        return
    previous = world.game.get('target_id')
    # Small hysteresis prevents rapid target switches between adjacent children.
    target = min(available,key=lambda c:math.hypot(c['x']-world.robot['x'],c['z']-world.robot['z'])-(.3 if c['id']==previous else 0))
    world.game['target_id'] = target['id']
    steps = max(1,math.ceil(dt/.01))
    for _ in range(steps):
        step=dt/steps
        dx,dz=target['x']-world.robot['x'],target['z']-world.robot['z']
        desired=math.atan2(-dx,dz)
        # A short steering fan avoids benches and already-caught children.
        options=[]
        for offset in (0,.45,-.45,.9,-.9,1.4,-1.4,2.0,-2.0):
            heading=desired+offset
            px=world.robot['x']-math.sin(heading)*.55
            pz=world.robot['z']+math.cos(heading)*.55
            clearance=world.clearance(px,pz,exclude_child=target['id'])
            options.append((math.cos(offset)+min(clearance-.42,.3)*3.0,heading))
        desired=max(options,key=lambda item:item[0])[1]
        error=angle_delta(desired,world.robot['heading'])
        angular=max(-2.4,min(2.4,error*3))
        heading=world.robot['heading']+angular*step
        speed=.48*max(0,math.cos(error))
        x=world.robot['x']-math.sin(heading)*speed*step
        z=world.robot['z']+math.cos(heading)*speed*step
        if world.clearance(x,z) < world.radius+.025:
            speed=0.0
        else:
            world.robot.update(x=x,z=z)
            world.distance+=speed*step
        world.robot.update(heading=angle_delta(heading,0),linear=speed,angular=angular)
        check_catches(world)
        if world.game['phase'] != 'chasing' or target['caught']:
            break
    if math.hypot(world.trail[-1][0]-world.robot['x'],world.trail[-1][1]-world.robot['z'])>.035:
        world.trail.append([world.robot['x'],world.robot['z']])
        world.trail=world.trail[-1500:]
