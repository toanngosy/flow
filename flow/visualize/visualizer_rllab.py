"""Visualizer for rllab-trained experiments."""

import argparse
import joblib
import numpy as np
import os

from flow.core.util import emission_to_csv

from rllab.sampler.utils import rollout


def visualizer_rllab(args):
    # extract the flow environment
    data = joblib.load(args.file)
    policy = data['policy']
    env = data['env']

    # FIXME(ev, ak) only one of these should be needed
    # unwrapped_env = env._wrapped_env._wrapped_env.env.unwrapped
    # unwrapped_env = env.wrapped_env.env.env.unwrapped

    # if this doesn't work, try the one above it
    unwrapped_env = env._wrapped_env.env.unwrapped

    # Set sumo to make a video
    sim_params = unwrapped_env.sim_params
    sim_params.emission_path = './test_time_rollout/'
    if args.no_render:
        sim_params.render = False
    else:
        sim_params.render = True
    unwrapped_env.restart_simulation(
        sim_params=sim_params, render=sim_params.render)

    # Load data into arrays
    rew = []
    for j in range(args.num_rollouts):
        # run a single rollout of the experiment
        path = rollout(env=env, agent=policy)

        # collect the observations and rewards from the rollout
        new_rewards = path['rewards']

        # print the cumulative reward of the most recent rollout
        print('Round {}, return: {}'.format(j, sum(new_rewards)))
        rew.append(sum(new_rewards))

    # print the average cumulative reward across rollouts
    print('Average, std return: {}, {}'.format(np.mean(rew), np.std(rew)))

    # if prompted, convert the emission file into a csv file
    if args.emission_to_csv:
        dir_path = os.path.dirname(os.path.realpath(__file__))
        emission_filename = '{0}-emission.xml'.format(
            unwrapped_env.scenario.name)

        emission_path = \
            '{0}/test_time_rollout/{1}'.format(dir_path, emission_filename)

        emission_to_csv(emission_path)


def create_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('file', type=str, help='path to the snapshot file')
    parser.add_argument(
        '--num_rollouts',
        type=int,
        default=100,
        help='Number of rollouts we will average over')
    parser.add_argument(
        '--no_render',
        action='store_true',
        help='Whether to render the result')
    parser.add_argument(
        '--plotname',
        type=str,
        default='traffic_plot',
        help='Prefix for all generated plots')
    parser.add_argument(
        '--emission_to_csv',
        action='store_true',
        help='Specifies whether to convert the emission file '
             'created by sumo into a csv file')
    return parser


if __name__ == '__main__':
    parser = create_parser()
    args = parser.parse_args()
    visualizer_rllab(args)
