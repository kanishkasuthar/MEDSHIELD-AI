"""Tests for FastAPI HTTP endpoint route handlers and contracts."""

import pytest
from fastapi import HTTPException
from medshield.api.app import (
    health_check,
    inject_scenario,
    reset_simulator,
    create_incident,
    list_incidents,
    get_incident,
    investigate_incident,
    submit_approval,
    get_incident_report,
    chat,
    create_invoice,
    get_invoice,
    approve_invoice,
    execute_payment,
    get_incident_audit,
    ScenarioInjectionRequest,
    container,
)
from medshield.simulator.scenarios import ScenarioType
from medshield.schemas.incident import IncidentRequest, IncidentSeverity, IncidentState
from medshield.schemas.actions import ApprovalDecision
from medshield.schemas.chatbot import ChatRequest, OperatorRole
from medshield.schemas.payment import (
    InvoiceRequest,
    PaymentApproval,
    PaymentExecutionRequest,
    PaymentStatus,
)


def test_api_health_check(db_session):
    data = health_check(db=db_session)
    assert data["status"] == "HEALTHY"
    assert data["database_connected"] is True
    assert data["agents"]["incident_commander"] == "ONLINE"
    assert data["agents"]["payment_agent"] == "ONLINE"
    assert data["simulator_active"] is True


def test_api_scenario_injection_and_reset():
    res = inject_scenario(ScenarioInjectionRequest(scenario_type=ScenarioType.EHR_APP_OUTAGE))
    assert res["status"] == "SCENARIO_INJECTED"
    assert res["target_service"] == "ehr-core-api"

    res_reset = reset_simulator()
    assert res_reset["status"] == "RESET_SUCCESS"


def test_api_full_incident_lifecycle(db_session):
    # 1. Inject failure
    inject_scenario(ScenarioInjectionRequest(scenario_type=ScenarioType.AUTH_SERVICE_FAILURE))

    # 2. Create Incident via API
    inc_req = IncidentRequest(
        incident_id="INC-API-001",
        correlation_id="CORR-API-001",
        service_id="auth-sso-service",
        title="SSO Certificate Expired",
        description="401 errors on logins",
        severity=IncidentSeverity.CRITICAL,
    )
    status_created = create_incident(inc_req, db=db_session)
    assert status_created.current_state == IncidentState.INCIDENT_DETECTED

    # 3. Investigate
    status_inv = investigate_incident("INC-API-001", db=db_session)
    assert status_inv.current_state == IncidentState.AWAITING_APPROVAL
    assert status_inv.proposed_action == "ROTATE_AUTH_KEYS"

    # 4. Get Incident
    status_get = get_incident("INC-API-001", db=db_session)
    assert status_get.incident_id == "INC-API-001"

    # 5. Chatbot query via API
    chat_resp = chat(
        ChatRequest(
            request_id="CHAT-API-01",
            operator_id="IT_LEAD",
            operator_role=OperatorRole.IT_OPERATOR,
            query="What recovery action is proposed for INC-API-001?",
        ),
        db=db_session,
    )
    assert "ROTATE_AUTH_KEYS" in chat_resp.answer

    # 6. Submit Approval Decision
    app_req = container.commander.get_approval_request("INC-API-001")
    decision = ApprovalDecision(
        approval_id=app_req.approval_id,
        incident_id="INC-API-001",
        approved=True,
        operator_id="SEC_CHIEF",
        operator_notes="Key rotation authorized",
        approval_token=app_req.approval_token,
    )
    status_app = submit_approval("INC-API-001", decision, db=db_session)
    assert status_app.current_state == IncidentState.RECOVERED

    # 7. Incident Report
    report = get_incident_report("INC-API-001", db=db_session)
    assert report["final_state"] == "RECOVERED"
    assert report["verification"]["verified_recovered"] is True

    # 8. Audit History
    audit_data = get_incident_audit("INC-API-001", db=db_session)
    assert audit_data["chain_tamper_verified"] is True
    assert audit_data["event_count"] >= 5


def test_api_payment_workflow(db_session):
    # 1. Create Invoice
    inv_payload = {
        "vendor_name": "Identity Systems Support LLC",
        "service_description": "Emergency SSO Certificate Provisioning",
        "amount": 2500.0,
        "currency": "USD",
        "invoice_reference": "INV-API-KEY-01",
    }
    inv = create_invoice(InvoiceRequest(**inv_payload), db=db_session)
    assert inv.status == PaymentStatus.PENDING

    # 2. Get Invoice
    inv_fetched = get_invoice(inv.invoice_id, db=db_session)
    assert inv_fetched.invoice_id == inv.invoice_id

    # 3. Approve Invoice
    approval = PaymentApproval(
        approval_id="APP-API-01",
        invoice_id=inv.invoice_id,
        approved=True,
        approver_id="FINANCE_MGR",
        approver_role="FINANCE",
        notes="Approved",
    )
    inv_approved = approve_invoice(inv.invoice_id, approval, db=db_session)
    assert inv_approved.status == PaymentStatus.APPROVED

    # 4. Execute Payment
    exec_req = PaymentExecutionRequest(
        invoice_id=inv.invoice_id,
        approval=approval,
        idempotency_key="idemp-api-pay-unique-001",
    )
    pay_res = execute_payment(exec_req, simulation_mode="SUCCESS", db=db_session)
    assert pay_res.status == PaymentStatus.SUCCEEDED
    assert pay_res.sandbox is True


def test_api_error_handling(db_session):
    # 404 on nonexistent incident
    with pytest.raises(HTTPException) as exc_info:
        get_incident("INC-NONEXISTENT", db=db_session)
    assert exc_info.value.status_code == 404

    # 404 on nonexistent invoice
    with pytest.raises(HTTPException) as exc_info_inv:
        get_invoice("INV-NONEXISTENT", db=db_session)
    assert exc_info_inv.value.status_code == 404
