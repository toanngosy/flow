from cistar.envs.loop import LoopEnvironment
from cistar.core import rewards
from cistar.controllers.car_following_models import *

from gym.spaces.box import Box
from gym.spaces.tuple_space import Tuple
import numpy as np
from numpy.random import normal


class SimpleLaneChangingAccelerationEnvironment(LoopEnvironment):
    """
    Fully functional environment. Takes in an *acceleration* as an action. Reward function is negative norm of the
    difference between the velocities of each vehicle, and the target velocity. State function is a vector of the
    velocities for each vehicle.
    """

    @property
    def action_space(self):
        """
        Actions are:
         - a (continuous) acceleration from max-deacc to max-acc
         - a (continuous) direction with 3 values: 0) lane change to index -1, 1) no lane change,
                                                   2) lane change to index +1
        :return:
        """
        max_deacc = self.env_params.get_additional_param("max-deacc")
        max_acc = self.env_params.get_additional_param("max-acc")

        lb = [-abs(max_deacc), -1] * self.vehicles.num_rl_vehicles
        ub = [max_acc, 1] * self.vehicles.num_rl_vehicles
        return Box(np.array(lb), np.array(ub))

    @property
    def observation_space(self):
        """
        See parent class
        An observation consists of the velocity, lane index, and absolute position of each vehicle
        in the fleet
        """

        speed = Box(low=-np.inf, high=np.inf, shape=(self.vehicles.num_vehicles,))
        lane = Box(low=0, high=self.scenario.lanes-1, shape=(self.vehicles.num_vehicles,))
        absolute_pos = Box(low=0., high=np.inf, shape=(self.vehicles.num_vehicles,))
        return Tuple((speed, lane, absolute_pos))

    def compute_reward(self, state, rl_actions, **kwargs):
        """
        See parent class
        """
        # compute the system-level performance of vehicles from a velocity perspective
        reward = rewards.desired_velocity(self, fail=kwargs["fail"])

        # punish excessive lane changes by reducing the reward by a set value every time an rl car changes lanes
        for veh_id in self.rl_ids:
            if self.vehicles.get_state(veh_id, "last_lc") == self.timer:
                reward -= 1

        return reward

    def get_state(self):
        """
        See parent class
        The state is an array the velocities for each vehicle
        :return: an array of vehicle speed for each vehicle
        """
        return np.array([[self.vehicles.get_speed(veh_id) + normal(0, self.observation_vel_std),
                          self.vehicles.get_absolute_position(veh_id) + normal(0, self.observation_pos_std),
                          self.vehicles.get_lane(veh_id)] for veh_id in self.sorted_ids])

    def apply_rl_actions(self, actions):
        """
        Takes a tuple and applies a lane change or acceleration. if a lane change is applied,
        don't issue any commands for the duration of the lane change and return negative rewards
        for actions during that lane change. if a lane change isn't applied, and sufficient time
        has passed, issue an acceleration like normal
        :param actions: (acceleration, lc_value, direction)
        :return: array of resulting actions: 0 if successful + other actions are ok, -1 if unsucessful / bad actions.
        """
        # acceleration = actions[-1]
        # direction = np.array(actions[:-1]) - 1

        acceleration = actions[::2]
        direction = np.round(actions[1::2])

        # re-arrange actions according to mapping in observation space
        sorted_rl_ids = [veh_id for veh_id in self.sorted_ids if veh_id in self.rl_ids]

        # represents vehicles that are allowed to change lanes
        non_lane_changing_veh = [self.timer <= self.lane_change_duration + self.vehicles.get_state(veh_id, 'last_lc')
                                 for veh_id in sorted_rl_ids]
        # vehicle that are not allowed to change have their directions set to 0
        direction[non_lane_changing_veh] = np.array([0] * sum(non_lane_changing_veh))

        self.apply_acceleration(sorted_rl_ids, acc=acceleration)
        self.apply_lane_change(sorted_rl_ids, direction=direction)


class LaneChangeOnlyEnvironment(SimpleLaneChangingAccelerationEnvironment):

    def __init__(self, env_params, sumo_params, scenario):

        super().__init__(env_params, sumo_params, scenario)

        # longitudinal (acceleration) controller used for rl cars
        self.rl_controller = dict()

        for veh_id in self.rl_ids:
            controller_params = env_params.get_additional_param("rl_acc_controller")
            self.rl_controller[veh_id] = controller_params[0](veh_id=veh_id, **controller_params[1])

    @property
    def action_space(self):
        """
        Actions are: a continuous direction for each rl vehicle
        """
        return Box(low=-1, high=1, shape=(self.vehicles.num_rl_vehicles,))

    @property
    def observation_space(self):
        """
        See parent class
        An observation consists of the velocity, lane index, and absolute position of each vehicle
        in the fleet
        """
        speed = Box(low=-np.inf, high=np.inf, shape=(self.vehicles.num_vehicles,))
        lane = Box(low=0, high=self.scenario.lanes-1, shape=(self.vehicles.num_vehicles,))
        absolute_pos = Box(low=0., high=np.inf, shape=(self.scenario.num_vehicles,))
        return Tuple([speed, lane, absolute_pos])

    def compute_reward(self, state, rl_actions, **kwargs):
        """
        See parent class
        """
        # compute the system-level performance of vehicles from a velocity perspective
        reward = rewards.desired_velocity(self, fail=kwargs["fail"])

        # punish excessive lane changes by reducing the reward by a set value every time an rl car changes lanes
        for veh_id in self.rl_ids:
            if self.vehicles[veh_id]["last_lc"] == self.timer:
                reward -= 1

        return reward

    def get_state(self):
        """
        See parent class
        """
        return np.array([[self.vehicles[veh_id]["speed"] + normal(0, self.observation_vel_std),
                          self.vehicles[veh_id]["absolute_position"] + normal(0, self.observation_pos_std),
                          self.vehicles[veh_id]["lane"]] for veh_id in self.sorted_ids])

    def apply_rl_actions(self, actions):
        """
        see parent class
        - accelerations are derived using the IDM equation
        - lane-change commands are collected from rllab
        """
        direction = actions

        # re-arrange actions according to mapping in observation space
        sorted_rl_ids = [veh_id for veh_id in self.sorted_ids if veh_id in self.rl_ids]

        # represents vehicles that are allowed to change lanes
        non_lane_changing_veh = [self.timer <= self.lane_change_duration + self.vehicles[veh_id]['last_lc']
                                 for veh_id in sorted_rl_ids]
        # vehicle that are not allowed to change have their directions set to 0
        direction[non_lane_changing_veh] = np.array([0] * sum(non_lane_changing_veh))

        self.apply_lane_change(sorted_rl_ids, direction=direction)

        # collect the accelerations for the rl vehicles as specified by the human controller
        acceleration = []
        for veh_id in sorted_rl_ids:
            acceleration.append(self.rl_controller[veh_id].get_action(self))

        self.apply_acceleration(sorted_rl_ids, acc=acceleration)

































