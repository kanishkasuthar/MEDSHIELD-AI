"""Tests for Agent 4 (Response Coordinator) and Agent 5 (Recovery Verifier)."""

from datetime import datetime, timedelta, timezone
import pytest
from medshield.simulator import SyntheticHospitalSimulator, ScenarioType
from medshield.agents.response_coordinator import ResponseCoordinatorAgent
from medshield.agents.recovery_verifier import RecoveryVerifierAgent
from medshield.schemas.actions import (
    AllowedRecoveryAction,
    ApprovalDecision,
    ActionExecutionRequest,
    ExecutionStatus,
)
from medshield.schemas.verification import VerificationRequest, ProbeStatus
from medshield.db.models import DBActionExecution


@pytest.fixture
def simulator():
    return SyntheticHospitalSimulator()


@pytest.fixture
def response_coordinator(simulator, db_session):
    return ResponseCoordinatorAgent(simulator=simulator, db_session=db_session)


@pytest.fixture
def recovery_verifier(simulator):
    return RecoveryVerifierAgent(simulator=simulator)


def test_response_coordinator_valid_approval_execution(simulator, response_coordinator):
    simulator.inject_scenario(ScenarioType.EHR_APP_OUTAGE)
    incident_id = "INC-RESP-01"

    # Step 1: Create approval request
    app_req = response_coordinator.create_approval_request(
        incident_id=incident_id,
        correlation_id="CORR-RESP-01",
        proposed_action=AllowedRecoveryAction.RESTART_SERVICE,
        target_service="ehr-core-api",
        justification="Worker threads crashed under memory pressure",
        clinical_impact_summary="ED and ICU eMAR systems disrupted",
    )
    assert app_req.approval_token is not None

    # Step 2: Operator grants explicit approval
    decision = ApprovalDecision(
        approval_id=app_req.approval_id,
        incident_id=incident_id,
        approved=True,
        operator_id="CHIEF_MED_INFO_OFFICER",
        operator_notes="Approved restart during low census interval",
        approval_token=app_req.approval_token,
    )

    # Step 3: Execute action
    exec_req = ActionExecutionRequest(
        execution_id="EXEC-001",
        incident_id=incident_id,
        correlation_id="CORR-RESP-01",
        action=AllowedRecoveryAction.RESTART_SERVICE,
        target_service="ehr-core-api",
        approval_id=app_req.approval_id,
        approval_decision=decision,
        idempotency_key="idemp-key-unique-001",
    )
    result = response_coordinator.execute_action(exec_req, approval_request=app_req)

    assert result.status == ExecutionStatus.SUCCESS
    assert "successfully executed" in result.simulator_output
    assert simulator.probe_health("ehr-core-api").status == ProbeStatus.HEALTHY


def test_response_coordinator_rejected_approval(simulator, response_coordinator):
    simulator.inject_scenario(ScenarioType.DB_CONNECTION_FAILURE)
    incident_id = "INC-REJECT-01"

    app_req = response_coordinator.create_approval_request(
        incident_id=incident_id,
        correlation_id="CORR-REJECT-01",
        proposed_action=AllowedRecoveryAction.FLUSH_CONNECTION_POOL,
        target_service="clinical-database",
        justification="Connection pool exhausted",
        clinical_impact_summary="High impact on CPOE",
    )

    # Operator explicitly denies authorization
    rejection = ApprovalDecision(
        approval_id=app_req.approval_id,
        incident_id=incident_id,
        approved=False,
        operator_id="DBA_LEAD",
        operator_notes="Hold action pending manual lock inspection",
        approval_token=app_req.approval_token,
    )

    exec_req = ActionExecutionRequest(
        execution_id="EXEC-002",
        incident_id=incident_id,
        correlation_id="CORR-REJECT-01",
        action=AllowedRecoveryAction.FLUSH_CONNECTION_POOL,
        target_service="clinical-database",
        approval_id=app_req.approval_id,
        approval_decision=rejection,
        idempotency_key="idemp-key-unique-002",
    )
    result = response_coordinator.execute_action(exec_req, approval_request=app_req)

    assert result.status == ExecutionStatus.REJECTED
    assert "Execution blocked" in result.error_message
    # Service must remain degraded
    assert simulator.probe_health("clinical-database").status == ProbeStatus.UNHEALTHY


