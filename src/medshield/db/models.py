"""Database models for persistent incident state, audit logging, and payment tracking."""

from datetime import datetime, timezone
import json
from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    DateTime,
    Text,
    Index,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class DBIncident(Base):
    __tablename__ = "incidents"

    incident_id = Column(String(64), primary_key=True, index=True)
    correlation_id = Column(String(64), index=True, nullable=False)
    service_id = Column(String(64), index=True, nullable=False)
    current_state = Column(String(32), nullable=False)
    previous_state = Column(String(32), nullable=True)
    severity = Column(String(16), nullable=False)
    title = Column(String(256), nullable=False)
    description = Column(Text, nullable=False)
    proposed_action = Column(String(64), nullable=True)
    approval_status = Column(String(32), nullable=True)
    escalation_reason = Column(Text, nullable=True)
    state_history_json = Column(Text, default="[]", nullable=False)
    evidence_report_json = Column(Text, nullable=True)
    continuity_report_json = Column(Text, nullable=True)
    execution_result_json = Column(Text, nullable=True)
    verification_result_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class DBAuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(64), unique=True, index=True, nullable=False)
    correlation_id = Column(String(64), index=True, nullable=False)
    incident_id = Column(String(64), index=True, nullable=True)
    actor = Column(String(64), nullable=False)
    event_type = Column(String(64), index=True, nullable=False)
    payload_json = Column(Text, default="{}", nullable=False)
    previous_state = Column(String(32), nullable=True)
    new_state = Column(String(32), nullable=True)
    hash_prev = Column(String(64), nullable=False)
    hash_current = Column(String(64), nullable=False)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index("ix_audit_incident_time", "incident_id", "timestamp"),
    )


class DBInvoice(Base):
    __tablename__ = "invoices"

    invoice_id = Column(String(64), primary_key=True, index=True)
    invoice_reference = Column(String(64), unique=True, index=True, nullable=False)
    vendor_name = Column(String(128), nullable=False)
    service_description = Column(String(256), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(8), default="USD", nullable=False)
    status = Column(String(32), default="PENDING", nullable=False)
    sandbox_mode = Column(Boolean, default=True, nullable=False)
    approved_by = Column(String(64), nullable=True)
    approval_timestamp = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class DBPaymentTransaction(Base):
    __tablename__ = "payment_transactions"

    transaction_id = Column(String(64), primary_key=True, index=True)
    invoice_id = Column(String(64), index=True, nullable=False)
    idempotency_key = Column(String(128), unique=True, index=True, nullable=False)
    status = Column(String(32), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(8), nullable=False)
    sandbox = Column(Boolean, default=True, nullable=False)
    reconciliation_notes = Column(Text, nullable=False)
    error_message = Column(Text, nullable=True)
    processed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class DBActionExecution(Base):
    __tablename__ = "action_executions"

    execution_id = Column(String(64), primary_key=True, index=True)
    incident_id = Column(String(64), index=True, nullable=False)
    action = Column(String(64), nullable=False)
    target_service = Column(String(64), nullable=False)
    idempotency_key = Column(String(128), unique=True, index=True, nullable=False)
    status = Column(String(32), nullable=False)
    simulator_output = Column(Text, nullable=False)
    error_message = Column(Text, nullable=True)
    executed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
