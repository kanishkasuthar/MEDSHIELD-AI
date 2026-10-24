"""Incident schemas and state machine definitions."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentState(str, Enum):
    NORMAL_MONITORING = "NORMAL_MONITORING"
    INCIDENT_DETECTED = "INCIDENT_DETECTED"
    INVESTIGATING = "INVESTIGATING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    RECOVERY_IN_PROGRESS = "RECOVERY_IN_PROGRESS"
    VERIFYING = "VERIFYING"
    RECOVERED = "RECOVERED"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"


# Valid state machine transitions
ALLOWED_TRANSITIONS: Dict[IncidentState, List[IncidentState]] = {
    IncidentState.NORMAL_MONITORING: [IncidentState.INCIDENT_DETECTED],
    IncidentState.INCIDENT_DETECTED: [IncidentState.INVESTIGATING, IncidentState.ESCALATED, IncidentState.FAILED],
    IncidentState.INVESTIGATING: [IncidentState.AWAITING_APPROVAL, IncidentState.ESCALATED, IncidentState.FAILED],
    IncidentState.AWAITING_APPROVAL: [
        IncidentState.RECOVERY_IN_PROGRESS,
        IncidentState.ESCALATED,
        IncidentState.FAILED,
        IncidentState.NORMAL_MONITORING,  # in case dismissed
    ],
    IncidentState.RECOVERY_IN_PROGRESS: [IncidentState.VERIFYING, IncidentState.FAILED, IncidentState.ESCALATED],
    IncidentState.VERIFYING: [IncidentState.RECOVERED, IncidentState.FAILED, IncidentState.ESCALATED],
    IncidentState.RECOVERED: [IncidentState.NORMAL_MONITORING],
    IncidentState.ESCALATED: [IncidentState.AWAITING_APPROVAL, IncidentState.FAILED, IncidentState.RECOVERED],
    IncidentState.FAILED: [IncidentState.INVESTIGATING, IncidentState.ESCALATED, IncidentState.NORMAL_MONITORING],
}


class StateTransitionEvent(BaseModel):
    from_state: IncidentState
    to_state: IncidentState
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reason: str
    actor: str


class IncidentRequest(BaseModel):
    incident_id: str = Field(description="Unique incident identifier, e.g. INC-20261024-001")
    correlation_id: str = Field(description="Correlation ID for distributed tracing across all agents")
    service_id: str = Field(description="Synthetic service ID affected, e.g. ehr-core-api")
    title: str
    description: str
    severity: IncidentSeverity = IncidentSeverity.HIGH
    reported_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)


class IncidentStatus(BaseModel):
    incident_id: str
    correlation_id: str
    service_id: str
    current_state: IncidentState = IncidentState.INCIDENT_DETECTED
    previous_state: Optional[IncidentState] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    state_history: List[StateTransitionEvent] = Field(default_factory=list)
    proposed_action: Optional[str] = None
    approval_status: Optional[str] = None
    escalation_reason: Optional[str] = None

    def transition_to(self, new_state: IncidentState, reason: str, actor: str) -> None:
        valid_next = ALLOWED_TRANSITIONS.get(self.current_state, [])
        if new_state not in valid_next:
            raise ValueError(
                f"Invalid incident state transition: cannot move from {self.current_state} to {new_state}. "
                f"Allowed transitions: {[s.value for s in valid_next]}"
            )
        event = StateTransitionEvent(
            from_state=self.current_state,
            to_state=new_state,
            reason=reason,
            actor=actor,
        )
        self.previous_state = self.current_state
        self.current_state = new_state
        self.updated_at = datetime.now(timezone.utc)
        self.state_history.append(event)
