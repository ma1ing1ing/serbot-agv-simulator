"""Short clearance-checked routes for the red-light escort."""
from __future__ import annotations

import heapq
import math


def plan_route(world, goal):
    start = (world.robot['x'], world.robot['z'])
    end = (goal['x'], goal['z'])
    spacing = .25
    margin = world.radius + world.physics['body_margin'] + .04

    def clear(start, end):
        steps = max(1, math.ceil(math.dist(start, end) / .08))
        return all(world.clearance(start[0] + (end[0]-start[0])*i/steps,
                                   start[1] + (end[1]-start[1])*i/steps) > margin
                   for i in range(1, steps+1))

    if clear(start, end):
        return [dict(goal)]

    def neighbors(point):
        x, z = (round(coordinate / spacing) for coordinate in point)
        for ix in range(x-1, x+2):
            for iz in range(z-1, z+2):
                candidate = (ix*spacing, iz*spacing)
                if candidate != point and clear(point, candidate):
                    yield candidate

    queue = [(math.dist(start, end), 0., start)]
    previous = {start: None}
    distances = {start: 0.}
    while queue:
        _, length, point = heapq.heappop(queue)
        if length > distances[point]:
            continue
        if math.dist(point, end) <= spacing*2 and clear(point, end):
            path = []
            while point != start:
                path.append(point)
                point = previous[point]
            # Join as many consecutive grid steps as the robot can see clear.
            route = []
            current = start
            last = start
            for candidate in reversed(path):
                if not clear(current, candidate):
                    current = last
                    route.append(dict(x=current[0], z=current[1]))
                last = candidate
            if path and not clear(current, end):
                route.append(dict(x=last[0], z=last[1]))
            return [*route, dict(goal)]
        for candidate in neighbors(point):
            next_length = length + math.dist(point, candidate)
            if next_length < distances.get(candidate, math.inf):
                distances[candidate] = next_length
                previous[candidate] = point
                heapq.heappush(queue, (next_length+math.dist(candidate, end), next_length, candidate))
    return []
