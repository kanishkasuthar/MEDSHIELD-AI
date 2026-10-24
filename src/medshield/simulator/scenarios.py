"""Deterministic hospital departments, workflows, and 6 failure scenarios."""

from enum import Enum
from typing import Dict, List
from pydantic import BaseModel
from medshield.schemas.actions import AllowedRecoveryAction
from medshield.simulator.models import SyntheticDepartment, SyntheticWorkflow


class ScenarioType(str, Enum):
    EHR_APP_OUTAGE = "EHR_APP_OUTAGE"
    DB_CONNECTION_FAILURE = "DB_CONNECTION_FAILURE"
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    AUTH_SERVICE_FAILURE = "AUTH_SERVICE_FAILURE"
    RANSOMWARE_SIMULATION = "RANSOMWARE_SIMULATION"
    TELEMETRY_SPOOFING = "TELEMETRY_SPOOFING"


class FailureScenario(BaseModel):
    scenario_id: ScenarioType
    name: str
    target_service: str
    description: str
    symptoms: List[str]
    root_cause_explanation: str
    synthetic_logs: List[Dict[str, str]]
    telemetry_impact: Dict[str, float]
    required_recovery_action: AllowedRecoveryAction
    remedy_description: str


# Standard synthetic hospital departments
DEFAULT_DEPARTMENTS: Dict[str, SyntheticDepartment] = {
    "ED": SyntheticDepartment(
        department_id="ED",
        name="Emergency Department & Level 1 Trauma",
        floor="Ground Floor - East Wing",
        criticality="LIFE_CRITICAL",
        primary_workflows=["TRIAGE_INTAKE", "EMAR_MEDICATION", "CPOE_ORDERS", "TRAUMA_RESUSCITATION"],
        active_patient_census=48,
    ),
    "ICU": SyntheticDepartment(
        department_id="ICU",
        name="Intensive Care Unit (Medical & Surgical)",
        floor="3rd Floor - Tower B",
        criticality="LIFE_CRITICAL",
        primary_workflows=["EMAR_MEDICATION", "CONTINUOUS_VITALS", "CPOE_ORDERS", "VENTILATOR_MONITORING"],
        active_patient_census=24,
    ),
    "OR": SyntheticDepartment(
        department_id="OR",
        name="Surgical Suite & Operating Theatres",
        floor="2nd Floor - Surgical Center",
        criticality="LIFE_CRITICAL",
        primary_workflows=["PERIOPERATIVE_CHARTING", "EMAR_MEDICATION", "PACS_IMAGING"],
        active_patient_census=12,
    ),
    "PHARMACY": SyntheticDepartment(
        department_id="PHARMACY",
        name="Inpatient Central Pharmacy",
        floor="Basement Floor - Central Supply",
        criticality="HIGH",
        primary_workflows=["RX_DISPENSING", "VERIFY_ORDERS", "EMAR_MEDICATION"],
        active_patient_census=0,
    ),
    "RADIOLOGY": SyntheticDepartment(
        department_id="RADIOLOGY",
        name="Diagnostic Imaging & Radiology",
        floor="1st Floor - West Wing",
        criticality="HIGH",
        primary_workflows=["PACS_IMAGING", "CT_MRI_STUDIES"],
        active_patient_census=16,
    ),
    "MED_SURG": SyntheticDepartment(
        department_id="MED_SURG",
        name="Inpatient Medical-Surgical Units",
        floor="4th & 5th Floors - Main Pavilion",
        criticality="HIGH",
        primary_workflows=["EMAR_MEDICATION", "CPOE_ORDERS", "PATIENT_ADMISSION"],
        active_patient_census=110,
    ),
}

