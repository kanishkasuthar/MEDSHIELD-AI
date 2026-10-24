"""Tests for the Synthetic Hospital Simulator and 6 failure scenarios."""

import pytest
from medshield.simulator import (
    SyntheticHospitalSimulator,
    ScenarioType,
    ServiceState,
    FAILURE_SCENARIOS,
)
from medshield.schemas.actions import AllowedRecoveryAction, ExecutionStatus
from medshield.schemas.verification import ProbeStatus


@pytest.fixture
def simulator():
    sim = SyntheticHospitalSimulator()
    return sim


def test_baseline_clean_state(simulator):
    ehr = simulator.get_service("ehr-core-api")
    assert ehr is not None
    assert ehr.state == ServiceState.HEALTHY
    assert ehr.error_rate_percent == 0.0

    probe = simulator.probe_health("ehr-core-api")
    assert probe.status == ProbeStatus.HEALTHY
    assert "HTTP 200" in probe.details


@pytest.mark.parametrize("scenario_type", list(ScenarioType))
def test_all_six_failure_scenarios_injection(simulator, scenario_type):
    scenario = simulator.inject_scenario(scenario_type)
    assert scenario.scenario_id == scenario_type

    target_svc = simulator.get_service(scenario.target_service)
    assert target_svc is not None
    assert target_svc.state == ServiceState.CRITICAL
    assert target_svc.error_rate_percent > 0.0

    # Probe must independently report unhealthy
    probe = simulator.probe_health(scenario.target_service)
    assert probe.status == ProbeStatus.UNHEALTHY
    assert "HTTP 503" in probe.details

    # Logs must contain the scenario log messages
    logs = simulator.get_recent_logs(scenario.target_service)
    assert len(logs) > 0
    assert any(entry.level in ("ERROR", "CRITICAL", "WARN") for entry in logs)

    # Telemetry observations must reflect failure
    telemetry = simulator.get_recent_telemetry(scenario.target_service)
    assert len(telemetry) >= 4
    error_metric = next(t for t in telemetry if t.metric_name == "error_rate_percent")
    assert error_metric.value > 0.0


def test_successful_recovery_remediation(simulator):
    # Scenario 1: EHR App Outage requires RESTART_SERVICE
    simulator.inject_scenario(ScenarioType.EHR_APP_OUTAGE)
    assert simulator.probe_health("ehr-core-api").status == ProbeStatus.UNHEALTHY

    # Execute correct recovery action
    result = simulator.execute_recovery_action(
        action=AllowedRecoveryAction.RESTART_SERVICE,
        target_service="ehr-core-api",
        incident_id="INC-TEST-001",
    )
    assert result.status == ExecutionStatus.SUCCESS

    # Probe must now verify healthy
    probe = simulator.probe_health("ehr-core-api")
    assert probe.status == ProbeStatus.HEALTHY
    assert simulator.get_service("ehr-core-api").state == ServiceState.HEALTHY


def test_failed_recovery_on_wrong_action(simulator):
    # Scenario 2: DB Connection Failure requires FLUSH_CONNECTION_POOL
    simulator.inject_scenario(ScenarioType.DB_CONNECTION_FAILURE)
    assert simulator.probe_health("clinical-database").status == ProbeStatus.UNHEALTHY

    # Attempting ROTATE_AUTH_KEYS on the database will NOT fix connection exhaustion
    result = simulator.execute_recovery_action(
        action=AllowedRecoveryAction.ROTATE_AUTH_KEYS,
        target_service="clinical-database",
        incident_id="INC-TEST-002",
    )
    assert result.status == ExecutionStatus.FAILED
    assert "remediation action mismatch" in result.error_message.lower()

    # Probe must remain UNHEALTHY
    assert simulator.probe_health("clinical-database").status == ProbeStatus.UNHEALTHY


def test_probe_nonexistent_service(simulator):
    probe = simulator.probe_health("nonexistent-cloud-service")
    assert probe.status == ProbeStatus.UNKNOWN
    assert "does not exist" in probe.details
