"""Tests for Agent 7 (Payment Agent)."""

from datetime import datetime, timezone
import pytest
from medshield.agents.payment_agent import PaymentAgent
from medshield.schemas.payment import (
    InvoiceRequest,
    PaymentApproval,
    PaymentExecutionRequest,
    PaymentStatus,
)
from medshield.db.session import AuditLogger


@pytest.fixture
def payment_agent(db_session):
    return PaymentAgent(db_session=db_session)


def test_payment_successful_flow(payment_agent, db_session):
    # 1. Create Invoice
    inv_req = InvoiceRequest(
        vendor_name="HealthGrid Telemetry Maintenance Corp",
        service_description="Emergency SLA Support & Telemetry Licensing Q4",
        amount=14500.00,
        currency="USD",
        invoice_reference="INV-REF-2026-9921",
    )
    invoice = payment_agent.create_invoice(inv_req)
    assert invoice.status == PaymentStatus.PENDING
    assert invoice.sandbox_mode is True

    # 2. Operator reviews and approves
    approval = PaymentApproval(
        approval_id="APP-PAY-001",
        invoice_id=invoice.invoice_id,
        approved=True,
        approver_id="HOSPITAL_FINANCIAL_CONTROLLER",
        approver_role="CONTROLLER",
        notes="Approved under IT Emergency Disaster Recovery budget",
    )
    approved_invoice = payment_agent.approve_invoice(approval)
    assert approved_invoice.status == PaymentStatus.APPROVED
    assert approved_invoice.approved_by == "HOSPITAL_FINANCIAL_CONTROLLER"

    # 3. Execute sandbox payment
    exec_req = PaymentExecutionRequest(
        invoice_id=invoice.invoice_id,
        approval=approval,
        idempotency_key="idemp-pay-success-001",
        sandbox_mode=True,
    )
    result = payment_agent.execute_payment(exec_req, simulation_mode="SUCCESS")

    assert result.status == PaymentStatus.SUCCEEDED
    assert result.sandbox is True
    assert result.amount == 14500.00
    assert "authorized and cleared" in result.reconciliation_notes

    # 4. Verify audit trail is unbroken
    assert AuditLogger.verify_audit_chain(db_session) is True


def test_payment_rejected_without_approval(payment_agent):
    inv_req = InvoiceRequest(
        vendor_name="Unapproved Vendor",
        service_description="Unsolicited IT Software",
        amount=5000.00,
        currency="USD",
        invoice_reference="INV-REF-UNAPPROVED-01",
    )
    invoice = payment_agent.create_invoice(inv_req)

    # Attempting to execute payment without approval
    fake_approval = PaymentApproval(
        approval_id="APP-FAKE-01",
        invoice_id=invoice.invoice_id,
        approved=True,
        approver_id="ATTACKER",
        approver_role="NONE",
    )
    exec_req = PaymentExecutionRequest(
        invoice_id=invoice.invoice_id,
        approval=fake_approval,
        idempotency_key="idemp-unapproved-attempt-01",
    )
    result = payment_agent.execute_payment(exec_req, simulation_mode="SUCCESS")

    assert result.status == PaymentStatus.REJECTED
    assert "not received valid operator approval" in result.reconciliation_notes


def test_payment_duplicate_idempotency_protection(payment_agent):
    inv_req = InvoiceRequest(
        vendor_name="Database Support Services LLC",
        service_description="PostgreSQL High Availability Failover Node",
        amount=3200.00,
        currency="USD",
        invoice_reference="INV-REF-IDEMP-01",
    )
    invoice = payment_agent.create_invoice(inv_req)

    approval = PaymentApproval(
        approval_id="APP-PAY-IDEMP",
        invoice_id=invoice.invoice_id,
        approved=True,
        approver_id="IT_DIRECTOR",
        approver_role="DIRECTOR",
    )
    payment_agent.approve_invoice(approval)

    idemp_key = "idemp-key-must-not-duplicate-12345"
    exec_req = PaymentExecutionRequest(
        invoice_id=invoice.invoice_id,
        approval=approval,
        idempotency_key=idemp_key,
    )

    # First call: executes
    res1 = payment_agent.execute_payment(exec_req, simulation_mode="SUCCESS")
    assert res1.status == PaymentStatus.SUCCEEDED

    # Second call with identical idempotency key: duplicate charge blocked
    res2 = payment_agent.execute_payment(exec_req, simulation_mode="SUCCESS")
    assert res2.transaction_id == res1.transaction_id
    assert "IDEMPOTENT_REPLAY" in res2.reconciliation_notes


