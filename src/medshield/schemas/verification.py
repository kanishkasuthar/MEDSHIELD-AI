"""Recovery Verifier schemas."""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class ProbeStatus(str, Enum):
    HEALTHY = "HEALTHY"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"
    UNVERIFIED = "UNVERIFIED"
    TIMEOUT = "TIMEOUT"


class SingleHealthProbeResult(BaseModel):
    probe_index: int
    service_id: str
    endpoint_or_component: str
    status: ProbeStatus
    latency_ms: float
    details: str
    probed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VerificationRequest(BaseModel):
    incident_id: str
    correlation_id: str
    target_service: str
    required_consecutive_successes: int = 3
    interval_seconds: float = 0.5


class VerificationResult(BaseModel):
    incident_id: str
    target_service: str
    verified_recovered: bool
    consecutive_success_count: int
    probes_conducted: List[SingleHealthProbeResult] = Field(default_factory=list)
    overall_status: str  # RECOVERED, FAILED_VERIFICATION, UNVERIFIED, TIMEOUT, ESCALATED
    summary: str
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
