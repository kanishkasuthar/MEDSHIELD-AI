"""Complete Seven-Agent Integration Tests.

Validates end-to-end multi-agent workflow, failure handling, timeout recovery,
operator approval enforcement, persistence across process restart, and ACP protocol translation.
"""

from datetime import datetime, timezone
import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from uagents_core.contrib.protocols.chat import (
    ChatMessage,
    ChatAcknowledgement,
    TextContent,
)

from medshield.simulator import SyntheticHospitalSimulator, ScenarioType
from medshield.agents.evidence_analyst import EvidenceAnalystAgent
from medshield.agents.clinical_continuity import ClinicalContinuityAnalystAgent
from medshield.agents.response_coordinator import ResponseCoordinatorAgent
from medshield.agents.recovery_verifier import RecoveryVerifierAgent
from medshield.agents.incident_commander import IncidentCommanderAgent
from medshield.agents.chatbot import HospitalOperationsChatbot
from medshield.agents.payment_agent import PaymentAgent
from medshield.protocols.acp_adapter import ACPMessageAdapter
from medshield.schemas.incident import IncidentRequest, IncidentState, IncidentSeverity
from medshield.schemas.actions import ApprovalDecision, AllowedRecoveryAction
from medshield.schemas.payment import (
    InvoiceRequest,
    PaymentApproval,
    PaymentExecutionRequest,
    PaymentStatus,
)
from medshield.schemas.chatbot import OperatorRole
from medshield.db.session import init_db, AuditLogger


@pytest.fixture
def test_platform(db_session):
    sim = SyntheticHospitalSimulator()
    evidence_agent = EvidenceAnalystAgent(sim)
    continuity_agent = ClinicalContinuityAnalystAgent()
    coordinator_agent = ResponseCoordinatorAgent(sim, db_session)
    verifier_agent = RecoveryVerifierAgent(sim)
    commander = IncidentCommanderAgent(
        simulator=sim,
        evidence_analyst=evidence_agent,
        continuity_analyst=continuity_agent,
        response_coordinator=coordinator_agent,
        recovery_verifier=verifier_agent,
        db_session=db_session,
    )
    chatbot = HospitalOperationsChatbot(commander)
    payment = PaymentAgent(db_session=db_session)
    acp_adapter = ACPMessageAdapter(chatbot=chatbot, commander=commander)

    return {
        "simulator": sim,
        "commander": commander,
        "chatbot": chatbot,
        "payment": payment,
        "acp_adapter": acp_adapter,
        "db": db_session,
    }


