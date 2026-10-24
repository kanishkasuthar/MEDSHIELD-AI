"""Response Coordinator and Human Authorization schemas."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class AllowedRecoveryAction(str, Enum):
    RESTART_SERVICE = "RESTART_SERVICE"
    FAILOVER_DATABASE = "FAILOVER_DATABASE"
    FLUSH_CONNECTION_POOL = "FLUSH_CONNECTION_POOL"
    ROTATE_AUTH_KEYS = "ROTATE_AUTH_KEYS"
    ISOLATE_AND_RESTORE_HOST = "ISOLATE_AND_RESTORE_HOST"
    RESYNC_TELEMETRY_STREAM = "RESYNC_TELEMETRY_STREAM"


class ExecutionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    REPLAY_DETECTED = "REPLAY_DETECTED"
    INVALID_TOKEN = "INVALID_TOKEN"


class ApprovalRequest(BaseModel):
    approval_id: str
    incident_id: str
    correlation_id: str
    proposed_action: AllowedRecoveryAction
    target_service: str
    action_parameters: Dict[str, Any] = Field(default_factory=dict)
    justification: str
    clinical_impact_summary: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    approval_token: str = Field(description="HMAC signature over incident_id, action, target_service, expires_at")


class ApprovalDecision(BaseModel):
    approval_id: str
    incident_id: str
    approved: bool
    operator_id: str
    operator_notes: str
    approval_token: str
    decided_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ActionExecutionRequest(BaseModel):
    execution_id: str
    incident_id: str
    correlation_id: str
    action: AllowedRecoveryAction
    target_service: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    approval_id: str
    approval_decision: ApprovalDecision
    idempotency_key: str


class ActionExecutionResult(BaseModel):
    execution_id: str
    incident_id: str
    action: AllowedRecoveryAction
    target_service: str
    status: ExecutionStatus
    execution_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    simulator_output: str
    error_message: Optional[str] = None
