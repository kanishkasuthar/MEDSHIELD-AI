"""Clinical Continuity Analyst schemas."""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class ClinicalImpactSeverity(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DepartmentImpact(BaseModel):
    department_id: str  # ED, ICU, OR, PHARMACY, RADIOLOGY, INPATIENT
    department_name: str
    impact_level: ClinicalImpactSeverity
    affected_workflows: List[str]
    patient_safety_risk: str


class DowntimeProcedure(BaseModel):
    procedure_id: str
    title: str
    version: str
    target_workflows: List[str]
    immediate_mitigation_steps: List[str]
    paper_forms_required: List[str]
    escalation_threshold: str


class ClinicalImpactRequest(BaseModel):
    incident_id: str
    correlation_id: str
    service_id: str
    root_cause_hint: Optional[str] = None


class ClinicalImpactReport(BaseModel):
    report_id: str
    incident_id: str
    correlation_id: str
    service_id: str
    affected_departments: List[DepartmentImpact] = Field(default_factory=list)
    recommended_downtime_procedures: List[DowntimeProcedure] = Field(default_factory=list)
    high_impact_escalation_required: bool = False
    escalation_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