# Standard synthetic workflows
DEFAULT_WORKFLOWS: Dict[str, SyntheticWorkflow] = {
    "EMAR_MEDICATION": SyntheticWorkflow(
        workflow_id="EMAR_MEDICATION",
        name="Electronic Medication Administration Record (eMAR)",
        dependent_services=["ehr-core-api", "clinical-database", "pharmacy-connector"],
        primary_departments=["ED", "ICU", "OR", "PHARMACY", "MED_SURG"],
        downtime_procedure_id="DP-MAR-01",
        description="Bedside barcode medication scanning and dose administration verification.",
    ),
    "CPOE_ORDERS": SyntheticWorkflow(
        workflow_id="CPOE_ORDERS",
        name="Computerized Physician Order Entry (CPOE)",
        dependent_services=["ehr-core-api", "clinical-database", "auth-sso-service"],
        primary_departments=["ED", "ICU", "OR", "MED_SURG"],
        downtime_procedure_id="DP-CPOE-02",
        description="Physician electronic medication, lab, and consultation order entry.",
    ),
    "PACS_IMAGING": SyntheticWorkflow(
        workflow_id="PACS_IMAGING",
        name="Picture Archiving and Communication System (PACS)",
        dependent_services=["pacs-gateway", "network-backbone"],
        primary_departments=["ED", "OR", "RADIOLOGY"],
        downtime_procedure_id="DP-PACS-03",
        description="High-resolution DICOM diagnostic imaging retrieval and radiologist review.",
    ),
    "PATIENT_ADMISSION": SyntheticWorkflow(
        workflow_id="PATIENT_ADMISSION",
        name="Patient Identity & Admission Discharge Transfer (ADT)",
        dependent_services=["ehr-core-api", "auth-sso-service", "integration-engine"],
        primary_departments=["ED", "MED_SURG"],
        downtime_procedure_id="DP-ADT-04",
        description="Master Patient Index registration, room assignment, and bed tracking.",
    ),
}

