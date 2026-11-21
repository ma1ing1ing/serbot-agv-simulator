"""Recording and explicit generation are tested only in disposable directories."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from simulator.engine import World
from simulator.batch import run
from simulator.tests.test_games import advance
from simulator.tests.test_http_routes import RouteTests


def read_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


class RecordingTests(unittest.TestCase):
    def test_recording_is_off_by_default_and_creates_no_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'not-created'
            w = World(record_root=root)
            w.start_game('freeze_tag')
            advance(w, 1)
            w.finish_game()
            self.assertFalse(root.exists())
            self.assertFalse(w.episode.metadata()['recording'])

    def test_four_files_common_clock_and_external_observation(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)/'episode'
            w = World()
            w.start_game('tag', False, seed=71, record=True, record_dir=directory, settings={'time_limit':1})
            w.note_observation({'frame_id':12, 'detections':[]}, 'camera_model')
            advance(w, 1)
            self.assertEqual({p.name for p in directory.iterdir()}, {'config.json','steps.jsonl','events.jsonl','summary.json'})
            steps = read_lines(directory/'steps.jsonl')
            events = read_lines(directory/'events.jsonl')
            self.assertEqual(len(steps), 11)
            self.assertEqual([s['tick'] for s in steps], list(range(0, 51, 5)))
            self.assertIsNone(steps[0]['robot_observation'])
            self.assertEqual(steps[1]['robot_observation']['source'], 'camera_model')
            self.assertEqual(steps[1]['robot_observation']['value']['frame_id'], 12)
            self.assertTrue(steps[-1]['truncated'])
            self.assertFalse(steps[-1]['terminated'])
            self.assertEqual([e['kind'] for e in events].count('episode_end'), 1)
            summary = json.loads((directory/'summary.json').read_text())
            self.assertEqual(summary['samples'], 11)
            self.assertEqual(summary['end_reason'], 'time_limit')
            self.assertEqual(len(json.loads((directory/'config.json').read_text())['code_sha256']), 64)

    def test_reset_restart_and_manual_finish_flush_the_old_recording(self):
        with tempfile.TemporaryDirectory() as temp:
            for action in ('reset', 'restart', 'user_stopped'):
                directory = Path(temp)/action
                w = World(); w.start_game(record=True, record_dir=directory)
                advance(w, .22)
                if action == 'reset': w.reset()
                elif action == 'restart': w.start_game('freeze_tag')
                else: w.finish_game()
                summary = json.loads((directory/'summary.json').read_text())
                self.assertEqual(summary['end_reason'], 'reset' if action == 'restart' else action)
                if action == 'user_stopped':
                    w.finish_game()
                    self.assertEqual(len([e for e in read_lines(directory/'events.jsonl') if e['kind']=='episode_end']), 1)

    def test_oracle_observation_is_labelled_and_velocities_use_real_movement(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)/'episode'
            w = World(); w.start_game(record=True, record_dir=directory)
            advance(w, .1); w.finish_game()
            step = read_lines(directory/'steps.jsonl')[1]
            self.assertEqual(step['robot_observation']['source'], 'oracle')
            self.assertLessEqual(step['robot_observation']['time'], step['time'])
            self.assertIn('vx', step['ground_truth']['children'][0])
            self.assertGreater(abs(step['ground_truth']['robot']['vz']), 0)

    def test_existing_output_and_invalid_configuration_never_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            w = World(); before = w.snapshot()
            with self.assertRaises(ValueError): w.start_game(record=True, record_dir=temp)
            self.assertEqual(w.snapshot(), before)
            with self.assertRaises(ValueError): run(Path(temp)/'invalid', episodes=0)
            self.assertFalse((Path(temp)/'invalid').exists())

    def test_explicit_batch_separates_seeds_and_writes_all_summaries(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'batch'
            with patch('builtins.print'):
                result = run(root, episodes=10, time_limit=1)
            self.assertEqual(result['status'], 'completed')
            entries = read_lines(root/'index.jsonl')
            self.assertEqual(len(entries), 30)
            seeds = {s:{e['seed'] for e in entries if e['split']==s} for s in ('train','validation','test')}
            self.assertFalse(seeds['train'] & seeds['test'])
            self.assertFalse(seeds['train'] & seeds['validation'])
            self.assertFalse(seeds['test'] & seeds['validation'])
            for entry in entries:
                self.assertTrue((root/entry['path']/'summary.json').exists())

    def test_interrupt_preserves_summary_and_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'batch'
            with patch.object(World, 'tick', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
                run(root, episodes=1)
            self.assertEqual(json.loads((root/'manifest.json').read_text())['status'], 'interrupted')
            summaries = list(root.rglob('summary.json'))
            self.assertEqual(len(summaries), 1)
            self.assertEqual(json.loads(summaries[0].read_text())['end_reason'], 'batch_interrupted')


class RecordingRouteTests(unittest.TestCase):
    request = RouteTests.request

    def setUp(self):
        RouteTests.setUp(self)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.world.record_root = Path(temp.name)/'episodes'

    def test_recording_observation_and_finish_routes(self):
        status, _ = self.request('/api/game/start', {'mode':'freeze_tag','record':True})
        self.assertEqual(status, 200)
        directory = Path(self.world.episode.metadata()['directory'])
        self.assertEqual(self.request('/api/game/auto', {'enabled':False})[0], 200)
        self.assertEqual(self.request('/api/episode/observation', {'value':{'frame_id':7}})[0], 200)
        self.assertEqual(self.request('/api/game/finish', {})[0], 200)
        self.assertTrue(self.request('/api/episode')[1]['closed'])
        self.assertTrue((directory/'summary.json').exists())


if __name__ == '__main__':
    unittest.main()
