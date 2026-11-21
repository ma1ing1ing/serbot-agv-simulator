"""Optional Gymnasium adapter. The base simulator requires no ML dependencies."""
from __future__ import annotations

try:
    import gymnasium as gym
    from gymnasium import spaces
    import numpy as np
except ImportError as exc:
    raise ImportError('GymPlayEnv requires: python3 -m pip install -e ".[training]"') from exc

from .environment import PlayEnv

STATES = ('missing','free','rescuing','frozen','caught','approaching','stopped','escaping','escaped','eliminated','unknown')
PHASES = ('ready','chasing','approaching','escaping','finished')
GAMES = ('tag','freeze_tag','red_light')


class GymPlayEnv(gym.Env):
    """Numeric dict observations, continuous [linear_mps, angular_rps] actions.

    No RGB rendering is claimed: browser images have their own asynchronous
    clock and are not suitable as exact step-synchronized training frames.
    """
    metadata = {'render_modes':[]}

    def __init__(self, game='tag', scenario='open', count=5, observation_mode='oracle',
                 dt=.1, settings=None, physics=None, reward_fn=None, guard=False):
        if not isinstance(guard,bool):
            raise ValueError('guard must be bool')
        self.guard = guard
        self.environment = PlayEnv(game, observation_mode=observation_mode, dt=dt,
                                   physics=physics, reward_fn=reward_fn)
        self.scenario = scenario
        self.count = count
        self.settings = settings
        self.action_space = spaces.Box(np.array([-.5,-3.],dtype=np.float32),
                                       np.array([.5,3.],dtype=np.float32),dtype=np.float32)
        self.observation_space = spaces.Dict(dict(
            robot=spaces.Box(-np.inf,np.inf,shape=(5,),dtype=np.float32),
            children=spaces.Box(-np.inf,np.inf,shape=(8,7),dtype=np.float32),
            child_mask=spaces.MultiBinary(8), game=spaces.MultiDiscrete([3,5]),
            sensors=spaces.Box(-1.,8.,shape=(4,),dtype=np.float32)))

    @staticmethod
    def encode_observation(observation):
        """Use the same numeric input for training and saved-model inference."""
        robot = observation['robot']
        children = [[c[key] for key in ('relative_x','relative_z','relative_vx','relative_vz','distance','bearing')]
                    +[STATES.index(c['state'])] for c in observation['children']]
        return dict(robot=np.asarray([robot[k] for k in ('x','z','heading','linear','angular')],dtype=np.float32),
                    children=np.asarray(children,dtype=np.float32),
                    child_mask=np.asarray(observation['child_mask'],dtype=np.int8),
                    game=np.asarray([GAMES.index(observation['game']['mode']),PHASES.index(observation['game']['phase'])],dtype=np.int64),
                    sensors=np.asarray([observation['sensors'].get(k,-1.) for k in ('front_m','left_m','right_m','rear_m')],dtype=np.float32))

    # Compatibility with callers written before the shared encoder was public.
    _encode = encode_observation

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        options = options or {}
        if not isinstance(options,dict) or set(options)-{'scenario','count','settings','record','record_dir','split'}:
            raise ValueError('unsupported reset options')
        if seed is None:
            seed = int(self.np_random.integers(0,2**32))
        observation, info = self.environment.reset(seed=seed,
            scenario=options.get('scenario',self.scenario), count=options.get('count',self.count),
            settings=options.get('settings',self.settings),record=options.get('record',False),
            record_dir=options.get('record_dir'),split=options.get('split','interactive'))
        info.pop('epoch',None)
        return self.encode_observation(observation),info

    def step(self, action):
        value = np.asarray(action,dtype=np.float32)
        if not self.action_space.contains(value):
            raise ValueError('action must be a finite [linear_mps, angular_rps] within bounds')
        observation,reward,terminated,truncated,info = self.environment.step(dict(linear_mps=float(value[0]),angular_rps=float(value[1]),guard=self.guard))
        info.pop('epoch',None)
        return self.encode_observation(observation),reward,terminated,truncated,info

    def close(self):
        self.environment.close()
