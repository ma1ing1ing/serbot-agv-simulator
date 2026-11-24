"""Paired, previously unseen full games for the exported referee policy."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
from statistics import mean

from simulator.controllers import RedLightController
from simulator.evaluate import run
from simulator.friendly_controller import FriendlyReferee
from simulator.friendly_policy import MODEL_PATH

GROUPS = ((3, 'cautious', .75), (6, 'playful', 1.25), (8, 'helper', 1.05))


def compare(case):
    number, seed = case
    count, style, pace = GROUPS[number % 3]
    layout = ('dense', 'cross_room')[(number // 3) % 2]
    reaction = ('immediate', 'delayed')[(number // 6 + number % 3) % 2]
    settings = dict(child_behavior=style, child_speed_scale=pace, stop_reaction=reaction,
                    trajectory_difficulty='challenge', time_limit=120.)
    args = dict(scenarios=(layout,), seeds=(seed,), count=count, dt=.1)
    rows = []
    for timing, turn, controllers in (
            ('timed', 'baseline', {'original': RedLightController}),
            ('settled', 'smooth', {'fixed_smooth': RedLightController, 'learned': FriendlyReferee})):
        report = run('red_light', settings=dict(settings, gaze_timing=timing, turn_profile=turn),
                     controllers=controllers, **args)
        for row in report['rows']:
            m = row['metrics']
            rows.append(dict(seed=seed, scenario=layout, group_count=count, settings=settings,
                             controller=row['controller'], initial_state=row['initial_state_sha256'],
                             game_seconds=row['game_time'], end_reason=row['end_reason'],
                             stages=row['referee_stages'], flags=row['failure_flags'],
                             near_seconds=m['near_miss_seconds'], brake_ticks=m['emergency_stops'],
                             angular_change=m['angular_change']))
    if len({r['initial_state'] for r in rows}) != 1:
        raise ValueError('controllers did not start from matching initial states')
    return rows


def summarize(rows):
    return dict(games=len(rows), complete=sum(r['stages']['referee_round_complete'] for r in rows),
                checked=sum(r['stages']['referee_checks'] > 0 for r in rows),
                mean_near_seconds=mean(r['near_seconds'] for r in rows),
                mean_brake_seconds=.02*mean(r['brake_ticks'] for r in rows),
                mean_angular_change=mean(r['angular_change'] for r in rows),
                endings=dict(Counter(r['end_reason'] for r in rows)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('artifacts/friendly/games.json'))
    parser.add_argument('--jobs', type=int, default=3)
    args = parser.parse_args()
    cases = [(i, 73109+10*i) for i in range(30)]
    with ProcessPoolExecutor(max_workers=args.jobs) as workers:
        rows = [row for group in workers.map(compare, cases) for row in group]
    summary = {key: summarize([r for r in rows if r['controller'] == key])
               for key in ('original', 'fixed_smooth', 'learned')}
    report = dict(model_sha256=hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest(),
                  observation='simulated positions and velocities', physics_dt=.02,
                  decision_dt=.1, summary=summary, cases=rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
