"""MEDSHIELD AI — Fetch.ai uAgent Monitor (Local & Remote Communication).

Implements the official Fetch.ai communication pattern provided in the evaluator guide:
- Runs as an autonomous uAgent on port 8002.
- Periodically sends HospitalIncidentAlert messages to the Commander agent on_interval.
- Receives and logs HospitalIncidentAck messages from the Commander.
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


# 2. Target Address of the MedShield Commander Agent
COMMANDER_ADDRESS = "agent1q0xal425zg53pectlsd2daw40jdsnxx92y7gxn4kss4jnmkrfgc95kl0ywt"


# 3. Create the Monitor uAgent
monitor = Agent(
    name="medshield_monitor",
    seed="medshield monitor secret recovery phrase 2026",
    port=8002,
    endpoint=["http://127.0.0.1:8002/submit"],
)


# 4. Periodically send incident telemetry alerts to Commander
@monitor.on_interval(period=3.0)
async def send_telemetry_alert(ctx: Context):
    alert = HospitalIncidentAlert(
        incident_id="INC-EHR-503",
        service_id="ehr-core-api",
        severity="CRITICAL",
        description="Bedside eMAR workstation connection dropped (503 Service Unavailable)",
    )
    ctx.logger.info(f"Sending incident alert to Commander ({COMMANDER_ADDRESS[:16]}...): {alert.service_id}")
    await ctx.send(COMMANDER_ADDRESS, alert)


# 5. Handle Acknowledgements from Commander
@monitor.on_message(model=HospitalIncidentAck)
async def handle_commander_ack(ctx: Context, sender: str, msg: HospitalIncidentAck):
    ctx.logger.info(f"Received confirmation from Commander ({sender[:16]}...): [{msg.commander_status}] {msg.message}")


if __name__ == "__main__":
    print(f"Starting MedShield Monitor uAgent on address: {monitor.address}")
    print(f"Targeting Commander address: {COMMANDER_ADDRESS}")
    monitor.run()