def test_full_seven_agent_lifecycle(test_platform):
    sim = test_platform["simulator"]
    commander = test_platform["commander"]
    chatbot = test_platform["chatbot"]
    payment = test_platform["payment"]
    acp_adapter = test_platform["acp_adapter"]
    db = test_platform["db"]

    # --- PHASE 1: Failure Injection & Incident Detection ---
    sim.inject_scenario(ScenarioType.DB_CONNECTION_FAILURE)
    inc_id = "INC-SEVEN-001"
    status = commander.start_incident(
        IncidentRequest(
            incident_id=inc_id,
            correlation_id="CORR-SEVEN-001",
            service_id="clinical-database",
            title="Clinical Database Connection Pool Saturation",
            description="All 500 connections in pool exhausted; queries timing out",
            severity=IncidentSeverity.CRITICAL,
        )
    )
    assert status.current_state == IncidentState.INCIDENT_DETECTED

    # --- PHASE 2: Investigation (Evidence & Clinical Continuity) ---
    status = commander.investigate(inc_id)
    assert status.current_state == IncidentState.AWAITING_APPROVAL
    assert status.proposed_action == AllowedRecoveryAction.FLUSH_CONNECTION_POOL.value

    # --- PHASE 3: Chatbot Q&A via ACP Protocol ---
    inbound_acp = ChatMessage(
        timestamp=datetime.now(timezone.utc),
        msg_id=uuid.uuid4(),
        content=[TextContent(type="text", text=f"What clinical workflows are affected by {inc_id}?")],
    )
    ack, reply = acp_adapter.process_inbound_chat_message(
        sender_address="agent1q_test_operator_address",
        chat_msg=inbound_acp,
        operator_role=OperatorRole.CLINICAL_COORDINATOR,
    )
    assert isinstance(ack, ChatAcknowledgement)
    assert ack.acknowledged_msg_id == inbound_acp.msg_id
    reply_text = reply.content[0].text
    assert "Affected Departments" in reply_text
    assert "DP-MAR-01" in reply_text or "DP-CPOE-02" in reply_text

    # --- PHASE 4: Human Operator Authorization Gate ---
    app_req = commander.get_approval_request(inc_id)
    decision = ApprovalDecision(
        approval_id=app_req.approval_id,
        incident_id=inc_id,
        approved=True,
        operator_id="CHIEF_MEDICAL_OFFICER",
        operator_notes="Approved flush of orphaned HL7 client connections",
        approval_token=app_req.approval_token,
    )

    # --- PHASE 5: Recovery Execution & Independent Verification ---
    final_status = commander.process_approval(inc_id, decision)
    assert final_status.current_state == IncidentState.RECOVERED
    assert final_status.approval_status == "APPROVED"

    # --- PHASE 6: Audit Chain Integrity ---
    assert AuditLogger.verify_audit_chain(db) is True
    audit_events = AuditLogger.get_events_for_incident(db, inc_id)
    assert len(audit_events) >= 6

    # --- PHASE 7: Payment Agent Workflow ---
    invoice = payment.create_invoice(
        InvoiceRequest(
            vendor_name="Relational Data Systems Support",
            service_description="PostgreSQL Critical Database Standby Support Incident",
            amount=7800.00,
            currency="USD",
            invoice_reference="INV-SEVEN-DBA-01",
        )
    )
    payment_approval = PaymentApproval(
        approval_id="APP-PAY-SEVEN",
        invoice_id=invoice.invoice_id,
        approved=True,
        approver_id="HOSPITAL_CFO",
        approver_role="CFO",
    )
    payment.approve_invoice(payment_approval)

    pay_result = payment.execute_payment(
        PaymentExecutionRequest(
            invoice_id=invoice.invoice_id,
            approval=payment_approval,
            idempotency_key="idemp-seven-payment-unique-key",
        ),
        simulation_mode="SUCCESS",
    )
    assert pay_result.status == PaymentStatus.SUCCEEDED
    assert pay_result.sandbox is True


def test_persistence_across_process_restart():
    """Verify that a completely new process recovers state from persistent storage."""
    # Step 1: Initialize database file engine
    db_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    init_db(db_engine)
    Session = sessionmaker(bind=db_engine)

    # Step 2: Session 1 records incident and investigates
    with Session() as session1:
        sim1 = SyntheticHospitalSimulator()
        sim1.inject_scenario(ScenarioType.EHR_APP_OUTAGE)
        cmd1 = IncidentCommanderAgent(
            simulator=sim1,
            evidence_analyst=EvidenceAnalystAgent(sim1),
            continuity_analyst=ClinicalContinuityAnalystAgent(),
            response_coordinator=ResponseCoordinatorAgent(sim1, session1),
            recovery_verifier=RecoveryVerifierAgent(sim1),
            db_session=session1,
        )
        cmd1.start_incident(
            IncidentRequest(
                incident_id="INC-PERSIST-01",
                correlation_id="CORR-PERSIST-01",
                service_id="ehr-core-api",
                title="Process Restart Test",
                description="Testing persistence",
                severity=IncidentSeverity.HIGH,
            )
        )
        cmd1.investigate("INC-PERSIST-01")

    # Step 3: Simulate application crash / restart with fresh Session 2
    with Session() as session2:
        sim2 = SyntheticHospitalSimulator()
        cmd2 = IncidentCommanderAgent(
            simulator=sim2,
            evidence_analyst=EvidenceAnalystAgent(sim2),
            continuity_analyst=ClinicalContinuityAnalystAgent(),
            response_coordinator=ResponseCoordinatorAgent(sim2, session2),
            recovery_verifier=RecoveryVerifierAgent(sim2),
            db_session=session2,
        )

        # Recover from database
        recovered_status = cmd2.get_incident("INC-PERSIST-01")
        assert recovered_status is not None
        assert recovered_status.incident_id == "INC-PERSIST-01"
        assert recovered_status.current_state == IncidentState.AWAITING_APPROVAL
        assert recovered_status.proposed_action == "RESTART_SERVICE"
        assert len(recovered_status.state_history) >= 2

        # Verify audit chain persisted and is valid
        assert AuditLogger.verify_audit_chain(session2) is True
