"""Evidence Analyst schemas."""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class FactConfidence(str, Enum):
    OBSERVED_FACT = "OBSERVED_FACT"
    HIGH_CONFIDENCE_HYPOTHESIS = "HIGH_CONFIDENCE_HYPOTHESIS"
    MODERATE_HYPOTHESIS = "MODERATE_HYPOTHESIS"
    SPECULATIVE_HYPOTHESIS = "SPECULATIVE_HYPOTHESIS"


class LogEntryObservation(BaseModel):
    timestamp: datetime
    service: str
    level: str  # INFO, WARN, ERROR, CRITICAL
    message: str
    observed: bool = True  # strictly verified from synthetic log buffer; never fabricated


class TelemetryObservation(BaseModel):
    metric_name: str
    value: float
    unit: str
    status: str  # HEALTHY, DEGRADED, FAILED
    observed_at: datetime


class EvidenceRequest(BaseModel):
    incident_id: str
    correlation_id: str
    service_id: str
    time_window_minutes: int = 15


class EvidenceReport(BaseModel):
    report_id: str
    incident_id: str
    correlation_id: str
    service_id: str
    observed_facts: List[LogEntryObservation] = Field(default_factory=list)
    telemetry_facts: List[TelemetryObservation] = Field(default_factory=list)
    likely_root_cause: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    confidence_level: FactConfidence
    distinction_summary: str = Field(
        description="Explicit breakdown distinguishing observed factual telemetry from analytical hypotheses"
    )
    uncertainty_notes: Optional[str] = None
    recommended_action_type: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