def test_response_coordinator_expired_token(simulator, response_coordinator):
    incident_id = "INC-EXP-01"

    # Create approval with already-expired duration
    app_req = response_coordinator.create_approval_request(
        incident_id=incident_id,
        correlation_id="CORR-EXP-01",
        proposed_action=AllowedRecoveryAction.RESTART_SERVICE,
        target_service="ehr-core-api",
        justification="Restart test",
        clinical_impact_summary="Test",
        expiry_seconds=-10,  # Expired in past
    )

    decision = ApprovalDecision(
        approval_id=app_req.approval_id,
        incident_id=incident_id,
        approved=True,
        operator_id="ADMIN",
        operator_notes="Belated approval",
        approval_token=app_req.approval_token,
    )

    exec_req = ActionExecutionRequest(
        execution_id="EXEC-003",
        incident_id=incident_id,
        correlation_id="CORR-EXP-01",
        action=AllowedRecoveryAction.RESTART_SERVICE,
        target_service="ehr-core-api",
        approval_id=app_req.approval_id,
        approval_decision=decision,
        idempotency_key="idemp-key-unique-003",
    )
    result = response_coordinator.execute_action(exec_req, approval_request=app_req)

    assert result.status == ExecutionStatus.EXPIRED
    assert "expired" in result.error_message.lower()


def test_response_coordinator_replay_protection(simulator, response_coordinator):
    simulator.inject_scenario(ScenarioType.AUTH_SERVICE_FAILURE)
    incident_id = "INC-REPLAY-01"

    app_req = response_coordinator.create_approval_request(
        incident_id=incident_id,
        correlation_id="CORR-REPLAY-01",
        proposed_action=AllowedRecoveryAction.ROTATE_AUTH_KEYS,
        target_service="auth-sso-service",
        justification="SSO cert expired",
        clinical_impact_summary="Clinicians cannot log in",
    )

    decision = ApprovalDecision(
        approval_id=app_req.approval_id,
        incident_id=incident_id,
        approved=True,
        operator_id="SECURITY_OFFICER",
        operator_notes="Rotate certs immediately",
        approval_token=app_req.approval_token,
    )

    exec_req = ActionExecutionRequest(
        execution_id="EXEC-004",
        incident_id=incident_id,
        correlation_id="CORR-REPLAY-01",
        action=AllowedRecoveryAction.ROTATE_AUTH_KEYS,
        target_service="auth-sso-service",
        approval_id=app_req.approval_id,
        approval_decision=decision,
        idempotency_key="idemp-key-shared-replay",
    )

    # First attempt: succeeds
    res1 = response_coordinator.execute_action(exec_req, approval_request=app_req)
    assert res1.status == ExecutionStatus.SUCCESS

    # Second attempt with same idempotency key: must be blocked as replay
    res2 = response_coordinator.execute_action(exec_req, approval_request=app_req)
    assert res2.status == ExecutionStatus.REPLAY_DETECTED
    assert "already used" in res2.error_message.lower() or "already in db" in res2.error_message.lower()


def test_recovery_verifier_three_consecutive_successes(simulator, recovery_verifier):
    # Base state is healthy
    req = VerificationRequest(
        incident_id="INC-VERIF-01",
        correlation_id="CORR-VERIF-01",
        target_service="ehr-core-api",
        required_consecutive_successes=3,
    )
    result = recovery_verifier.verify_recovery(req, max_probe_cycles=5)

    assert result.verified_recovered is True
    assert result.overall_status == "RECOVERED"
    assert result.consecutive_success_count == 3
    assert len(result.probes_conducted) == 3


def test_recovery_verifier_resets_on_probe_failure(simulator, recovery_verifier):
    # Service is broken
    simulator.inject_scenario(ScenarioType.EHR_APP_OUTAGE)

    req = VerificationRequest(
        incident_id="INC-VERIF-02",
        correlation_id="CORR-VERIF-02",
        target_service="ehr-core-api",
        required_consecutive_successes=3,
    )
    result = recovery_verifier.verify_recovery(req, max_probe_cycles=4)

    assert result.verified_recovered is False
    assert result.overall_status == "FAILED_VERIFICATION"
    assert result.consecutive_success_count == 0


def test_recovery_verifier_unknown_service_reports_unverified(simulator, recovery_verifier):
    req = VerificationRequest(
        incident_id="INC-VERIF-03",
        correlation_id="CORR-VERIF-03",
        target_service="ghost-service-not-in-system",
        required_consecutive_successes=3,
    )
    result = recovery_verifier.verify_recovery(req, max_probe_cycles=3)

    assert result.verified_recovered is False
    assert result.overall_status == "UNVERIFIED"
    assert result.consecutive_success_count == 0
