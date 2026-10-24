"""Agent 7 — Payment Agent.

Manages synthetic institutional service invoices and sandbox payment workflows.
Enforces strict idempotency, operator approval, institutional spend limits,
truthful state recording (PENDING, APPROVED, PROCESSING, SUCCEEDED, FAILED, UNKNOWN),
and sandbox labeling. Never represents a mock payment as a real transfer.
"""

from datetime import datetime, timezone
import uuid
from typing import Dict, Optional
from sqlalchemy.orm import Session
from medshield.config import settings
from medshield.db.models import DBInvoice, DBPaymentTransaction
from medshield.db.session import AuditLogger
from medshield.schemas.payment import (
    InvoiceRequest,
    InvoiceRecord,
    PaymentApproval,
    PaymentExecutionRequest,
    PaymentResult,
    PaymentStatus,
)
from medshield.schemas.audit import AuditEvent


class PaymentAgent:
    """Institutional IT maintenance invoice and sandbox payment agent."""

    def __init__(self, db_session: Optional[Session] = None):
        self.db = db_session
        self._invoices: Dict[str, InvoiceRecord] = {}
        self._transactions: Dict[str, PaymentResult] = {}
        self._idempotency_map: Dict[str, str] = {}  # idempotency_key -> transaction_id

    def set_db_session(self, db_session: Session) -> None:
        self.db = db_session

    def _audit(self, event_type: str, actor: str, payload: Dict) -> None:
        if self.db:
            event = AuditEvent(
                event_id=f"AUD-PAY-{uuid.uuid4().hex[:8]}",
                timestamp=datetime.now(timezone.utc),
                correlation_id=payload.get("correlation_id", "CORR-PAYMENT"),
                incident_id=payload.get("invoice_id"),
                actor=actor,
                event_type=event_type,
                payload=payload,
            )
            AuditLogger.record_event(self.db, event)

    def create_invoice(self, request: InvoiceRequest) -> InvoiceRecord:
        """Create a synthetic institutional service invoice for IT operations review."""
        if request.amount <= 0:
            raise ValueError(f"Invoice amount must be positive, got {request.amount}")

        if request.amount > settings.payment_max_institutional_limit:
            raise ValueError(
                f"Invoice amount ${request.amount:,.2f} exceeds institutional threshold "
                f"of ${settings.payment_max_institutional_limit:,.2f}"
            )

        invoice_id = f"INV-{uuid.uuid4().hex[:8]}"
        record = InvoiceRecord(
            invoice_id=invoice_id,
            invoice_reference=request.invoice_reference,
            vendor_name=request.vendor_name,
            service_description=request.service_description,
            amount=request.amount,
            currency=request.currency,
            status=PaymentStatus.PENDING,
            sandbox_mode=settings.payment_sandbox_mode,
            created_at=datetime.now(timezone.utc),
        )

        self._invoices[invoice_id] = record

        if self.db:
            db_inv = DBInvoice(
                invoice_id=invoice_id,
                invoice_reference=request.invoice_reference,
                vendor_name=request.vendor_name,
                service_description=request.service_description,
                amount=request.amount,
                currency=request.currency,
                status=record.status.value,
                sandbox_mode=record.sandbox_mode,
                created_at=record.created_at,
            )
            self.db.add(db_inv)
            self.db.commit()

        self._audit(
            event_type="INVOICE_CREATED",
            actor="PaymentAgent",
            payload=record.model_dump(mode="json"),
        )
        return record

    def get_invoice(self, invoice_id: str) -> Optional[InvoiceRecord]:
        if invoice_id in self._invoices:
            return self._invoices[invoice_id]
        if self.db:
            db_inv = self.db.query(DBInvoice).filter(DBInvoice.invoice_id == invoice_id).first()
            if db_inv:
                rec = InvoiceRecord(
                    invoice_id=db_inv.invoice_id,
                    invoice_reference=db_inv.invoice_reference,
                    vendor_name=db_inv.vendor_name,
                    service_description=db_inv.service_description,
                    amount=db_inv.amount,
                    currency=db_inv.currency,
                    status=PaymentStatus(db_inv.status),
                    sandbox_mode=db_inv.sandbox_mode,
                    created_at=db_inv.created_at,
                    approved_by=db_inv.approved_by,
                    approval_timestamp=db_inv.approval_timestamp,
                )
                self._invoices[invoice_id] = rec
                return rec
        return None

    def approve_invoice(self, approval: PaymentApproval) -> InvoiceRecord:
        """Record explicit operator approval or rejection for an invoice."""
        inv = self.get_invoice(approval.invoice_id)
        if not inv:
            raise KeyError(f"Invoice {approval.invoice_id} not found")

        if inv.status != PaymentStatus.PENDING:
            raise ValueError(f"Cannot approve invoice {approval.invoice_id} in status {inv.status.value}")

        if approval.approved:
            inv.status = PaymentStatus.APPROVED
            inv.approved_by = approval.approver_id
            inv.approval_timestamp = approval.signed_at
            event_type = "INVOICE_APPROVED"
        else:
            inv.status = PaymentStatus.REJECTED
            event_type = "INVOICE_REJECTED"

        if self.db:
            db_inv = self.db.query(DBInvoice).filter(DBInvoice.invoice_id == approval.invoice_id).first()
            if db_inv:
                db_inv.status = inv.status.value
                db_inv.approved_by = inv.approved_by
                db_inv.approval_timestamp = inv.approval_timestamp
                self.db.commit()

        self._audit(
            event_type=event_type,
            actor=approval.approver_id,
            payload={
                "invoice_id": approval.invoice_id,
                "approved": approval.approved,
                "notes": approval.notes,
            },
        )
        return inv

    def execute_payment(
        self,
        request: PaymentExecutionRequest,
        simulation_mode: str = "SUCCESS",
    ) -> PaymentResult:
        """Execute a sandbox payment workflow with strict idempotency and validation.

        Supported simulation modes:
        - "SUCCESS": Sandbox payment succeeds.
        - "DECLINED": Sandbox payment declined by issuer.
        - "TIMEOUT": Sandbox payment gateway times out (results in UNKNOWN).
        - "PROVIDER_ERROR": Sandbox payment provider reports upstream error.
        """
        # 1. Idempotency Check
        idemp_key = request.idempotency_key
        if idemp_key in self._idempotency_map:
            tx_id = self._idempotency_map[idemp_key]
            prev = self._transactions[tx_id]
            return PaymentResult(
                transaction_id=prev.transaction_id,
                invoice_id=prev.invoice_id,
                invoice_reference=prev.invoice_reference,
                status=prev.status,
                amount=prev.amount,
                currency=prev.currency,
                idempotency_key=idemp_key,
                sandbox=True,
                processed_at=prev.processed_at,
                reconciliation_notes="IDEMPOTENT_REPLAY: Cached transaction returned. Duplicate charge prevented.",
                error_message=prev.error_message,
            )

        if self.db:
            db_tx = (
                self.db.query(DBPaymentTransaction)
                .filter(DBPaymentTransaction.idempotency_key == idemp_key)
                .first()
            )
            if db_tx:
                self._idempotency_map[idemp_key] = db_tx.transaction_id
                res = PaymentResult(
                    transaction_id=db_tx.transaction_id,
                    invoice_id=db_tx.invoice_id,
                    invoice_reference="STORED_REF",
                    status=PaymentStatus(db_tx.status),
                    amount=db_tx.amount,
                    currency=db_tx.currency,
                    idempotency_key=idemp_key,
                    sandbox=db_tx.sandbox,
                    processed_at=db_tx.processed_at,
                    reconciliation_notes="IDEMPOTENT_REPLAY: Duplicate charge prevented via persistent database record.",
                    error_message=db_tx.error_message,
                )
                self._transactions[db_tx.transaction_id] = res
                return res

        # 2. Invoice Check
        inv = self.get_invoice(request.invoice_id)
        if not inv:
            raise KeyError(f"Invoice {request.invoice_id} not found")

        # 3. Authorization Check
        if inv.status != PaymentStatus.APPROVED:
            return PaymentResult(
                transaction_id=f"TX-REJECTED-{uuid.uuid4().hex[:6]}",
                invoice_id=inv.invoice_id,
                invoice_reference=inv.invoice_reference,
                status=PaymentStatus.REJECTED,
                amount=inv.amount,
                currency=inv.currency,
                idempotency_key=idemp_key,
                sandbox=True,
                processed_at=datetime.now(timezone.utc),
                reconciliation_notes="Payment rejected: Invoice has not received valid operator approval.",
                error_message=f"Invoice status is {inv.status.value}, expected APPROVED",
            )

        # 4. Sandbox Provider Execution
        tx_id = f"TX-SANDBOX-{uuid.uuid4().hex[:8]}"
        processed_at = datetime.now(timezone.utc)

        if simulation_mode == "SUCCESS":
            status = PaymentStatus.SUCCEEDED
            err = None
            notes = "Sandbox institutional payment authorized and cleared via simulated ACH adapter."
            inv.status = PaymentStatus.SUCCEEDED
        elif simulation_mode == "DECLINED":
            status = PaymentStatus.FAILED
            err = "Simulated bank decline: Institutional department credit ceiling exceeded."
            notes = "Sandbox payment declined."
            inv.status = PaymentStatus.FAILED
        elif simulation_mode == "TIMEOUT":
            # Crucial requirement: Never report success if provider times out!
            status = PaymentStatus.UNKNOWN
            err = "Simulated provider gateway timeout (HTTP 504). Transfer state is UNKNOWN pending reconciliation."
            notes = "Transaction in UNKNOWN state. Requires manual or automated reconciliation."
            inv.status = PaymentStatus.UNKNOWN
        else:
            status = PaymentStatus.FAILED
            err = f"Simulated provider error: {simulation_mode}"
            notes = "Sandbox payment error."
            inv.status = PaymentStatus.FAILED

        result = PaymentResult(
            transaction_id=tx_id,
            invoice_id=inv.invoice_id,
            invoice_reference=inv.invoice_reference,
            status=status,
            amount=inv.amount,
            currency=inv.currency,
            idempotency_key=idemp_key,
            sandbox=True,
            processed_at=processed_at,
            reconciliation_notes=notes,
            error_message=err,
        )

        # Cache in memory
        self._transactions[tx_id] = result
        self._idempotency_map[idemp_key] = tx_id

        # Persist to database
        if self.db:
            db_tx = DBPaymentTransaction(
                transaction_id=tx_id,
                invoice_id=inv.invoice_id,
                idempotency_key=idemp_key,
                status=status.value,
                amount=inv.amount,
                currency=inv.currency,
                sandbox=True,
                reconciliation_notes=notes,
                error_message=err,
                processed_at=processed_at,
            )
            self.db.add(db_tx)

            # Update DB invoice status
            db_inv = self.db.query(DBInvoice).filter(DBInvoice.invoice_id == inv.invoice_id).first()
            if db_inv:
                db_inv.status = inv.status.value

            self.db.commit()

        self._audit(
            event_type="PAYMENT_EXECUTED",
            actor="PaymentAgent",
            payload=result.model_dump(mode="json"),
        )
        return result

    def reconcile_transaction(self, transaction_id: str, verified_status: PaymentStatus, audit_notes: str) -> PaymentResult:
        """Reconcile an UNKNOWN payment transaction after querying sandbox provider logs."""
        tx = self._transactions.get(transaction_id)
        if not tx:
            if self.db:
                db_tx = self.db.query(DBPaymentTransaction).filter(DBPaymentTransaction.transaction_id == transaction_id).first()
                if db_tx:
                    tx = PaymentResult(
                        transaction_id=db_tx.transaction_id,
                        invoice_id=db_tx.invoice_id,
                        invoice_reference="STORED_REF",
                        status=PaymentStatus(db_tx.status),
                        amount=db_tx.amount,
                        currency=db_tx.currency,
                        idempotency_key=db_tx.idempotency_key,
                        sandbox=db_tx.sandbox,
                        processed_at=db_tx.processed_at,
                        reconciliation_notes=db_tx.reconciliation_notes,
                        error_message=db_tx.error_message,
                    )
                    self._transactions[transaction_id] = tx

        if not tx:
            raise KeyError(f"Transaction {transaction_id} not found")

        tx.status = verified_status
        tx.reconciliation_notes = f"RECONCILED: {audit_notes}"

        if self.db:
            db_tx = self.db.query(DBPaymentTransaction).filter(DBPaymentTransaction.transaction_id == transaction_id).first()
            if db_tx:
                db_tx.status = verified_status.value
                db_tx.reconciliation_notes = tx.reconciliation_notes
            db_inv = self.db.query(DBInvoice).filter(DBInvoice.invoice_id == tx.invoice_id).first()
            if db_inv:
                db_inv.status = verified_status.value
            self.db.commit()

        self._audit(
            event_type="PAYMENT_RECONCILED",
            actor="PaymentAgent",
            payload={
                "transaction_id": transaction_id,
                "verified_status": verified_status.value,
                "audit_notes": audit_notes,
            },
        )
        return tx