# 6 repeatable, deterministic scenarios
FAILURE_SCENARIOS: Dict[ScenarioType, FailureScenario] = {
    ScenarioType.EHR_APP_OUTAGE: FailureScenario(
        scenario_id=ScenarioType.EHR_APP_OUTAGE,
        name="Synthetic EHR Core Application Outage",
        target_service="ehr-core-api",
        description="EHR web application worker processes crashed under memory starvation.",
        symptoms=["HTTP 503 Service Unavailable", "Worker threads unresponsive", "Error rate at 100%"],
        root_cause_explanation="Memory starvation induced uncaught SIGTERM on gunicorn worker pool in synthetic container.",
        synthetic_logs=[
            {"level": "CRITICAL", "message": "Worker thread 12 pid 4091 crashed: OutOfMemoryError"},
            {"level": "ERROR", "message": "Health probe /healthz returned 503: Service Unavailable"},
            {"level": "WARN", "message": "Circuit breaker OPEN for upstream route /api/v1/patients"},
        ],
        telemetry_impact={"error_rate_percent": 100.0, "latency_ms": 5000.0, "cpu_percent": 99.2, "memory_percent": 98.6},
        required_recovery_action=AllowedRecoveryAction.RESTART_SERVICE,
        remedy_description="Restart container process pool for ehr-core-api.",
    ),
    ScenarioType.DB_CONNECTION_FAILURE: FailureScenario(
        scenario_id=ScenarioType.DB_CONNECTION_FAILURE,
        name="Clinical Database Connection Pool Exhaustion",
        target_service="clinical-database",
        description="Synthetic relational database pool reached maximum active clients and dropped idle timeouts.",
        symptoms=["SQL ConnectionPoolTimeout", "Active connections at capacity (500/500)", "Queries timing out"],
        root_cause_explanation="Connection leak in legacy HL7 parser holding open idle transactions, exhausting PostgreSQL max_connections.",
        synthetic_logs=[
            {"level": "ERROR", "message": "FATAL: remaining connection slots are reserved for non-replication superuser connections"},
            {"level": "ERROR", "message": "ConnectionPoolExhausted: PoolSize=500, CheckedOut=500, Waiting=142"},
            {"level": "WARN", "message": "Client query abort after 30000ms timeout on table clinical_encounters"},
        ],
        telemetry_impact={"error_rate_percent": 84.5, "latency_ms": 3200.0, "active_connections": 500, "cpu_percent": 88.0},
        required_recovery_action=AllowedRecoveryAction.FLUSH_CONNECTION_POOL,
        remedy_description="Flush orphaned connections and reset connection pool for clinical-database.",
    ),
    ScenarioType.NETWORK_TIMEOUT: FailureScenario(
        scenario_id=ScenarioType.NETWORK_TIMEOUT,
        name="Downstream PACS & Integration Network Timeout",
        target_service="pacs-gateway",
        description="Simulated network packet drop on DICOM integration bridge causing gateway timeout.",
        symptoms=["TCP handshake retransmissions > 40%", "DICOM C-FIND queries failing", "504 Gateway Timeout"],
        root_cause_explanation="Simulated SDN route flapping caused routing blackhole between PACS Gateway and Imaging Storage Node.",
        synthetic_logs=[
            {"level": "ERROR", "message": "PACS Bridge: C-MOVE failed for SOPInstanceUID 1.2.840.10008.5.1: Network unreachable"},
            {"level": "WARN", "message": "TCP Retransmission rate exceeded 45% on interface eth1"},
            {"level": "ERROR", "message": "HTTP 504 Gateway Timeout connecting to dicom-store.internal"},
        ],
        telemetry_impact={"error_rate_percent": 76.0, "latency_ms": 4500.0, "cpu_percent": 24.0, "memory_percent": 38.0},
        required_recovery_action=AllowedRecoveryAction.FAILOVER_DATABASE,  # Or failover secondary path
        remedy_description="Failover primary DICOM route to redundant storage node.",
    ),
    ScenarioType.AUTH_SERVICE_FAILURE: FailureScenario(
        scenario_id=ScenarioType.AUTH_SERVICE_FAILURE,
        name="Authentication & SSO Certificate Expiration",
        target_service="auth-sso-service",
        description="Synthetic OAuth/SAML token signing certificate expired, causing universal 401 Unauthorized errors.",
        symptoms=["HTTP 401 Unauthorized on all clinician logins", "JWT signature validation failed: Key Expired"],
        root_cause_explanation="Automated key rotation daemon stalled; current RSA signing key expired at synthetic midnight.",
        synthetic_logs=[
            {"level": "CRITICAL", "message": "OAuth2TokenValidator: SignatureVerificationFailed: Token signing cert expired at 00:00:00Z"},
            {"level": "ERROR", "message": "SSO Handshake failed for clinical workstation ws-ed-04: 401 Unauthorized"},
            {"level": "WARN", "message": "Kerberos ticket validation fallback rejected for 18 sessions"},
        ],
        telemetry_impact={"error_rate_percent": 95.0, "latency_ms": 120.0, "cpu_percent": 30.0, "memory_percent": 40.0},
        required_recovery_action=AllowedRecoveryAction.ROTATE_AUTH_KEYS,
        remedy_description="Rotate signing keys and distribute new public key to SSO validators.",
    ),
    ScenarioType.RANSOMWARE_SIMULATION: FailureScenario(
        scenario_id=ScenarioType.RANSOMWARE_SIMULATION,
        name="Simulated Canary Host Ransomware Disruption",
        target_service="ehr-core-api",
        description="Canary sensor detected rapid unauthorized file entropy changes and bulk lock attempts on isolated honeypot mount.",
        symptoms=["Canary tripwire alerted", "High I/O entropy detected on /var/hospital/canary_files", "Host isolated by watchdog"],
        root_cause_explanation="Synthetic honeypot node detected suspicious file modification velocity matching ransomware simulator test.",
        synthetic_logs=[
            {"level": "CRITICAL", "message": "CANARY_ALERT: Entropy spike > 7.9 detected on canary storage share /data/canary"},
            {"level": "CRITICAL", "message": "Emergency containment: Service ehr-core-api host canary-node-01 quarantined from clinical LAN"},
            {"level": "ERROR", "message": "Application access halted by automated defensive tripwire"},
        ],
        telemetry_impact={"error_rate_percent": 100.0, "latency_ms": 9999.0, "cpu_percent": 99.0, "memory_percent": 85.0},
        required_recovery_action=AllowedRecoveryAction.ISOLATE_AND_RESTORE_HOST,
        remedy_description="Purge quarantined canary host and restore clean verified immutable snapshot.",
    ),
    ScenarioType.TELEMETRY_SPOOFING: FailureScenario(
        scenario_id=ScenarioType.TELEMETRY_SPOOFING,
        name="Simulated Telemetry Spoofing & Corrupted Telemetry Stream",
        target_service="telemetry-broker",
        description="Anomalous synthetic vital signs and forged HMAC signatures detected in broker ingestion queue.",
        symptoms=["Telemetry signature mismatch", "Physiologic vitals out of physical range (HR: 999 bpm)", "Integrity alerts"],
        root_cause_explanation="Corrupted telemetry stream injecting invalid checksum payloads into telemetry-broker queue.",
        synthetic_logs=[
            {"level": "WARN", "message": "TelemetryIngest: Cryptographic HMAC check failed for telemetry device node-icu-bed03"},
            {"level": "ERROR", "message": "Out-of-bounds telemetry reading rejected: HeartRate=999, SpO2=-5%"},
            {"level": "CRITICAL", "message": "Broker ingestion paused: 250 corrupted frames quarantined"},
        ],
        telemetry_impact={"error_rate_percent": 68.0, "latency_ms": 800.0, "cpu_percent": 45.0, "memory_percent": 50.0},
        required_recovery_action=AllowedRecoveryAction.RESYNC_TELEMETRY_STREAM,
        remedy_description="Resync telemetry broker stream, flush corrupted buffer, and reissue device session keys.",
    ),
}
