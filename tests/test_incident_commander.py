"""Tests for Agent 1 (Incident Commander) orchestrating the 5 core agents."""

import pytest
from medshield.simulator import SyntheticHospitalSimulator, ScenarioType
from medshield.agents.evidence_analyst import EvidenceAnalystAgent
from medshield.agents.clinical_continuity import ClinicalContinuityAnalystAgent
from medshield.agents.response_coordinator import ResponseCoordinatorAgent
from medshield.agents.recovery_verifier import RecoveryVerifierAgent
from medshield.agents.incident_commander import IncidentCommanderAgent
from medshield.schemas.incident import (
    IncidentRequest,
    IncidentState,
    IncidentSeverity,
)
from medshield.schemas.actions import ApprovalDecision
from medshield.db.session import AuditLogger


@pytest.fixture
def simulator():
    return SyntheticHospitalSimulator()


@pytest.fixture
def commander(simulator, db_session):
    evidence_agent = EvidenceAnalystAgent(simulator)
    continuity_agent = ClinicalContinuityAnalystAgent()
    coordinator_agent = ResponseCoordinatorAgent(simulator, db_session)
    verifier_agent = RecoveryVerifierAgent(simulator)

    cmd = IncidentCommanderAgent(
        simulator=simulator,
        evidence_analyst=evidence_agent,
        continuity_analyst=continuity_agent,
        response_coordinator=coordinator_agent,
        recovery_verifier=verifier_agent,
        db_session=db_session,
    )
    return cmd


def test_commander_e2e_successful_recovery(simulator, commander, db_session):
    # 1. Inject simulated EHR outage
    simulator.inject_scenario(ScenarioType.EHR_APP_OUTAGE)

    # 2. Start Incident
    req = IncidentRequest(
        incident_id="INC-E2E-001",
        correlation_id="CORR-E2E-001",
        service_id="ehr-core-api",
        title="Critical EHR Web Worker Outage",
        description="EHR cluster returning 503 errors under memory spike",
        severity=IncidentSeverity.CRITICAL,
    )
    status = commander.start_incident(req)
    assert status.current_state == IncidentState.INCIDENT_DETECTED

    # 3. Investigate
    status = commander.investigate("INC-E2E-001")
    assert status.current_state == IncidentState.AWAITING_APPROVAL
    assert status.proposed_action == "RESTART_SERVICE"
    assert status.approval_status == "PENDING_OPERATOR_DECISION"

    # Verify pending approval request exists
    app_req = commander.get_approval_request("INC-E2E-001")
    assert app_req is not None
    assert app_req.approval_token is not None

    # 4. Operator grants authorization
    decision = ApprovalDecision(
        approval_id=app_req.approval_id,
        incident_id="INC-E2E-001",
        approved=True,
        operator_id="DR_HOSPITAL_CIO",
        operator_notes="Restart approved for rapid clinical restoration",
        approval_token=app_req.approval_token,
    )
    final_status = commander.process_approval("INC-E2E-001", decision)

    # 5. Must reach RECOVERED
    assert final_status.current_state == IncidentState.RECOVERED

    # 6. Final report checks
    report = commander.generate_incident_report("INC-E2E-001")
    assert report["final_state"] == "RECOVERED"
    assert report["evidence_analysis"]["likely_root_cause"] != "N/A"
    assert len(report["clinical_continuity"]["departments_affected"]) > 0
    assert "DP-MAR-01" in " ".join(report["clinical_continuity"]["downtime_procedures"])
    assert report["recovery_execution"]["status"] == "SUCCESS"
    assert report["verification"]["verified_recovered"] is True

    # 7. Audit log verification
    assert AuditLogger.verify_audit_chain(db_session) is True
    audit_events = AuditLogger.get_events_for_incident(db_session, "INC-E2E-001")
    assert len(audit_events) >= 5


def test_commander_operator_rejection_escalation(simulator, commander, db_session):
    simulator.inject_scenario(ScenarioType.DB_CONNECTION_FAILURE)

    req = IncidentRequest(
        incident_id="INC-REJECT-002",
        correlation_id="CORR-REJECT-002",
        service_id="clinical-database",
        title="Clinical DB Connection Exhaustion",
        description="Pool full",
        severity=IncidentSeverity.HIGH,
    )
    commander.start_incident(req)
    commander.investigate("INC-REJECT-002")

    app_req = commander.get_approval_request("INC-REJECT-002")
    decision = ApprovalDecision(
        approval_id=app_req.approval_id,
        incident_id="INC-REJECT-002",
        approved=False,
        operator_id="SENIOR_DBA",
        operator_notes="Rejected: investigating hung long-running query manually",
        approval_token=app_req.approval_token,
    )
    final_status = commander.process_approval("INC-REJECT-002", decision)

    assert final_status.current_state == IncidentState.ESCALATED
    assert final_status.approval_status == "REJECTED"
    assert "investigating hung" in final_status.escalation_reason

    # Service must NOT have been recovered
    from medshield.schemas.verification import ProbeStatus
    assert simulator.probe_health("clinical-database").status == ProbeStatus.UNHEALTHY
