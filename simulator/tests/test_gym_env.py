"""Optional real Gymnasium compatibility checks, not a mocked substitute."""
import importlib.util
import unittest


@unittest.skipUnless(importlib.util.find_spec('gymnasium') and importlib.util.find_spec('numpy'),
                     'install the optional training extra for Gymnasium checks')
class GymTests(unittest.TestCase):
    def test_official_environment_checker_and_fixed_shapes(self):
        from gymnasium.utils.env_checker import check_env
        from simulator.gym_env import GymPlayEnv
        env=GymPlayEnv(settings={'time_limit':1})
        try:
            check_env(env,skip_render_check=True)
            obs,info=env.reset(seed=4)
            self.assertTrue(env.observation_space.contains(obs))
            self.assertEqual(obs['children'].shape,(8,7))
            self.assertEqual(obs['child_mask'].sum(),5)
            obs,*_=env.step(env.action_space.sample())
            self.assertTrue(env.observation_space.contains(obs))
        finally:env.close()

    def test_sensor_mask_and_invalid_action(self):
        from simulator.gym_env import GymPlayEnv
        env=GymPlayEnv(observation_mode='sensor')
        try:
            obs,_=env.reset(seed=1)
            self.assertEqual(obs['child_mask'].sum(),0)
            with self.assertRaises(ValueError):env.step([2,0])
        finally:env.close()


if __name__=='__main__':unittest.main()
