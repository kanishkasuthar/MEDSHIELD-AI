"""Deterministic, controllable Synthetic Hospital Simulator service."""

from datetime import datetime, timezone
import uuid
from typing import Dict, List, Optional
from medshield.schemas.actions import (
    AllowedRecoveryAction,
    ActionExecutionResult,
    ExecutionStatus,
)
from medshield.schemas.evidence import (
    LogEntryObservation,
    TelemetryObservation,
)
from medshield.schemas.verification import (
    ProbeStatus,
    SingleHealthProbeResult,
)
from medshield.simulator.models import (
    ServiceState,
    SyntheticService,
    SimulatorLogEntry,
)
from medshield.simulator.scenarios import (
    ScenarioType,
    FAILURE_SCENARIOS,
    FailureScenario,
    DEFAULT_DEPARTMENTS,
    DEFAULT_WORKFLOWS,
)


class SyntheticHospitalSimulator:
    """Deterministic hospital IT environment simulator.

    Manages services, logs, telemetry, and failure scenarios.
    Ensures safe, allowlist-only recovery execution and realistic telemetry probes.
    """

    def __init__(self):
        self.services: Dict[str, SyntheticService] = {}
        self.log_buffer: List[SimulatorLogEntry] = []
        self.active_scenarios: Dict[str, ScenarioType] = {}
        self._action_execution_history: List[ActionExecutionResult] = []
        self.reset_to_clean_state()

    def reset_to_clean_state(self) -> None:
        """Reset all synthetic services and telemetry to baseline healthy state."""
        self.services = {
            "ehr-core-api": SyntheticService(
                service_id="ehr-core-api",
                display_name="Synthetic Hospital EHR Core API",
                state=ServiceState.HEALTHY,
                health_endpoint="/healthz",
                error_rate_percent=0.0,
                latency_ms=22.5,
                active_connections=48,
                cpu_percent=15.0,
                memory_percent=32.0,
                status_details="EHR core clinical APIs healthy and accepting requests",
            ),
            "clinical-database": SyntheticService(
                service_id="clinical-database",
                display_name="Clinical Encounter & Chart Database",
                state=ServiceState.HEALTHY,
                health_endpoint="/db/health",
                error_rate_percent=0.0,
                latency_ms=8.0,
                active_connections=35,
                cpu_percent=12.0,
                memory_percent=45.0,
                status_details="PostgreSQL connection pool healthy; replication lag 0ms",
            ),
            "pacs-gateway": SyntheticService(
                service_id="pacs-gateway",
                display_name="PACS Imaging Bridge & DICOM Router",
                state=ServiceState.HEALTHY,
                health_endpoint="/pacs/status",
                error_rate_percent=0.0,
                latency_ms=35.0,
                active_connections=14,
                cpu_percent=18.0,
                memory_percent=28.0,
                status_details="DICOM store-and-forward routes operating normally",
            ),
            "auth-sso-service": SyntheticService(
                service_id="auth-sso-service",
                display_name="Hospital Identity & Clinician SSO Gateway",
                state=ServiceState.HEALTHY,
                health_endpoint="/auth/health",
                error_rate_percent=0.0,
                latency_ms=12.0,
                active_connections=65,
                cpu_percent=10.0,
                memory_percent=22.0,
                status_details="SAML 2.0 and OAuth2 token endpoints validated",
            ),
            "telemetry-broker": SyntheticService(
                service_id="telemetry-broker",
                display_name="ICU & Bedside Telemetry Message Broker",
                state=ServiceState.HEALTHY,
                health_endpoint="/broker/health",
                error_rate_percent=0.0,
                latency_ms=5.0,
                active_connections=120,
                cpu_percent=22.0,
                memory_percent=38.0,
                status_details="Telemetry event queue healthy; zero dropped frames",
            ),
        }
        self.active_scenarios.clear()
        self._action_execution_history.clear()
        self.log_buffer = [
            SimulatorLogEntry(
                timestamp=datetime.now(timezone.utc),
                service_id="ehr-core-api",
                level="INFO",
                message="Synthetic hospital IT cluster initialized in normal baseline state.",
                trace_id="trace-init-001",
            )
        ]

    def inject_scenario(self, scenario_type: ScenarioType) -> FailureScenario:
        """Inject one of the 6 deterministic failure scenarios."""
        scenario = FAILURE_SCENARIOS[scenario_type]
        svc = self.services.get(scenario.target_service)
        if not svc:
            raise ValueError(f"Target service {scenario.target_service} not registered in simulator")

        svc.state = ServiceState.CRITICAL
        svc.error_rate_percent = scenario.telemetry_impact.get("error_rate_percent", 95.0)
        svc.latency_ms = scenario.telemetry_impact.get("latency_ms", 5000.0)
        if "active_connections" in scenario.telemetry_impact:
            svc.active_connections = int(scenario.telemetry_impact["active_connections"])
        if "cpu_percent" in scenario.telemetry_impact:
            svc.cpu_percent = scenario.telemetry_impact["cpu_percent"]
        if "memory_percent" in scenario.telemetry_impact:
            svc.memory_percent = scenario.telemetry_impact["memory_percent"]
        svc.status_details = f"SIMULATED_FAILURE: {scenario.name} - {scenario.root_cause_explanation}"

        self.active_scenarios[scenario.target_service] = scenario_type

        # Append synthetic logs
        for entry in scenario.synthetic_logs:
            self.log_buffer.append(
                SimulatorLogEntry(
                    timestamp=datetime.now(timezone.utc),
                    service_id=scenario.target_service,
                    level=entry["level"],
                    message=entry["message"],
                    trace_id=f"trace-{uuid.uuid4().hex[:8]}",
                )
            )

        return scenario

    def get_service(self, service_id: str) -> Optional[SyntheticService]:
        return self.services.get(service_id)

    def get_recent_logs(self, service_id: str, limit: int = 10) -> List[LogEntryObservation]:
        """Retrieve real synthetic logs from the simulator buffer for a service."""
        matching = [
            LogEntryObservation(
                timestamp=entry.timestamp,
                service=entry.service_id,
                level=entry.level,
                message=entry.message,
                observed=True,
            )
            for entry in self.log_buffer
            if entry.service_id == service_id
        ]
        return matching[-limit:]

    def get_recent_telemetry(self, service_id: str) -> List[TelemetryObservation]:
        """Retrieve real synthetic telemetry observations for a service."""
        svc = self.services.get(service_id)
        if not svc:
            return []
        now = datetime.now(timezone.utc)
        telemetry_status = "FAILED" if svc.state in (ServiceState.CRITICAL, ServiceState.OFFLINE) else "HEALTHY"
        return [
            TelemetryObservation(
                metric_name="error_rate_percent",
                value=svc.error_rate_percent,
                unit="percent",
                status=telemetry_status,
                observed_at=now,
            ),
            TelemetryObservation(
                metric_name="latency_ms",
                value=svc.latency_ms,
                unit="milliseconds",
                status=telemetry_status,
                observed_at=now,
            ),
            TelemetryObservation(
                metric_name="cpu_percent",
                value=svc.cpu_percent,
                unit="percent",
                status="DEGRADED" if svc.cpu_percent > 85.0 else "HEALTHY",
                observed_at=now,
            ),
            TelemetryObservation(
                metric_name="active_connections",
                value=float(svc.active_connections),
                unit="count",
                status="DEGRADED" if svc.active_connections >= 500 else "HEALTHY",
                observed_at=now,
            ),
        ]

    def probe_health(self, service_id: str, probe_index: int = 1) -> SingleHealthProbeResult:
        """Independent health probe checking the simulator service endpoint."""
        svc = self.services.get(service_id)
        now = datetime.now(timezone.utc)
        if not svc:
            return SingleHealthProbeResult(
                probe_index=probe_index,
                service_id=service_id,
                endpoint_or_component="/unknown",
                status=ProbeStatus.UNKNOWN,
                latency_ms=0.0,
                details=f"Service {service_id} does not exist in simulator registry",
                probed_at=now,
            )

        if svc.state == ServiceState.HEALTHY:
            return SingleHealthProbeResult(
                probe_index=probe_index,
                service_id=service_id,
                endpoint_or_component=svc.health_endpoint,
                status=ProbeStatus.HEALTHY,
                latency_ms=svc.latency_ms,
                details=f"HTTP 200 OK — {svc.status_details}",
                probed_at=now,
            )
        else:
            return SingleHealthProbeResult(
                probe_index=probe_index,
                service_id=service_id,
                endpoint_or_component=svc.health_endpoint,
                status=ProbeStatus.UNHEALTHY,
                latency_ms=svc.latency_ms,
                details=f"HTTP 503 Service Degraded/Unavailable — {svc.status_details}",
                probed_at=now,
            )

    def execute_recovery_action(
        self,
        action: AllowedRecoveryAction,
        target_service: str,
        parameters: Optional[Dict] = None,
        incident_id: str = "INC-UNKNOWN",
    ) -> ActionExecutionResult:
        """Execute an explicitly allowlisted action strictly on the synthetic simulator."""
        execution_id = f"EXEC-{uuid.uuid4().hex[:8]}"
        svc = self.services.get(target_service)
        if not svc:
            return ActionExecutionResult(
                execution_id=execution_id,
                incident_id=incident_id,
                action=action,
                target_service=target_service,
                status=ExecutionStatus.FAILED,
                simulator_output="",
                error_message=f"Target service {target_service} not recognized by simulator",
            )

        # Check if active scenario matches the action's capability
        active_scenario_type = self.active_scenarios.get(target_service)
        scenario = FAILURE_SCENARIOS.get(active_scenario_type) if active_scenario_type else None

        # Verify whether the recovery action fixes the active problem
        if scenario and scenario.required_recovery_action != action:
            msg = (
                f"Action {action.value} executed against {target_service}, but failed to remediate: "
                f"Service still degraded. Expected required action was {scenario.required_recovery_action.value}."
            )
            self.log_buffer.append(
                SimulatorLogEntry(
                    timestamp=datetime.now(timezone.utc),
                    service_id=target_service,
                    level="WARN",
                    message=msg,
                    trace_id=f"trace-{uuid.uuid4().hex[:8]}",
                )
            )
            res = ActionExecutionResult(
                execution_id=execution_id,
                incident_id=incident_id,
                action=action,
                target_service=target_service,
                status=ExecutionStatus.FAILED,
                simulator_output=msg,
                error_message="Remediation action mismatch: service remains in failed state",
            )
            self._action_execution_history.append(res)
            return res

        # Remediate service
        svc.state = ServiceState.HEALTHY
        svc.error_rate_percent = 0.0
        svc.latency_ms = 20.0
        svc.cpu_percent = 15.0
        svc.memory_percent = 30.0
        svc.last_restarted_at = datetime.now(timezone.utc)
        svc.status_details = f"Remediated via {action.value}. All synthetic clinical workloads healthy."

        if target_service in self.active_scenarios:
            del self.active_scenarios[target_service]

        log_msg = f"Recovery action {action.value} successfully executed for {target_service}. Health restored."
        self.log_buffer.append(
            SimulatorLogEntry(
                timestamp=datetime.now(timezone.utc),
                service_id=target_service,
                level="INFO",
                message=log_msg,
                trace_id=f"trace-{uuid.uuid4().hex[:8]}",
            )
        )

        res = ActionExecutionResult(
            execution_id=execution_id,
            incident_id=incident_id,
            action=action,
            target_service=target_service,
            status=ExecutionStatus.SUCCESS,
            simulator_output=log_msg,
            error_message=None,
        )
        self._action_execution_history.append(res)
        return res
