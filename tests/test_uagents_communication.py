"""Unit tests for Fetch.ai uAgents communication models and agent setup."""

import pytest
from uagents import Agent, Model


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


def test_uagents_model_serialization():
    alert = HospitalIncidentAlert(
        incident_id="INC-EHR-503",
        service_id="ehr-core-api",
        severity="CRITICAL",
        description="Bedside eMAR connection dropped",
    )
    # Verify uagents Model JSON serialization
    serialized = alert.model_dump_json()
    assert "INC-EHR-503" in serialized
    assert "ehr-core-api" in serialized

    # Verify deserialization
    reloaded = HospitalIncidentAlert.model_validate_json(serialized)
    assert reloaded.incident_id == alert.incident_id
    assert reloaded.severity == "CRITICAL"


def test_uagents_ack_model_serialization():
    ack = HospitalIncidentAck(
        incident_id="INC-EHR-503",
        commander_status="AWAITING_OPERATOR_APPROVAL",
        assigned_action="RESTART_SERVICE",
        message="Incident verified",
    )
    serialized = ack.model_dump_json()
    reloaded = HospitalIncidentAck.model_validate_json(serialized)
    assert reloaded.assigned_action == "RESTART_SERVICE"
    assert reloaded.commander_status == "AWAITING_OPERATOR_APPROVAL"
