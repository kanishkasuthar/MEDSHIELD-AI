"""Hospital Operations Chatbot schemas and ACP adapter models."""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class ChatRole(str, Enum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    SYSTEM = "SYSTEM"


class OperatorRole(str, Enum):
    IT_OPERATOR = "IT_OPERATOR"
    CLINICAL_COORDINATOR = "CLINICAL_COORDINATOR"
    HOSPITAL_EXECUTIVE = "HOSPITAL_EXECUTIVE"
    AUDITOR = "AUDITOR"
    UNAUTHORIZED_GUEST = "UNAUTHORIZED_GUEST"


class ChatRequest(BaseModel):
    request_id: str
    operator_id: str
    operator_role: OperatorRole = OperatorRole.IT_OPERATOR
    query: str
    active_incident_id: Optional[str] = None
    correlation_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChatResponse(BaseModel):
    response_id: str
    request_id: str
    answer: str
    referenced_incident_id: Optional[str] = None
    data_sources: List[str] = Field(default_factory=list)
    distinction: str = Field(
        default="All hospital environments, patient records, and service telemetry in MEDSHIELD AI are synthetic test models."
    )
    authorized: bool = True
    missing_info_needed: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
