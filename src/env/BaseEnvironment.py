import random
import time
from typing import Union
import numpy as np
from src.env.GridWorld import GridWorld
from src.env.map_objects.Resources import Resource, default_resources
from src.env.economy_objects.Marketplace import Marketplace, Order
from src.agents.actions import default_action_space_config, ActionHandler
from src.env.Economy import Economy
import logging
from src.react_visualization.backend.DataBaseServer import DatabaseServer
from src.react_visualization.backend.mongoDB_connection import MongoDBClient
from src.react_visualization.backend.ReactServer import ReactServer
from matplotlib.colors import cnames

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

state_space_config = {
    "agent_visibility_radius": -1,
}


class BaseEnvironment:
    """
    class that represents an instance of the highest-level.

    uses the classic gymnasium style environment format
    """

    def __init__(
            self,
            size: Union[tuple, int] = (100, 100),
            max_steps: int = 1000,
            agents: list = None,
            verbose: int = 0,
            seed: int = None,
            use_react: bool = True,
            use_mongodb: bool = True
    ):
        # set gridworld size
        if isinstance(size, int):
            self.gridworld_size = (size, size)
        elif isinstance(size, tuple):
            self.gridworld_size = size
        else:
            raise TypeError("gridworld_size argument must be either an int or tuple")

        self.resources = default_resources()
        self.num_resources = len(self.resources)
        self.max_steps = max_steps
        self.verbose = verbose
        self.seed = seed
        if self.seed:
            np.random.seed(self.seed)

        # agent specification
        if agents:
            self.set_agents(agents)
            self.n_agents = len(agents)
        else:
            self.agents = agents

        self.gridworld = GridWorld(self.gridworld_size[0], self.gridworld_size[1],
                                   self.resources,
                                   seed=self.seed
                                   )
        self.current_timestep = None
        self.episode = 0

        self.marketplace = Marketplace()

        # configure action space
        self.action_handler = ActionHandler()
        self.state_space = None
        self.cumulative_rewards = []

        # logger
        console_handler.setLevel(logging.CRITICAL)
        logger.addHandler(console_handler)

        # rendering the environment
        self.use_react = use_react
        if self.use_react:
            self.react_server = ReactServer()
            self.react_server.start()

            self.db_server = DatabaseServer()
            self.db_server.run()

        self.use_mongodb = use_mongodb
        if self.use_mongodb:
            self.mdb_client = MongoDBClient()

    def set_agents(self, agents) -> None:
        if not isinstance(agents, list):
            raise TypeError(
                "Pass a list of BaseAgents. If only one agent, pass a list of length one"
            )
        self.agents = agents
        self.n_agents = len(agents)

        self.state_space = (self.num_resources + self.n_agents) * (self.gridworld_size[0] * self.gridworld_size[1])

        names = {}
        used_colors = set()
        hex_colors = set(cnames.values())

        id = 1
        for idx, agent in enumerate(self.agents):
            agent.id = id
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

        self.cumulative_rewards = [0 for _ in self.agents]

        # reset grid
        self.gridworld.reset(self.agents)

        # reset and initialize map configuration
        if self.use_react:
            agent_locs = [agent.get_position() for agent in self.agents]

            agent_names = {i: agent.name for i, agent in enumerate(self.agents)}
            self.db_server.send(
                {
                    "agent_names": agent_names,
                    "gridworld_color_lookup": self.gridworld.hex_codes,
                    "gridworld_y": self.gridworld_size[1],
                    "gridworld_x": self.gridworld_size[0],
                    "gridworld": self.gridworld.get_resource_locations,
                    "agent_locations": agent_locs
                }
            )

        if self.use_mongodb:
            self.mdb_client.send_gridworld(self.gridworld)
            self.mdb_client.send_agents(self.agents)

        time.sleep(4)
        return self.get_state(), {}

    def calculate_rewards(self) -> list:
        agent_rewards = []
        for idx, agent in enumerate(self.agents):
            reward = agent.get_reward()

            # if self.gridworld.resource_ids[agent.x][agent.y] == 0:
            #   reward -= 5

            agent_rewards.append(reward)
            self.cumulative_rewards[idx] += reward

        return agent_rewards

    def get_state(self) -> np.ndarray:
        return 0
        return self.gridworld.get_one_hot_coding_map()

    def get_observation(self):
        raise NotImplementedError()

    def step(self, actions) -> [np.ndarray, list, list]:
        self.action_handler.process_actions(self.agents, actions, self.gridworld)
        for agent in self.agents:
            agent.step()

        # CODE THAT HAPPENS AFTER ALL EVENTS ARE PROCESSED
        dones = [self.current_timestep >= self.max_steps for _ in self.agents]
        rewards = self.calculate_rewards()
        self.gridworld.step()
        if self.use_react:
            self.render_step()

        if self.use_mongodb:
            self.mdb_client.send_gridworld(self.gridworld)
            self.mdb_client.send_agents(self.agents)
        self.current_timestep += 1

        return self.get_state(), rewards, dones

    def render_step(self) -> None:
        """
        function to do any calculations needed to render the environment, sends
        a dictionary to the the Flask server to POST
        """
        agent_locs = [agent.get_position() for agent in self.agents]

        agent_totals = []
        for i in range(self.current_timestep):
            agent_totals_dict = {}
            for agent in self.agents:
                agent_totals_dict[agent.name] = agent.xps[i]
            agent_totals.append(agent_totals_dict)

        self.db_server.send(
            {
                "agent_totals": agent_totals,
                "gridworld": self.gridworld.get_resource_locations,
                "agent_locations": agent_locs,
                "agent_data": [agent.inventory.history for agent in self.agents]
            }
        )

    def close(self):
        self.mdb_client.clear_all_databases()
        self.react_server.stop()
