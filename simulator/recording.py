"""Opt-in streaming records, with evaluation truth separate from model inputs."""
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path

from . import games, serbot_sensors


def source_hash():
    digest = hashlib.sha256()
    for name in ('engine.py','games.py','recording.py','contracts.py','controllers.py','motion.py','environment.py','scenarios.py','serbot_sensors.py','referee_route.py','friendly_controller.py','friendly_policy.py','models/friendly_referee_v1.json'):
        digest.update((Path(__file__).parent/name).read_bytes())
    return digest.hexdigest()


# Capture the loaded version once, even if source files change while a server runs.
CODE_SHA256 = source_hash()


def dump(path, value):
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)+'\n', encoding='utf-8')
    temporary.replace(path)


class Episode:
    def __init__(self, world, directory=None, *, split='interactive'):
        self.directory = Path(directory) if directory is not None else None
        self.closed = False
        self.counts = Counter()
        self.sequence = 0
        self.samples = 0
        self.minimum_distance = None
        self.observation = None
        self.files = {}
        self.summary = None
        self.config = dict(schema_version=2, game=world.game['mode'], seed=world.game['seed'],
                           split=split, rules=copy.deepcopy(world.rules), policy_version=games.VERSION,
                           code_sha256=CODE_SHA256, physics_dt=.02, record_interval=.1,
                           physics=copy.deepcopy(world.physics), scenario=copy.deepcopy(world.scenario),
                           execution_mode=world.execution_mode, control_dt=world.control_dt,
                           observation_mode=world.controller_observation_mode,
                           controller=world.controller_name,
                           units=dict(position='m', time='s', angle='rad'), ground_axes=['x', 'z'],
                           roles=dict(robot='tagger', children='players'),
                           provenance=dict(positions='synthetic_game_rules', animation='ChildACT_if_available_else_procedural',
                                           playground_a_used=False, learned_child_policy=False),
                           initial_state=dict(robot=copy.deepcopy(world.robot), children=copy.deepcopy(world.children),
                                              obstacles=copy.deepcopy(world.obstacles), bounds=world.bounds))
        if getattr(world, 'serbot_sensors', False):
            self.config['serbot_sensors'] = serbot_sensors.SCHEMA
        if self.directory is not None:
            self.directory.mkdir(parents=True, exist_ok=False)
            try:
                dump(self.directory/'config.json', self.config)
                for name in ('steps', 'events'):
                    self.files[name] = (self.directory/(name+'.jsonl')).open('w', encoding='utf-8')
            except BaseException:
                for handle in self.files.values():
                    handle.close()
                raise

    def write(self, name, value):
        if name in self.files:
            self.files[name].write(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))+'\n')

    def event(self, world, kind, actor=None, target=None, **details):
        if self.closed:
            return
        self.sequence += 1
        self.counts[kind] += 1
        ident = target if target is not None else actor
        who = next((c for c in world.children if c['id'] == ident), world.robot)
        self.write('events', dict(event_id=self.sequence, time=world.time, tick=world.frame,
                                 game_time=world.game.get('elapsed', 0.), kind=kind, actor=actor, target=target,
                                 position=dict(x=who['x'], z=who['z']), **details))

    def update(self, world, previous):
        if self.closed:
            return
        distances = [games.distance(c, world.robot) for c in world.children]
        if distances:
            nearest = min(distances)
            self.minimum_distance = nearest if self.minimum_distance is None else min(self.minimum_distance, nearest)
        if world.frame % 5 == 0 or world.game['phase'] == 'finished':
            self.sample(world, previous)
        if world.game['phase'] == 'finished':
            self.close(world)

    def sample(self, world, previous=None):
        if self.closed:
            return
        truth = dict(robot=copy.deepcopy(world.robot), children=copy.deepcopy(world.children), game=copy.deepcopy(world.game))
        actors = [('robot', truth['robot'])]+[(c['id'], c) for c in truth['children']]
        for ident, actor in actors:
            before = (previous or {}).get(ident, actor)
            actor['vx'] = (actor['x']-before['x'])/.02
            actor['vz'] = (actor['z']-before['z'])/.02
        observation = copy.deepcopy(world.observation if world.game['auto_chase'] else self.observation)
        self.write('steps', dict(sample=self.samples, tick=world.frame, time=world.time,
                                 game_time=world.game['elapsed'], ground_truth=truth,
                                 robot_observation=observation,
                                 robot_action=dict(controller=world.controller_name,
                                                   linear=world.robot['linear'], angular=world.robot['angular'],
                                                   target_id=world.game['target_id']),
                                 requested_action=copy.deepcopy(world.requested_action),
                                 action_input=copy.deepcopy(world.action_input),
                                 action_received_tick=world.action_received_tick,
                                 applied_action=dict(linear_mps=world.robot['linear'],angular_rps=world.robot['angular']),
                                 robot_command=world.motion, terminal=world.game['phase'] == 'finished',
                                 terminated=world.game['phase'] == 'finished' and world.game['end_reason'] != 'time_limit',
                                 truncated=world.game.get('end_reason') == 'time_limit'))
        self.samples += 1
        for handle in self.files.values():
            handle.flush()

    def close(self, world):
        if self.closed:
            return
        self.summary = dict(schema_version=2, game=world.game['mode'], seed=world.game['seed'],
                            split=self.config['split'], end_reason=world.game['end_reason'],
                            simulation_time=world.time, game_time=world.game['elapsed'],
                            samples=self.samples, events=dict(self.counts),
                            caught_ids=list(world.game['caught_ids']), escaped_ids=list(world.game['escaped_ids']),
                            minimum_robot_child_distance=self.minimum_distance, robot_distance=world.distance,
                            collision_count=self.counts['collision'],
                            collision_prevented_count=self.counts['collision_prevented'],
                            metrics=copy.deepcopy(world.metrics))
        try:
            for handle in self.files.values():
                handle.close()
            if self.directory is not None:
                dump(self.directory/'summary.json', self.summary)
        finally:
            self.closed = True

    def transition(self, previous, action, observation, reward, terminated, truncated, info):
        """Exact control-boundary tuples, separate from sampled render states."""
        if self.directory is not None:
            row = dict(schema_version=2, observation=previous, action=action.to_dict(),
                       next_observation=observation, reward=reward, terminated=terminated,
                       truncated=truncated, start_tick=previous['tick'], end_tick=observation['tick'],
                       start_time=previous['time'], end_time=observation['time'],
                       event_delta=info['event_delta'], metrics_delta=info['metrics_delta'])
            with (self.directory/'transitions.jsonl').open('a',encoding='utf-8') as handle:
                handle.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
        if self.summary is not None:
            self.summary['metrics'] = copy.deepcopy(info['metrics'])
            if self.directory is not None:
                dump(self.directory/'summary.json',self.summary)

    def metadata(self):
        return dict(recording=self.directory is not None, directory=str(self.directory) if self.directory else None,
                    closed=self.closed, samples=self.samples, events=dict(self.counts), summary=self.summary)
