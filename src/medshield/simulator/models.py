"""Models for the synthetic hospital simulator."""

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class ServiceState(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"
    OFFLINE = "OFFLINE"


class SyntheticService(BaseModel):
    service_id: str
    display_name: str
    state: ServiceState = ServiceState.HEALTHY
    health_endpoint: str
    error_rate_percent: float = 0.0
    latency_ms: float = 25.0
    active_connections: int = 42
    cpu_percent: float = 18.5
    memory_percent: float = 34.0
    last_restarted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status_details: str = "All synthetic clinical workloads running normally"


class SyntheticDepartment(BaseModel):
    department_id: str
    name: str
    floor: str
    criticality: str  # LIFE_CRITICAL, HIGH, STANDARD
    primary_workflows: List[str]
    active_patient_census: int


class SyntheticWorkflow(BaseModel):
    workflow_id: str
    name: str
    dependent_services: List[str]
    primary_departments: List[str]
    downtime_procedure_id: str
    description: str


class SimulatorLogEntry(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    service_id: str
    level: str  # INFO, WARN, ERROR, CRITICAL
    message: str
    trace_id: str
    correlation_id: Optional[str] = None
