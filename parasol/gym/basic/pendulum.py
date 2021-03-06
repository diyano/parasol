from deepx import T
import cv2
import numpy as np
import gym
from gym import spaces
from gym.utils import seeding
from os import path

from ..utils import ImageEncoder
from ..gym_wrapper import GymWrapper

__all__ = ['Pendulum']

class GymPendulum(gym.Env):
    metadata = {
        'render.modes' : ['human', 'rgb_array'],
        'video.frames_per_second' : 30
    }

    def __init__(self, *args, **kwargs):
        self.__dict__.update(kwargs)
        self.max_speed=8
        self.max_torque=2.
        self.dt=.05
        self.viewer = None

        # modify from original gym env for (potential) images
        if self.image:
            obs_size = self.image_dim ** 2 * 3 * (self.sliding_window + 1)
            self.observation_space = spaces.Box(low=np.zeros(obs_size), high=np.ones(obs_size), dtype=np.float32)
        else:
            high = np.array([1., 1., self.max_speed])
            self.observation_space = spaces.Box(low=-high, high=high, dtype=np.float32)

        self.action_space = spaces.Box(low=-self.max_torque, high=self.max_torque, shape=(1,), dtype=np.float32)

        self.seed()

    def seed(self, seed=None):
        self.np_random, seed = seeding.np_random(seed)
        return [seed]

    def step(self,u):
        th, thdot = self.state # th := theta

        g = 10.
        m = 1.
        l = 1.
        dt = self.dt

        u = np.clip(u, -self.max_torque, self.max_torque)[0]
        if not self.image:
            self.last_u = u # for rendering
        costs = angle_normalize(th)**2 + .1*thdot**2 + .001*(u**2)

        newthdot = thdot + (-3*g/(2*l) * np.sin(th + np.pi) + 3./(m*l**2)*u) * dt
        newth = th + newthdot*dt
        newthdot = np.clip(newthdot, -self.max_speed, self.max_speed) #pylint: disable=E1111

        self.state = np.array([newth, newthdot])
        return self._get_obs(), -costs, False, {}

    def reset(self):
        if self.sliding_window:
            self._prev_img = None
        # modify from original gym env to fix starting state
        high = np.array([0.01, 0.01])
        self.state = self.np_random.uniform(low=-high, high=high) + np.array([np.pi, 0])
        self.last_u = None
        return self._get_obs()

    def _get_obs(self):
        if self.image:
            img = cv2.resize(self.render(mode='rgb_array'),
                             (self.image_dim, self.image_dim),
                             interpolation=cv2.INTER_LINEAR) / 255
            if self.sliding_window:
                if not self._prev_img:
                    self._prev_img = [img] * self.sliding_window
                obs = [img] + self._prev_img
                self._prev_img = obs[:-1]
                return np.concatenate(obs, axis=-1).flatten()
            return img.flatten()
        theta, thetadot = self.state
        return np.array([np.cos(theta), np.sin(theta), thetadot])

    def render(self, mode='human'):

        if self.viewer is None:
            from gym.envs.classic_control import rendering
            self.viewer = rendering.Viewer(500,500)
            self.viewer.set_bounds(-2.2,2.2,-2.2,2.2)
            rod = rendering.make_capsule(1, .2)
            rod.set_color(.8, .3, .3)
            self.pole_transform = rendering.Transform()
            rod.add_attr(self.pole_transform)
            self.viewer.add_geom(rod)
            axle = rendering.make_circle(.05)
            axle.set_color(0,0,0)
            self.viewer.add_geom(axle)
            if not self.image:
                fname = path.join(path.dirname(__file__), "assets/clockwise.png")
                self.img = rendering.Image(fname, 1., 1.)
                self.imgtrans = rendering.Transform()
                self.img.add_attr(self.imgtrans)

        if not self.image:
            self.viewer.add_onetime(self.img)
        self.pole_transform.set_rotation(self.state[0] + np.pi/2)
        if self.last_u:
            self.imgtrans.scale = (-self.last_u/2, np.abs(self.last_u)/2)

        return self.viewer.render(return_rgb_array = mode=='rgb_array')

    def close(self):
        if self.viewer:
            self.viewer.close()
            self.viewer = None

def angle_normalize(x):
    return (((x+np.pi) % (2*np.pi)) - np.pi)

class Pendulum(GymWrapper):

    environment_name = 'Pendulum'
    reward_threshold = -3.75
    entry_point = "parasol.gym.basic.pendulum:GymPendulum"
    max_episode_steps = 200

    def __init__(self, **kwargs):
        config = {
            'image': kwargs.pop('image', False),
            'sliding_window': kwargs.pop('sliding_window', 0),
            'image_dim': kwargs.pop('image_dim', 32),
        }
        super(Pendulum, self).__init__(config)

    def make_summary(self, observations, name):
        if self.image:
            observations = T.reshape(observations, [-1] + self.image_size())
            T.core.summary.image(name, observations)

    def is_image(self):
        return self.image

    def image_size(self):
        if self.image:
            return [self.image_dim, self.image_dim, 3]
        return None

    def start_recording(self, video_path):
        frame_shape = (500, 500, 3)
        self.image_encoder = ImageEncoder(video_path, frame_shape, 30)

    def grab_frame(self):
        frame = self.render(mode='rgb_array')
        self.image_encoder.capture_frame(frame)

    def stop_recording(self):
        self.image_encoder.close()

    def cost_fn(self, s, a):
        cos_th, sin_th = s[:,0], s[:,1]
        th = np.arctan2(sin_th, cos_th)

        thdot = s[:,2]
        return angle_normalize(th)**2 + .1*thdot**2 + .001*(np.squeeze(a)**2)

    def torque_matrix(self):
        return 0.002 * np.eye(self.get_action_dim())
