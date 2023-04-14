import time
from src.env.default_environments import SimpleEnvironment
from src.agents.simple.GatheringAgent import GatheringAgent
from src.agents.complex.PPOAgent.agent import PPOAgent
import plotly.graph_objs as go
import numpy as np

if __name__ == '__main__':
    timesteps = 1000

    Env = SimpleEnvironment()
    Env.max_timesteps = 1000

    action_space = Env.action_space
    state_space = Env.state_space

    ppo_agent = PPOAgent(use_pretrained=True)
    test_agent = GatheringAgent()
    agents = [test_agent, ppo_agent]

    Env.set_agents(agents)
    ppo_agent.init_model()

    sleep_time = 0.1
    avg_period = 50
    graph_episode = 50
    render_episode = 100
    update_episode = 150
    total_rewards_ppo = []
    total_rewards_gathering = []
    ppo_avg = []
    gathering_avg = []
    sum_avg = []
    for episode in range(100000):
        state, info = Env.reset()

        for i in range(timesteps):
            actions = [agent.select_action(state) for agent in agents]
            state, rewards, dones = Env.step(actions)
            ppo_agent.ppo_agent.buffer.rewards.append(rewards[1])
            ppo_agent.ppo_agent.buffer.is_terminals.append(dones[1])

            if dones[0]:
                break

        cum_reward = Env.cumulative_rewards
        total_rewards_ppo.append(cum_reward[1])
        total_rewards_gathering.append(cum_reward[0])
        ppo_avg.append(np.mean(total_rewards_ppo[-avg_period:]))
        gathering_avg.append(np.mean(total_rewards_gathering[-avg_period:]))
        sum_avg.append(ppo_avg[-1] + gathering_avg[-1])

        if episode % update_episode == 0:
            ppo_agent.ppo_agent.update()
            ppo_agent.ppo_agent.save(
                "C:\\Users\\aaron\\PycharmProjects\\gridworld-economy\\src\\agents\complex\\PPOAgent\\GatheringPPO_final.pth"
            )

        if episode % graph_episode == 0:
            go.Figure(
                data=[
                    go.Scatter(
                        y=ppo_avg
                    ),
                    go.Scatter(
                        y=gathering_avg
                    ),
                    go.Scatter(
                        y=sum_avg
                    )
                ]
            ).show()

        print(episode, cum_reward, gathering_avg[-1], ppo_avg[-1])
