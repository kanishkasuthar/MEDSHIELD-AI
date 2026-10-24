"""MEDSHIELD AI — Fetch.ai uAgent Commander (Local & Remote Communication).

Implements the official Fetch.ai communication pattern provided in the evaluator guide:
- Runs as an autonomous uAgent on port 8001.
- Listens for HospitalIncidentAlert messages from peer agents.
- Logs incoming alerts and replies back with HospitalIncidentAck.
"""

import sys
from pathlib import Path

_src_path = str(Path(__file__).resolve().parent.parent / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

from uagents import Agent, Context, Model


# 1. Define Message Models conforming to uagents.Model
class HospitalIncidentAlert(Model):
    incident_id: str
    service_id: str
    severity: str
    description: str


class HospitalIncidentAck(Model):
    incident_id: str
    commander_status: str
    assigned_action: str
    message: str


# 2. Create the Commander uAgent
# Unique seed derives deterministic address: agent1q...
commander = Agent(
    name="medshield_commander",
    seed="medshield commander secret recovery phrase 2026",
    port=8001,
    endpoint=["http://127.0.0.1:8001/submit"],
)


# 3. Handle Incoming Messages & Reply back to Sender
@commander.on_message(model=HospitalIncidentAlert)
async def handle_incident_alert(ctx: Context, sender: str, msg: HospitalIncidentAlert):
    ctx.logger.info(f"Received alert from {sender}: [{msg.severity}] {msg.service_id} — {msg.description}")
    
    # Reply back to the sender with acknowledgement and assigned action
    reply = HospitalIncidentAck(
        incident_id=msg.incident_id,
        commander_status="AWAITING_OPERATOR_APPROVAL",
        assigned_action="RESTART_SERVICE",
        message=f"Incident {msg.incident_id} logged by Commander. Dispatched Evidence and Clinical analysts.",
    )
    await ctx.send(sender, reply)
    ctx.logger.info(f"Dispatched confirmation reply to {sender}")


if __name__ == "__main__":
    print(f"Starting MedShield Commander uAgent on address: {commander.address}")
    commander.run()