def test_payment_timeout_records_unknown_never_assumes_success(payment_agent):
    inv_req = InvoiceRequest(
        vendor_name="Critical Care Gateway Inc",
        service_description="DICOM Network Hardware Lease",
        amount=8900.00,
        currency="USD",
        invoice_reference="INV-REF-TIMEOUT-01",
    )
    invoice = payment_agent.create_invoice(inv_req)

    approval = PaymentApproval(
        approval_id="APP-TIMEOUT-01",
        invoice_id=invoice.invoice_id,
        approved=True,
        approver_id="CHIEF_TECH_OFFICER",
        approver_role="CTO",
    )
    payment_agent.approve_invoice(approval)

    exec_req = PaymentExecutionRequest(
        invoice_id=invoice.invoice_id,
        approval=approval,
        idempotency_key="idemp-timeout-simulation-key",
    )

    # Simulate timeout
    result = payment_agent.execute_payment(exec_req, simulation_mode="TIMEOUT")

    # MUST record UNKNOWN, NEVER mock or report SUCCEEDED
    assert result.status == PaymentStatus.UNKNOWN
    assert "UNKNOWN" in result.error_message


def test_payment_reconciliation_workflow(payment_agent):
    inv_req = InvoiceRequest(
        vendor_name="Network Provider",
        service_description="Fiber Link Standby",
        amount=1200.00,
        currency="USD",
        invoice_reference="INV-REF-RECONCILE-01",
    )
    invoice = payment_agent.create_invoice(inv_req)
    approval = PaymentApproval(
        approval_id="APP-RECON",
        invoice_id=invoice.invoice_id,
        approved=True,
        approver_id="CFO",
        approver_role="CFO",
    )
    payment_agent.approve_invoice(approval)

    # Execute timeout -> UNKNOWN
    exec_req = PaymentExecutionRequest(
        invoice_id=invoice.invoice_id,
        approval=approval,
        idempotency_key="idemp-reconcile-target-01",
    )
    tx = payment_agent.execute_payment(exec_req, simulation_mode="TIMEOUT")
    assert tx.status == PaymentStatus.UNKNOWN

    # Reconcile via out-of-band audit verification
    reconciled_tx = payment_agent.reconcile_transaction(
        transaction_id=tx.transaction_id,
        verified_status=PaymentStatus.SUCCEEDED,
        audit_notes="Clearing verified via automated bank settlement file check.",
    )
    assert reconciled_tx.status == PaymentStatus.SUCCEEDED
    assert "RECONCILED" in reconciled_tx.reconciliation_notes


def test_payment_declined_scenario(payment_agent):
    inv_req = InvoiceRequest(
        vendor_name="Hardware Vendor",
        service_description="Emergency Rack Replacement",
        amount=19500.00,
        currency="USD",
        invoice_reference="INV-REF-DECLINE-01",
    )
    invoice = payment_agent.create_invoice(inv_req)
    approval = PaymentApproval(
        approval_id="APP-DEC",
        invoice_id=invoice.invoice_id,
        approved=True,
        approver_id="VP_OPS",
        approver_role="VP",
    )
    payment_agent.approve_invoice(approval)

    exec_req = PaymentExecutionRequest(
        invoice_id=invoice.invoice_id,
        approval=approval,
        idempotency_key="idemp-decline-target-01",
    )
    result = payment_agent.execute_payment(exec_req, simulation_mode="DECLINED")
    assert result.status == PaymentStatus.FAILED
    assert "decline" in result.error_message.lower()


def test_payment_amount_threshold_validation(payment_agent):
    # Zero or negative amount must be rejected
    with pytest.raises(ValueError, match="greater than 0"):
        InvoiceRequest(
            vendor_name="Bad Vendor",
            service_description="Invalid",
            amount=-100.0,
            currency="USD",
            invoice_reference="INV-BAD-01",
        )

    # Exceeding institutional limit ($25,000) must be rejected
    with pytest.raises(ValueError, match="exceeds institutional threshold"):
        payment_agent.create_invoice(
            InvoiceRequest(
                vendor_name="Super Expensive Vendor",
                service_description="Uncapped consulting",
                amount=99000.0,
                currency="USD",
                invoice_reference="INV-EXCEED-01",
            )
        )
