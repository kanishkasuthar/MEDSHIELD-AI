"""Fetch.ai Agent Chat Protocol (ACP) adapter and ASI:One discovery integration.

Maps incoming Fetch.ai ACP ChatMessage payloads to MEDSHIELD AI ChatRequests,
dispatches to the HospitalOperationsChatbot and IncidentCommander,
and formats responses conforming to the canonical AgentChatProtocol v0.3.0.
"""

from datetime import datetime, timezone
import uuid
from typing import Optional, Tuple
from uagents import Agent, Context, Model, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatMessage,
    ChatAcknowledgement,
    TextContent,
    chat_protocol_spec,
)
from medshield.config import settings
from medshield.schemas.chatbot import ChatRequest, ChatResponse, OperatorRole
from medshield.agents.chatbot import HospitalOperationsChatbot
from medshield.agents.incident_commander import IncidentCommanderAgent


class ACPMessageAdapter:
    """Translates between Fetch.ai ACP envelopes and internal MEDSHIELD contracts."""

    def __init__(self, chatbot: HospitalOperationsChatbot, commander: IncidentCommanderAgent):
        self.chatbot = chatbot
        self.commander = commander

    def process_inbound_chat_message(
        self,
        sender_address: str,
        chat_msg: ChatMessage,
        operator_role: OperatorRole = OperatorRole.IT_OPERATOR,
    ) -> Tuple[ChatAcknowledgement, ChatMessage]:
        """Process inbound ACP ChatMessage, produce immediate ACK and reply ChatMessage."""
        # 1. Produce immediate acknowledgement
        ack = ChatAcknowledgement(
            timestamp=datetime.now(timezone.utc),
            acknowledged_msg_id=chat_msg.msg_id,
        )

        # 2. Extract text payload
        extracted_text = ""
        for item in chat_msg.content:
            if isinstance(item, TextContent):
                extracted_text += item.text + " "

        query = extracted_text.strip()
        if not query:
            query = "help"

        # 3. Create internal ChatRequest
        request = ChatRequest(
            request_id=f"ACP-{uuid.uuid4().hex[:8]}",
            operator_id=sender_address,
            operator_role=operator_role,
            query=query,
            timestamp=datetime.now(timezone.utc),
        )

        # 4. Invoke chatbot logic
        response: ChatResponse = self.chatbot.handle_chat(request)

        # 5. Package reply in ACP ChatMessage
        reply_content = f"{response.answer}\n\n*[Data Source: {', '.join(response.data_sources)} | {response.distinction}]*"
        reply_msg = ChatMessage(
            timestamp=datetime.now(timezone.utc),
            msg_id=uuid.uuid4(),
            content=[TextContent(type="text", text=reply_content)],
        )

        return ack, reply_msg


def create_asi_one_uagent(
    adapter: ACPMessageAdapter,
    name: str = "medshield_commander",
    seed: Optional[str] = None,
    port: Optional[int] = None,
) -> Agent:
    """Build a Fetch.ai uAgent with Almanac discovery and ACP chat protocol handler."""
    agent_seed = seed or settings.agent_seed_commander
    agent_port = port or settings.agent_port_commander

    agent = Agent(
        name=name,
        seed=agent_seed,
        port=agent_port,
        mailbox=f"{settings.agent_mailbox_key}@https://agentverse.ai" if settings.agent_mailbox_key else None,
    )

    chat_proto = Protocol(name="AgentChatProtocol", version="0.3.0")

    @chat_proto.on_message(model=ChatMessage, replies={ChatAcknowledgement, ChatMessage})
    async def handle_acp_message(ctx: Context, sender: str, msg: ChatMessage):
        ctx.logger.info(f"[ACP Inbound] From: {sender} | MsgId: {msg.msg_id}")
        ack, reply = adapter.process_inbound_chat_message(sender_address=sender, chat_msg=msg)
        await ctx.send(sender, ack)
        await ctx.send(sender, reply)
        ctx.logger.info(f"[ACP Outbound] Sent reply to {sender}")

    agent.include(chat_proto, publish_manifest=True)
    return agent
