"""Measure tag outcomes and the distance to each pursued target up to the first catch."""
import argparse
import json
from pathlib import Path

from simulator.controllers import RuleController
from simulator.engine import World
from simulator.environment import PlayEnv
from simulator.evaluate import outcome
from simulator.examples.tag_pursuit import ClosingTagController
from simulator.games import distance


class TraceWorld(World):
    """Read positions on the original physics tick, including mid-control-step catches."""

    def reset(self):
        self.segments = []
        self.first_catch = None
        super().reset()

    def sample_target(self):
        if self.first_catch is not None or not self.segments:
            return
        segment = self.segments[-1]
        samples = segment['samples']
        if not samples or samples[-1][0] != self.time:
            child = next(c for c in self.children if c['id'] == segment['target'])
            samples.append((self.time, distance(self.robot, child)))

    def emit(self, kind, actor=None, target=None, **details):
        super().emit(kind, actor, target, **details)
        if self.first_catch is not None:
            return
        if kind == 'target_change' and target is not None:
            self.sample_target()
            self.segments.append(dict(target=target, samples=[]))
            self.sample_target()
        elif kind == 'catch':
            self.sample_target()
            child = next(c for c in self.children if c['id'] == target)
            xmin, xmax, zmin, zmax = self.bounds
            wall = min(child['x'] - xmin, xmax - child['x'], child['z'] - zmin, zmax - child['z'])
            self.first_catch = dict(time=self.time, target=target, wall_distance=wall)


def measure(seed, policy):
    world = TraceWorld()
    with PlayEnv(game='tag', controller=policy, world=world, dt=.1) as env:
        env.reset(seed=seed, scenario='open', settings={'time_limit': 30.}, count=5)
        while env.active:
            _, _, _, _, info = env.step()
            world.sample_target()
        return dict(seed=seed, controller=policy.name, model_version=policy.model_version,
                    end_reason=world.game['end_reason'], first_catch=world.first_catch,
                    pursuit_segments=world.segments, outcome=outcome(world), metrics=info['metrics'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', nargs='+', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output already exists')
    rows = [measure(seed, factory()) for seed in args.seeds
            for factory in (RuleController, ClosingTagController)]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(rows, handle, allow_nan=False)
        handle.write('\n')


if __name__ == '__main__':
    main()
