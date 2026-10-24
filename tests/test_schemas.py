"""Unit and contract tests for schemas, state machine, and security."""

from datetime import datetime, timedelta, timezone
import pytest
from medshield.schemas import (
    IncidentRequest,
    IncidentStatus,
    IncidentState,
    IncidentSeverity,
    AllowedRecoveryAction,
    ApprovalRequest,
    ApprovalDecision,
    ActionExecutionRequest,
    ExecutionStatus,
    AuditEvent,
    InvoiceRequest,
    PaymentApproval,
    PaymentExecutionRequest,
    PaymentStatus,
)
from medshield.security import generate_approval_token, verify_approval_token
from medshield.db.session import AuditLogger


def test_incident_request_validation():
    req = IncidentRequest(
        incident_id="INC-20261024-001",
        correlation_id="CORR-123",
        service_id="ehr-core-api",
        title="EHR Core API Outage",
        description="Synthetic EHR core service is returning HTTP 503",
        severity=IncidentSeverity.CRITICAL,
    )
    assert req.incident_id == "INC-20261024-001"
    assert req.severity == IncidentSeverity.CRITICAL

    # Test serialization to JSON and back
    data = req.model_dump()
    reloaded = IncidentRequest.model_validate(data)
    assert reloaded.incident_id == req.incident_id


def test_incident_state_machine_valid_transitions():
    status = IncidentStatus(
        incident_id="INC-001",
        correlation_id="CORR-001",
        service_id="ehr-core-api",
        current_state=IncidentState.NORMAL_MONITORING,
    )

    # NORMAL_MONITORING -> INCIDENT_DETECTED
    status.transition_to(IncidentState.INCIDENT_DETECTED, "Telemetry threshold breached", "Detector")
    assert status.current_state == IncidentState.INCIDENT_DETECTED
    assert status.previous_state == IncidentState.NORMAL_MONITORING

    # INCIDENT_DETECTED -> INVESTIGATING
    status.transition_to(IncidentState.INVESTIGATING, "Dispatched Evidence Analyst", "IncidentCommander")
    assert status.current_state == IncidentState.INVESTIGATING

    # INVESTIGATING -> AWAITING_APPROVAL
    status.transition_to(IncidentState.AWAITING_APPROVAL, "Recovery plan proposed", "ResponseCoordinator")
    assert status.current_state == IncidentState.AWAITING_APPROVAL

    # AWAITING_APPROVAL -> RECOVERY_IN_PROGRESS
    status.transition_to(IncidentState.RECOVERY_IN_PROGRESS, "Operator approved restart", "IncidentCommander")
    assert status.current_state == IncidentState.RECOVERY_IN_PROGRESS

    # RECOVERY_IN_PROGRESS -> VERIFYING
    status.transition_to(IncidentState.VERIFYING, "Action executed", "ResponseCoordinator")
    assert status.current_state == IncidentState.VERIFYING

    # VERIFYING -> RECOVERED
    status.transition_to(IncidentState.RECOVERED, "3 consecutive probes succeeded", "RecoveryVerifier")
    assert status.current_state == IncidentState.RECOVERED
    assert len(status.state_history) == 6


def test_incident_state_machine_invalid_transitions():
    status = IncidentStatus(
        incident_id="INC-002",
        correlation_id="CORR-002",
        service_id="clinical-database",
        current_state=IncidentState.NORMAL_MONITORING,
    )

    # Cannot jump directly from NORMAL_MONITORING to RECOVERED or RECOVERY_IN_PROGRESS
    with pytest.raises(ValueError, match="Invalid incident state transition"):
        status.transition_to(IncidentState.RECOVERED, "Direct leap illegal", "Attacker")

    with pytest.raises(ValueError, match="Invalid incident state transition"):
        status.transition_to(IncidentState.RECOVERY_IN_PROGRESS, "Bypassing approval illegal", "Attacker")


def test_hmac_approval_token_security():
    incident_id = "INC-100"
    action = AllowedRecoveryAction.RESTART_SERVICE.value
    target = "ehr-core-api"
    now = datetime.now(timezone.utc)
    future_exp = now + timedelta(minutes=5)
    past_exp = now - timedelta(minutes=1)

    # Valid token
    valid_token = generate_approval_token(incident_id, action, target, future_exp)
    ok, msg = verify_approval_token(valid_token, incident_id, action, target, future_exp)
    assert ok is True
    assert msg == "Token valid"

    # Expired token
    expired_token = generate_approval_token(incident_id, action, target, past_exp)
    ok, msg = verify_approval_token(expired_token, incident_id, action, target, past_exp)
    assert ok is False
    assert "expired" in msg

    # Tampered incident or action
    ok, msg = verify_approval_token(valid_token, "INC-DIFFERENT", action, target, future_exp)
    assert ok is False
    assert "Invalid approval token signature" in msg

    ok, msg = verify_approval_token(valid_token, incident_id, AllowedRecoveryAction.FAILOVER_DATABASE.value, target, future_exp)
    assert ok is False


def test_audit_hash_chain_tamper_detection(db_session):
    # Log 3 events
    ev1 = AuditEvent(
        event_id="EVT-001",
        correlation_id="CORR-1",
        incident_id="INC-001",
        actor="Commander",
        event_type="INCIDENT_DETECTED",
        payload={"reason": "CPU overload"},
    )
    AuditLogger.record_event(db_session, ev1)

    ev2 = AuditEvent(
        event_id="EVT-002",
        correlation_id="CORR-1",
        incident_id="INC-001",
        actor="EvidenceAnalyst",
        event_type="EVIDENCE_COLLECTED",
        payload={"root_cause": "Memory leak"},
    )
    AuditLogger.record_event(db_session, ev2)

    # Chain should be valid
    assert AuditLogger.verify_audit_chain(db_session) is True

    # Tamper with event 1 payload in the database
    from medshield.db.models import DBAuditEvent
    db_ev1 = db_session.query(DBAuditEvent).filter(DBAuditEvent.event_id == "EVT-001").first()
    db_ev1.payload_json = '{"reason": "TAMPERED_RECORD"}'
    db_session.commit()

    # Chain verification must now detect tampering and return False
    assert AuditLogger.verify_audit_chain(db_session) is False


def test_payment_idempotency_validation():
    # Idempotency key too short raises validation error
    with pytest.raises(ValueError, match="idempotency_key must be at least 8 characters long"):
        PaymentExecutionRequest(
            invoice_id="INV-001",
            approval=PaymentApproval(
                approval_id="APP-001",
                invoice_id="INV-001",
                approved=True,
                approver_id="CHIEF_INFO_OFFICER",
                approver_role="CIO",
            ),
            idempotency_key="short",
        )
