"""MEDSHIELD AI — Combined uAgents Local Communication Runner.

Runs both MedShield Commander and Monitor uAgents simultaneously using uAgents Bureau.
Demonstrates autonomous multi-agent message passing in a single unified process.
"""

import sys
from pathlib import Path

_src_path = str(Path(__file__).resolve().parent.parent / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

from uagents import Agent, Context, Model, Bureau


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


# Initialize Commander
commander = Agent(
    name="medshield_commander",
    seed="medshield commander secret recovery phrase 2026",
)

# Initialize Monitor
monitor = Agent(
    name="medshield_monitor",
    seed="medshield monitor secret recovery phrase 2026",
)

print("=" * 75)
print(" MEDSHIELD AI — Fetch.ai uAgents Autonomous Local Communication")
print("=" * 75)
print(f"Commander Agent Address: {commander.address}")
print(f"Monitor Agent Address:   {monitor.address}")
print("=" * 75)


@commander.on_message(model=HospitalIncidentAlert)
async def handle_alert(ctx: Context, sender: str, msg: HospitalIncidentAlert):
    ctx.logger.info(f"[Commander] Received alert from {sender[:16]}...: [{msg.severity}] on {msg.service_id}")
    reply = HospitalIncidentAck(
        incident_id=msg.incident_id,
        commander_status="AWAITING_OPERATOR_APPROVAL",
        assigned_action="RESTART_SERVICE",
        message=f"Incident {msg.incident_id} verified. Dispatched recovery coordination.",
    )
    await ctx.send(sender, reply)
    ctx.logger.info(f"[Commander] Dispatched acknowledgement back to Monitor")


@monitor.on_interval(period=3.0)
async def send_alert(ctx: Context):
    alert = HospitalIncidentAlert(
        incident_id="INC-EHR-503",
        service_id="ehr-core-api",
        severity="CRITICAL",
        description="Bedside eMAR workstation connection dropped (503 Service Unavailable)",
    )
    ctx.logger.info(f"[Monitor] Emitting periodic telemetry alert for {alert.service_id} to Commander...")
    await ctx.send(commander.address, alert)


@monitor.on_message(model=HospitalIncidentAck)
async def handle_ack(ctx: Context, sender: str, msg: HospitalIncidentAck):
    ctx.logger.info(f"[Monitor] Received Commander response: [{msg.commander_status}] {msg.message}")


if __name__ == "__main__":
    bureau = Bureau(port=8005)
    bureau.add(commander)
    bureau.add(monitor)
    print("Starting Bureau event loop on port 8005 (Press CTRL+C to stop)...")
    bureau.run()
