import os
import random
import time
from typing import Union
import numpy as np
from src.env.GridWorld import GridWorld
from src.env.map_objects.Resources import Resource, default_resources
from src.env.economy_objects.Marketplace import Marketplace, Order
from src.agents.actions import default_action_space_config, get_action_space_from_config, ActionHandler
from src.env.Economy import Economy
import logging
from src.react_visualization.backend.server import GridWorldReactServer
from matplotlib.colors import cnames
from src.agents.BaseAgent import BaseAgent
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

state_space_config = {
    "agent_visibility_radius": -1,
}

BaseAgentList = list[BaseAgent]


class BaseEnvironment:
    """
    Highest level class
    """
    def __init__(
            self,
            gridworld_size: Union[tuple, int] = (100, 100),
            agents: Union[BaseAgentList] = None,
            use_react: bool =True,
            verbose: int = 0,
            action_space_config: dict = default_action_space_config,
            seed: int = None
    ):
        # set gridworld size to ()
        if isinstance(gridworld_size, int):
            self.gridworld_size = (gridworld_size, gridworld_size)
        elif isinstance(gridworld_size, tuple):
            self.gridworld_size = gridworld_size
        else:
            raise TypeError("gridworld_size argument must be either an int or tuple")

        # agent specification
        if agents:
            self.set_agents(agents)
            self.n_agents = len(agents)
        else:
            self.agents = agents

        self.verbose = verbose
        self.seed = seed

        if self.seed:
            np.random.seed(self.seed)

        self.gridworld = None
        self.current_timestep = None
        self.episode = 0

        self.resource_parameters = default_resources()
        self.num_resources = len(self.resource_parameters)
        self.marketplace = Marketplace()

        # rendering the environment
        self.use_react = use_react
        self.server = GridWorldReactServer()
        self.server.run()

        self.action_space = get_action_space_from_config(action_space_config, self.num_resources)
        self.action_handler = ActionHandler(self.gridworld_size, action_space_config)
        print("action_space", self.action_space)

        self.state_space = None
        self.max_timesteps = 1_000_000
        self.cumulative_rewards = []

        # logger
        console_handler.setLevel(logging.CRITICAL)
        logger.addHandler(console_handler)

    def set_agents(self, agents: list[BaseAgent]) -> None:
        if not isinstance(agents, list):
            raise TypeError(
                "Pass a list of BaseAgents. If only one agent, pass a list of length one"
            )
        self.agents = agents
        self.n_agents = len(agents)
        print(self.n_agents, self.num_resources)
        self.state_space = (self.num_resources + self.n_agents) * (self.gridworld_size[0] * self.gridworld_size[1])
        print("state space: ", self.state_space)
        names = {}
        used_colors = set()
        hex_colors = set(cnames.values())

        id = 1
        for idx, agent in enumerate(self.agents):
            agent.id = id
            agent.n_actions = self.action_space
            agent.state_space = self.state_space
            id += 1
            if agent.color is None:
                agent.color = random.choice(list(hex_colors - used_colors))
                used_colors.add(agent.color)
            elif agent.color[0] != "#":
                try:
                    convert_to_hex_color = cnames[agent.color]
                    agent.color = convert_to_hex_color
                    used_colors.add(convert_to_hex_color)
                except:
                    agent.color = random.choice(list(hex_colors - used_colors))
                    used_colors.add(agent.color)

            # set agent name or
            # change agent name if more than one agent with the same name
            if agent.name not in names.keys():
                names[agent.name] = 0
            else:
                names[agent.name] += 1
                agent.name = agent.name + "_" + str(names[agent.name])

    def reset(self) -> [np.ndarray, dict]:
        """
        Resets the environment - including agents and gridworld
        """
        if not self.agents:
            raise ValueError("agents must be passed through the <set_agents> function before the environment"
                             "the first episode is run")
        self.current_timestep = 0
        self.episode += 1

        # reset each agent
        for agent in self.agents:
            agent.reset()

        # reset and initialize map configuration
        del self.gridworld
        self.gridworld = GridWorld(
            self.gridworld_size[0],
            self.gridworld_size[1],
            self.agents,
            self.resource_parameters,
            seed = self.seed
        )

        agent_locs = [agent.get_position() for agent in self.agents]
        hex_codes = {self.resource_parameters[r].id + 1: self.resource_parameters[r].color for r in self.resource_parameters}
        hex_codes[0] = "#8A9A5B"

        agent_names = {i: agent.name for i, agent in enumerate(self.agents)}
        if self.use_react:
            self.server.send(
                {
                    "agent_names": agent_names,
                    "gridworld_color_lookup": hex_codes,
                    "gridworld_y": self.gridworld_size[1],
                    "gridworld_x": self.gridworld_size[0],
                    "gridworld": self.gridworld.resource_ids.tolist(),
                    "agent_locations": agent_locs
                }
            )
        self.cumulative_rewards = [0 for _ in self.agents]
        return self.get_state(), {}

    def calculate_rewards(self) -> list:
        """

        """
        agent_rewards = []
        for agent in self.agents:
            reward = agent.get_reward()

            if self.gridworld.resource_ids[agent.x][agent.y] == 0:
                reward -= 5

            agent_rewards.append(reward)

        return agent_rewards

    def get_state(self) -> np.ndarray:
        return self.gridworld.get_one_hot_coding_map()

    def step(self, actions) -> [np.ndarray, list, list]:
        self.action_handler.process_actions(self.agents, actions, self.gridworld)

        if self.current_timestep >= self.max_timesteps:
            dones = [True for i in self.agents]
        else:
            dones = [False for i in self.agents]

        self.current_timestep += 1

        rewards = self.calculate_rewards()
        for idx, reward in enumerate(rewards):
            self.cumulative_rewards[idx] += reward

        if self.use_react:
            self.render_step()

        return self.get_state(), rewards, dones

    def render_step(self) -> None:
        agent_locs = [agent.get_position() for agent in self.agents]

        agent_totals = []
        for i in range(self.current_timestep):
            agent_totals_dict = {}
            for agent in self.agents:
                agent_totals_dict[agent.name] = agent.xps[i]
            agent_totals.append(agent_totals_dict)

        self.server.send(
            {
                "agent_totals": agent_totals,
                "gridworld": self.gridworld.resource_ids.tolist(),
                "agent_locations": agent_locs,
                "agent_data": [agent.inventory_history for agent in self.agents]
            }
        )

    def close(self):
        self.server.close()