class RLOnlyLane(SimpleLaneChangingAccelerationEnvironment):

    def compute_reward(self, state, action, **kwargs):
        """
        See parent class
        """

        if any(state[0] < 0) or kwargs["fail"]:
            return -20.0

        #
        # flag = 1
        # # max_cost3 = np.array([self.env_params["target_velocity"]]*len(self.rl_ids))
        # # max_cost3 = np.linalg.norm(max_cost3)
        # # cost3 = [self.vehicles[veh_id]["speed"] - self.env_params["target_velocity"] for veh_id in self.rl_ids]
        # # cost3 = np.linalg.norm(cost)
        # # for i, veh_id in enumerate(self.rl_ids):
        # #     if self.vehicles[veh_id]["lane"] != 0:
        # #         flag = 1
        #
        # if flag:
        #     return max_cost - cost - cost2
        # else:
        #     return (max_cost - cost) + (max_cost3 - cost3) - cost2

        reward_type = 1

        if reward_type == 1:
            # this reward type only rewards the velocity of the rl vehicle if it is in lane zero
            # otherwise, the reward function perceives the velocity of the rl vehicles as 0 m/s

            max_cost = np.array([self.env_params.get_additional_param("target_velocity")]*self.scenario.num_vehicles)
            max_cost = np.linalg.norm(max_cost)

            vel = state[0]
            lane = state[1]
            vel[lane != 0] = np.array([0] * sum(lane != 0))

            cost = vel - self.env_params.get_additional_param("target_velocity")
            cost = np.linalg.norm(cost)

            return max(max_cost - cost, 0)

        elif reward_type == 2:
            # this reward type only rewards non-rl vehicles, and penalizes rl vehicles for being
            # in the wrong lane

            # reward for only non-rl vehicles
            max_cost = np.array([self.env_params.get_additional_param("target_velocity")]*len(self.controlled_ids))
            max_cost = np.linalg.norm(max_cost)

            cost = [self.vehicles[veh_id]["speed"] - self.env_params.get_additional_param("target_velocity")
                    for veh_id in self.controlled_ids]
            cost = np.linalg.norm(cost)

            # penalty for being in the other lane
            # calculate how long the cars have been in the left lane
            left_lane_cost = np.zeros(len(self.rl_ids))
            for i, veh_id in enumerate(self.rl_ids):
                if self.vehicles[veh_id]["lane"] != 0:
                    # method 1:
                    # if its possible to lane change and we are still hanging out in the left lane
                    # start penalizing it
                    # left_lane_cost[i] = np.max([0, (self.timer - self.vehicles[veh_id]['last_lc'] -
                    #                                 self.lane_change_duration)])

                    # method 2:
                    # penalize the left lane in increasing amount from the start
                    left_lane_cost[i] = self.timer/20

            cost2 = np.linalg.norm(np.array(left_lane_cost))/10

            return max_cost - cost - cost2

    @property
    def observation_space(self):
        """
        See parent class
        An observation consists of the velocity, lane index, and absolute position of each vehicle
        in the fleet
        """
        speed = Box(low=0, high=np.inf, shape=(self.scenario.num_vehicles,))
        lane = Box(low=0, high=self.scenario.lanes-1, shape=(self.scenario.num_vehicles,))
        pos = Box(low=0., high=np.inf, shape=(self.scenario.num_vehicles,))
        return Tuple((speed, lane, pos))

    def get_state(self):
        """
        See parent class
        The state is an array the velocities for each vehicle
        :return: an array of vehicle speed for each vehicle
        """
        # sorting states by position
        sorted_indx = np.argsort([self.vehicles[veh_id]["absolute_position"] for veh_id in self.ids])
        sorted_ids = np.array(self.ids)[sorted_indx]

        return np.array([[self.vehicles[veh_id]["speed"],
                          self.vehicles[veh_id]["lane"],
                          self.vehicles[veh_id]["absolute_position"]] for veh_id in sorted_ids])

    # def render(self):
    #     print('current velocity, lane, headway, adj headway:', self.state)