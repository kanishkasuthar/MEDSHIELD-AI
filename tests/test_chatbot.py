"""Tests for Agent 6 (Hospital Operations Chatbot)."""

import pytest
from medshield.simulator import SyntheticHospitalSimulator, ScenarioType
from medshield.agents.evidence_analyst import EvidenceAnalystAgent
from medshield.agents.clinical_continuity import ClinicalContinuityAnalystAgent
from medshield.agents.response_coordinator import ResponseCoordinatorAgent
from medshield.agents.recovery_verifier import RecoveryVerifierAgent
from medshield.agents.incident_commander import IncidentCommanderAgent
from medshield.agents.chatbot import HospitalOperationsChatbot
from medshield.schemas.chatbot import ChatRequest, OperatorRole
from medshield.schemas.incident import IncidentRequest, IncidentSeverity
from medshield.schemas.actions import ApprovalDecision


@pytest.fixture
def test_setup(db_session):
    sim = SyntheticHospitalSimulator()
    ev = EvidenceAnalystAgent(sim)
    clin = ClinicalContinuityAnalystAgent()
    coord = ResponseCoordinatorAgent(sim, db_session)
    verif = RecoveryVerifierAgent(sim)
    cmd = IncidentCommanderAgent(sim, ev, clin, coord, verif, db_session)
    bot = HospitalOperationsChatbot(cmd)
    return sim, cmd, bot


def test_chatbot_unauthorized_guest_denied(test_setup):
    _, _, bot = test_setup
    req = ChatRequest(
        request_id="REQ-AUTH-01",
        operator_id="guest_user",
        operator_role=OperatorRole.UNAUTHORIZED_GUEST,
        query="What incidents are active?",
    )
    resp = bot.handle_chat(req)
    assert resp.authorized is False
    assert "Access Denied" in resp.answer


def test_chatbot_active_incidents_listing(test_setup):
    sim, cmd, bot = test_setup
    sim.inject_scenario(ScenarioType.EHR_APP_OUTAGE)

    cmd.start_incident(
        IncidentRequest(
            incident_id="INC-CHAT-01",
            correlation_id="CORR-CHAT-01",
            service_id="ehr-core-api",
            title="EHR Down",
            description="503 errors",
            severity=IncidentSeverity.CRITICAL,
        )
    )

    req = ChatRequest(
        request_id="REQ-LIST-01",
        operator_id="clinician_01",
        operator_role=OperatorRole.CLINICAL_COORDINATOR,
        query="What incidents are currently active in the hospital?",
    )
    resp = bot.handle_chat(req)
    assert resp.authorized is True
    assert "INC-CHAT-01" in resp.answer
    assert "ehr-core-api" in resp.answer


def test_chatbot_missing_incident_id_prompt(test_setup):
    _, _, bot = test_setup
    req = ChatRequest(
        request_id="REQ-MISS-01",
        operator_id="it_admin",
        operator_role=OperatorRole.IT_OPERATOR,
        query="What evidence supports the likely cause?",
        active_incident_id=None,
    )
    resp = bot.handle_chat(req)
    assert resp.missing_info_needed == "incident_id"
    assert "Please specify the Incident ID" in resp.answer


def test_chatbot_unknown_incident_id(test_setup):
    _, _, bot = test_setup
    req = ChatRequest(
        request_id="REQ-UNK-01",
        operator_id="it_admin",
        operator_role=OperatorRole.IT_OPERATOR,
        query="What happened to incident INC-GHOST-999?",
    )
    resp = bot.handle_chat(req)
    assert "was not found" in resp.answer


def test_chatbot_comprehensive_questions(test_setup):
    sim, cmd, bot = test_setup
    sim.inject_scenario(ScenarioType.EHR_APP_OUTAGE)

    inc_id = "INC-FULL-01"
    cmd.start_incident(
        IncidentRequest(
            incident_id=inc_id,
            correlation_id="CORR-FULL-01",
            service_id="ehr-core-api",
            title="EHR Outage",
            description="Outage",
            severity=IncidentSeverity.CRITICAL,
        )
    )
    cmd.investigate(inc_id)

    # 1. Ask about evidence
    req_ev = ChatRequest(
        request_id="REQ-EV-01",
        operator_id="it_admin",
        query=f"What evidence supports the likely cause for {inc_id}?",
    )
    resp_ev = bot.handle_chat(req_ev)
    assert "memory" in resp_ev.answer.lower() or "crash" in resp_ev.answer.lower()
    assert "Distinction" in resp_ev.answer

    # 2. Ask about clinical impact & workflows
    req_clin = ChatRequest(
        request_id="REQ-CLIN-01",
        operator_id="charge_nurse",
        query=f"Which simulated clinical workflows are affected by {inc_id}?",
    )
    resp_clin = bot.handle_chat(req_clin)
    assert "ED" in resp_clin.answer or "Emergency" in resp_clin.answer
    assert "DP-MAR-01" in resp_clin.answer

    # 3. Ask about proposed action & approval pending
    req_act = ChatRequest(
        request_id="REQ-ACT-01",
        operator_id="it_admin",
        query=f"What recovery action is proposed for {inc_id}?",
    )
    resp_act = bot.handle_chat(req_act)
    assert "RESTART_SERVICE" in resp_act.answer
    assert "Human Authorization Pending" in resp_act.answer
    assert "YES" in resp_act.answer

    # Approve and complete
    app_req = cmd.get_approval_request(inc_id)
    cmd.process_approval(
        inc_id,
        ApprovalDecision(
            approval_id=app_req.approval_id,
            incident_id=inc_id,
            approved=True,
            operator_id="CIO",
            operator_notes="Approved",
            approval_token=app_req.approval_token,
        ),
    )

    # 4. Ask if recovery actually succeeded
    req_rec = ChatRequest(
        request_id="REQ-REC-01",
        operator_id="it_admin",
        query=f"Did recovery actually succeed for {inc_id}?",
    )
    resp_rec = bot.handle_chat(req_rec)
    assert "Verified Recovered" in resp_rec.answer
    assert "YES" in resp_rec.answer
    assert "RECOVERED" in resp_rec.answer

    # 5. Ask about audit history
    req_aud = ChatRequest(
        request_id="REQ-AUD-01",
        operator_id="auditor_01",
        query=f"Show me the audit history and timeline for {inc_id}",
    )
    resp_aud = bot.handle_chat(req_aud)
    assert "Audit & Transition History" in resp_aud.answer
    assert "INCIDENT_DETECTED" in resp_aud.answer
    assert "RECOVERED" in resp_aud.answer
