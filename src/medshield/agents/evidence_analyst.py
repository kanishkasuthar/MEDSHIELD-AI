"""Agent 2 — Evidence Analyst.

Inspects synthetic application logs, error codes, service health, and telemetry.
Distinguishes observed facts from hypotheses. Returns structured EvidenceReport.
Never invents log entries or claims unperformed diagnostic checks succeeded.
"""

from datetime import datetime, timezone
import uuid
from typing import List, Optional
from medshield.schemas.evidence import (
    EvidenceRequest,
    EvidenceReport,
    FactConfidence,
    LogEntryObservation,
    TelemetryObservation,
)
from medshield.schemas.actions import AllowedRecoveryAction
from medshield.simulator.service import SyntheticHospitalSimulator
from medshield.simulator.scenarios import ScenarioType, FAILURE_SCENARIOS


class EvidenceAnalystAgent:
    """Investigates synthetic hospital logs and telemetry to identify root causes."""

    def __init__(self, simulator: SyntheticHospitalSimulator):
        self.simulator = simulator

    def analyze_incident(self, request: EvidenceRequest) -> EvidenceReport:
        report_id = f"EVR-{uuid.uuid4().hex[:8]}"
        service_id = request.service_id

        # 1. Collect real synthetic logs directly from simulator (strictly uninvented)
        observed_logs: List[LogEntryObservation] = self.simulator.get_recent_logs(
            service_id=service_id,
            limit=15,
        )

        # 2. Collect real synthetic telemetry from simulator
        observed_telemetry: List[TelemetryObservation] = self.simulator.get_recent_telemetry(
            service_id=service_id,
        )

        # If service does not exist or has zero telemetry
        if not observed_telemetry and not observed_logs:
            return EvidenceReport(
                report_id=report_id,
                incident_id=request.incident_id,
                correlation_id=request.correlation_id,
                service_id=service_id,
                observed_facts=[],
                telemetry_facts=[],
                likely_root_cause="Unknown: Target service has no telemetry or log records in simulator.",
                confidence_score=0.1,
                confidence_level=FactConfidence.SPECULATIVE_HYPOTHESIS,
                distinction_summary="FACTS: 0 log records observed, 0 telemetry probes. HYPOTHESIS: Unmonitored or unmapped service.",
                uncertainty_notes="High uncertainty: Missing telemetry stream.",
                recommended_action_type=AllowedRecoveryAction.RESTART_SERVICE.value,
            )

        # 3. Analyze patterns without fabricating any log lines
        log_text = " ".join([entry.message.lower() for entry in observed_logs])
        error_telemetry = next((t for t in observed_telemetry if t.metric_name == "error_rate_percent"), None)
        latency_telemetry = next((t for t in observed_telemetry if t.metric_name == "latency_ms"), None)
        conn_telemetry = next((t for t in observed_telemetry if t.metric_name == "active_connections"), None)

        error_rate = error_telemetry.value if error_telemetry else 0.0
        latency = latency_telemetry.value if latency_telemetry else 0.0
        connections = conn_telemetry.value if conn_telemetry else 0.0

        # Pattern matching strictly against observed symptoms
        if "canary_alert" in log_text or "entropy spike" in log_text or "quarantined" in log_text:
            likely_root = "Simulated canary tripwire alert: High-entropy modification detected on honeypot share."
            action = AllowedRecoveryAction.ISOLATE_AND_RESTORE_HOST
            confidence = 0.95
            conf_level = FactConfidence.HIGH_CONFIDENCE_HYPOTHESIS
        elif "connectionpoolexhausted" in log_text or "remaining connection slots" in log_text or connections >= 500:
            likely_root = "PostgreSQL connection pool exhausted by leaked client connections."
            action = AllowedRecoveryAction.FLUSH_CONNECTION_POOL
            confidence = 0.92
            conf_level = FactConfidence.HIGH_CONFIDENCE_HYPOTHESIS
        elif "signatureverificationfailed" in log_text or "token signing cert expired" in log_text or "401 unauthorized" in log_text:
            likely_root = "SSO signing certificate expired causing universal authentication rejection."
            action = AllowedRecoveryAction.ROTATE_AUTH_KEYS
            confidence = 0.94
            conf_level = FactConfidence.HIGH_CONFIDENCE_HYPOTHESIS
        elif "hmac check failed" in log_text or "out-of-bounds telemetry" in log_text:
            likely_root = "Corrupted telemetry ingestion stream injecting invalid checksum frames."
            action = AllowedRecoveryAction.RESYNC_TELEMETRY_STREAM
            confidence = 0.90
            conf_level = FactConfidence.HIGH_CONFIDENCE_HYPOTHESIS
        elif "network unreachable" in log_text or "504 gateway timeout" in log_text or "retransmission" in log_text:
            likely_root = "Downstream network routing blackhole on DICOM PACS bridge."
            action = AllowedRecoveryAction.FAILOVER_DATABASE
            confidence = 0.88
            conf_level = FactConfidence.HIGH_CONFIDENCE_HYPOTHESIS
        elif "outofmemoryerror" in log_text or "crashed" in log_text or error_rate >= 90.0:
            likely_root = "Application container process crash induced by memory starvation (OOM)."
            action = AllowedRecoveryAction.RESTART_SERVICE
            confidence = 0.91
            conf_level = FactConfidence.HIGH_CONFIDENCE_HYPOTHESIS
        else:
            likely_root = f"Generic degradation on {service_id} with error rate {error_rate}% and latency {latency}ms."
            action = AllowedRecoveryAction.RESTART_SERVICE
            confidence = 0.55
            conf_level = FactConfidence.MODERATE_HYPOTHESIS

        distinction = (
            f"OBSERVED FACTS: {len(observed_logs)} log events captured (errors={sum(1 for l in observed_logs if l.level in ('ERROR', 'CRITICAL'))}); "
            f"Telemetry error_rate={error_rate}%, latency={latency}ms, active_connections={connections}. "
            f"ANALYTICAL HYPOTHESIS: Root cause evaluated as '{likely_root}' with confidence {confidence:.2f} based on heuristic symptom signature."
        )

        return EvidenceReport(
            report_id=report_id,
            incident_id=request.incident_id,
            correlation_id=request.correlation_id,
            service_id=service_id,
            observed_facts=observed_logs,
            telemetry_facts=observed_telemetry,
            likely_root_cause=likely_root,
            confidence_score=confidence,
            confidence_level=conf_level,
            distinction_summary=distinction,
            uncertainty_notes=None if confidence >= 0.8 else "Moderate uncertainty: Log patterns do not match a singular failure signature.",
            recommended_action_type=action.value,
        )
