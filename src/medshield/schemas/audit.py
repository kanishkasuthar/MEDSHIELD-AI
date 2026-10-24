"""Audit, health, and error schemas."""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class AuditEvent(BaseModel):
    event_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str
    incident_id: Optional[str] = None
    actor: str
    event_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    previous_state: Optional[str] = None
    new_state: Optional[str] = None
    hash_prev: Optional[str] = None
    hash_current: Optional[str] = None

    def calculate_hash(self, prev_hash: Optional[str]) -> str:
        ts = self.timestamp if self.timestamp.tzinfo else self.timestamp.replace(tzinfo=timezone.utc)
        ts_str = ts.astimezone(timezone.utc).isoformat()
        data = {
            "event_id": self.event_id,
            "timestamp": ts_str,
            "correlation_id": self.correlation_id,
            "incident_id": self.incident_id,
            "actor": self.actor,
            "event_type": self.event_type,
            "payload": self.payload,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "hash_prev": prev_hash or "GENESIS",
        }
        serialized = json.dumps(data, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class AgentHealth(BaseModel):
    agent_id: str
    agent_name: str
    status: str  # HEALTHY, DEGRADED, UNREACHABLE
    last_heartbeat: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    active_tasks: int = 0
    details: Optional[str] = None


class AgentError(BaseModel):
    error_id: str
    agent_id: str
    correlation_id: str
    error_type: str
    message: str
    recoverable: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
