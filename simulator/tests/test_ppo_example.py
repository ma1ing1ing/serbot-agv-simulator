"""Saved-policy integrity and optional real PPO train/save/load integration."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from simulator.contracts import SCHEMA_VERSION
from simulator.examples.ppo_controller import PPOController
from simulator.examples.train_ppo import train


class PPOInputTests(unittest.TestCase):
    def test_invalid_request_never_starts_training_or_creates_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'model'
            for options in ({'steps': 0}, {'count': 9}, {'game': 'unsupported'}, {'seed': -1}):
                with self.subTest(options=options), self.assertRaises(ValueError):
                    train(output=output, **options)
                self.assertFalse(output.exists())
            output.mkdir()
            with self.assertRaisesRegex(ValueError, 'already exists'):
                train(output=output)

    def test_mismatched_game_and_replaced_weights_rejected_before_loading(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            model = directory / 'model.zip'
            # These bytes are an integrity fixture, never loaded as an ML model.
            model.write_bytes(b'integrity-fixture')
            config = dict(game='tag', observation_mode='oracle', dt=.1, guard=False,
                          schema_version=SCHEMA_VERSION,
                          model_sha256=hashlib.sha256(model.read_bytes()).hexdigest())
            (directory / 'config.json').write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, 'config must match'):
                PPOController(model, 'freeze_tag')
            model.write_bytes(b'replaced-weights')
            with self.assertRaisesRegex(ValueError, 'model_sha256'):
                PPOController(model, 'tag')


@unittest.skipUnless(all(importlib.util.find_spec(name) for name in
                        ('numpy', 'gymnasium', 'torch', 'stable_baselines3')),
                     'install training extra and stable-baselines3 for real PPO checks')
class PPOIntegrationTests(unittest.TestCase):
    def test_real_training_round_trip_and_baseline_comparison(self):
        from simulator.controllers import RuleController
        from simulator.environment import PlayEnv
        from simulator.evaluate import run

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'tag'
            path = train(game='tag', steps=256, count=1, time_limit=1, output=output)
            config = json.loads((output / 'config.json').read_text())
            self.assertEqual(config['actual_steps'], 256)
            self.assertTrue(config['training_episode_seeds'])
            self.assertEqual({item.name for item in output.iterdir()}, {'model.zip', 'config.json'})
            first, reloaded = PPOController(path, 'tag'), PPOController(path, 'tag')
            with PlayEnv(controller=first) as environment:
                observation, _ = environment.reset(seed=10000, count=1, settings={'time_limit': 1})
                self.assertEqual(first.predict(observation), reloaded.predict(observation))
                environment.step()
                self.assertGreater(environment.world.frame, 0)
            evaluation_seed = next(seed for seed in range(10000, 11000)
                                   if seed not in config['training_episode_seeds'])
            report = run(game='tag', seeds=(evaluation_seed,), count=1,
                         settings={'time_limit': 1},
                         controllers={'rule': RuleController, 'ppo': lambda: PPOController(path, 'tag')})
            self.assertEqual({row['controller'] for row in report['rows']}, {'rule', 'ppo'})
            self.assertEqual(report['controller_types']['ppo']['model_version'], first.model_version)


if __name__ == '__main__':
    unittest.main()
