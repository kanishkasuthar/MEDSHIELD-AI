"""Runner for the Fetch.ai ACP Incident Commander & Chatbot Agent."""

import sys
from medshield.api.app import container
from medshield.protocols.acp_adapter import create_asi_one_uagent
from medshield.config import settings

if __name__ == "__main__":
    print("=" * 70)
    print("MEDSHIELD AI — Fetch.ai Agent Chat Protocol (ACP) & ASI:One Gateway")
    print("=" * 70)
    print(f"Agent Name:    medshield_commander")
    print(f"Seed Config:   {settings.agent_seed_commander[:12]}...")
    print(f"Port:          {settings.agent_port_commander}")
    print(f"Mailbox Key:   {'Configured' if settings.agent_mailbox_key else 'None (Local Loopback / Direct Endpoint)'}")
    print(f"Agentverse:    {'API key provided' if settings.agentverse_api_key else 'Not configured (Local Almanac)'}")
    print("Initializing uAgent with AgentChatProtocol v0.3.0...")

    agent = create_asi_one_uagent(
        adapter=container.acp_adapter,
        name="medshield_commander",
        seed=settings.agent_seed_commander,
        port=settings.agent_port_commander,
    )

    print(f"Agent Address: {agent.address}")
    print("Starting agent runtime loop...")
    agent.run()
