"""Payment Agent schemas and sandbox records."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    REJECTED = "REJECTED"


class InvoiceRequest(BaseModel):
    vendor_name: str
    service_description: str
    amount: float = Field(gt=0.0, description="Amount must be positive")
    currency: str = "USD"
    invoice_reference: str


class InvoiceRecord(BaseModel):
    invoice_id: str
    invoice_reference: str
    vendor_name: str
    service_description: str
    amount: float
    currency: str
    status: PaymentStatus = PaymentStatus.PENDING
    sandbox_mode: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    approved_by: Optional[str] = None
    approval_timestamp: Optional[datetime] = None


class PaymentApproval(BaseModel):
    approval_id: str
    invoice_id: str
    approved: bool
    approver_id: str
    approver_role: str
    notes: Optional[str] = None
    signed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PaymentExecutionRequest(BaseModel):
    invoice_id: str
    approval: PaymentApproval
    idempotency_key: str
    sandbox_mode: bool = True

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, v: str) -> str:
        if not v or len(v.strip()) < 8:
            raise ValueError("idempotency_key must be at least 8 characters long")
        return v


class PaymentResult(BaseModel):
    transaction_id: str
    invoice_id: str
    invoice_reference: str
    status: PaymentStatus
    amount: float
    currency: str
    idempotency_key: str
    sandbox: bool = True
    processed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reconciliation_notes: str
    error_message: Optional[str] = None
