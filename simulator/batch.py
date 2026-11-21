"""Opt-in headless dataset generation. Importing this module never runs games."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from .engine import World
from . import games
from .recording import dump


def split_for(index):
    return 'train' if index % 10 < 8 else 'validation' if index % 10 == 8 else 'test'


def run(output, *, modes=games.MODES, episodes=100, seed=0, count=5, time_limit=120.):
    modes = tuple(modes)
    if not modes or len(set(modes)) != len(modes) or not set(modes) <= set(games.MODES):
        raise ValueError('중복 없는 게임 목록이 필요합니다')
    if not isinstance(episodes, int) or not 1 <= episodes <= 100000:
        raise ValueError('episodes: 1 ~ 100000')
    if not isinstance(count, int) or not 1 <= count <= 8:
        raise ValueError('count: 1 ~ 8')
    games.options(modes[0], seed, {'time_limit':time_limit})
    games.options(modes[0], seed+episodes-1, {'time_limit':time_limit})
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    manifest = dict(schema_version=1, policy_version=games.VERSION, seed=seed, games=list(modes),
                    episodes_per_game=episodes, count=count, time_limit=time_limit,
                    split_strategy='index_mod_10: train 0..7, validation 8, test 9; same seed stays in same split across games',
                    status='running', completed=0)
    dump(root/'manifest.json', manifest)
    world = World()
    try:
        with (root/'index.jsonl').open('w', encoding='utf-8') as index_file:
            for mode in modes:
                for index in range(episodes):
                    split = split_for(index)
                    directory = root/split/mode/f'{seed+index:010d}'
                    world.reset()
                    world.set_count(count)
                    world.start_game(mode, seed=seed+index, settings={'time_limit':time_limit},
                                     record=True, record_dir=directory, split=split)
                    while world.game['phase'] != 'finished':
                        world.tick(.02)
                    entry = dict(path=directory.relative_to(root).as_posix(), **world.episode.summary)
                    index_file.write(json.dumps(entry, ensure_ascii=False, allow_nan=False)+'\n')
                    index_file.flush()
                    manifest['completed'] += 1
                    dump(root/'manifest.json', manifest)
                print(f'{mode}: {episodes}판 완료', flush=True)
        manifest['status'] = 'completed'
    except BaseException:
        world.finish_game('batch_interrupted')
        manifest['status'] = 'interrupted'
        raise
    finally:
        dump(root/'manifest.json', manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description='세 가지 놀이의 가상 상호작용 데이터 생성')
    parser.add_argument('--games', nargs='+', choices=games.MODES, default=list(games.MODES))
    parser.add_argument('--episodes', type=int, default=100, help='게임별 판 수')
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--count', type=int, default=5)
    parser.add_argument('--time-limit', type=float, default=120)
    name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:6]
    parser.add_argument('--output', type=Path, default=Path('artifacts/datasets')/name)
    args = parser.parse_args()
    try:
        run(args.output, modes=args.games, episodes=args.episodes, seed=args.seed,
            count=args.count, time_limit=args.time_limit)
    except (ValueError, OSError) as exc:
        parser.exit(1, str(exc)+'\n')
    except KeyboardInterrupt:
        parser.exit(130, '중단했습니다. 완료된 판과 중단 사유는 저장되어 있습니다.\n')
    print(f'저장: {args.output.resolve()}')


if __name__ == '__main__':
    main()
