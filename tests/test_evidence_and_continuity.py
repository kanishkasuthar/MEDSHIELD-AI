"""Tests for Agent 2 (Evidence Analyst) and Agent 3 (Clinical Continuity Analyst)."""

import pytest
from medshield.simulator import SyntheticHospitalSimulator, ScenarioType
from medshield.agents.evidence_analyst import EvidenceAnalystAgent
from medshield.agents.clinical_continuity import ClinicalContinuityAnalystAgent
from medshield.schemas.evidence import EvidenceRequest, FactConfidence
from medshield.schemas.continuity import ClinicalImpactRequest, ClinicalImpactSeverity
from medshield.schemas.actions import AllowedRecoveryAction


@pytest.fixture
def simulator():
    return SyntheticHospitalSimulator()


@pytest.fixture
def evidence_analyst(simulator):
    return EvidenceAnalystAgent(simulator)


@pytest.fixture
def clinical_analyst():
    return ClinicalContinuityAnalystAgent()


def test_evidence_analyst_ehr_app_outage(simulator, evidence_analyst):
    # Inject EHR outage scenario
    simulator.inject_scenario(ScenarioType.EHR_APP_OUTAGE)

    req = EvidenceRequest(
        incident_id="INC-EHR-01",
        correlation_id="CORR-EHR-01",
        service_id="ehr-core-api",
    )
    report = evidence_analyst.analyze_incident(req)

    assert report.incident_id == "INC-EHR-01"
    assert report.service_id == "ehr-core-api"
    assert len(report.observed_facts) > 0
    # Facts must be marked as observed
    assert all(fact.observed for fact in report.observed_facts)
    # Check root cause and recommended action
    assert "memory" in report.likely_root_cause.lower() or "crash" in report.likely_root_cause.lower()
    assert report.recommended_action_type == AllowedRecoveryAction.RESTART_SERVICE.value
    assert report.confidence_level == FactConfidence.HIGH_CONFIDENCE_HYPOTHESIS
    assert report.confidence_score >= 0.8
    # Distinction summary must contain both OBSERVED FACTS and ANALYTICAL HYPOTHESIS
    assert "OBSERVED FACTS:" in report.distinction_summary
    assert "ANALYTICAL HYPOTHESIS:" in report.distinction_summary


def test_evidence_analyst_db_connection_pool_failure(simulator, evidence_analyst):
    simulator.inject_scenario(ScenarioType.DB_CONNECTION_FAILURE)

    req = EvidenceRequest(
        incident_id="INC-DB-01",
        correlation_id="CORR-DB-01",
        service_id="clinical-database",
    )
    report = evidence_analyst.analyze_incident(req)

    assert "connection" in report.likely_root_cause.lower()
    assert report.recommended_action_type == AllowedRecoveryAction.FLUSH_CONNECTION_POOL.value
    assert report.confidence_level == FactConfidence.HIGH_CONFIDENCE_HYPOTHESIS


def test_evidence_analyst_ransomware_tripwire(simulator, evidence_analyst):
    simulator.inject_scenario(ScenarioType.RANSOMWARE_SIMULATION)

    req = EvidenceRequest(
        incident_id="INC-RANSOM-01",
        correlation_id="CORR-RANSOM-01",
        service_id="ehr-core-api",
    )
    report = evidence_analyst.analyze_incident(req)

    assert "canary" in report.likely_root_cause.lower() or "entropy" in report.likely_root_cause.lower()
    assert report.recommended_action_type == AllowedRecoveryAction.ISOLATE_AND_RESTORE_HOST.value


def test_evidence_analyst_unknown_service_no_fabrication(simulator, evidence_analyst):
    # Analyzing an unmonitored / non-existent service must not invent log lines
    req = EvidenceRequest(
        incident_id="INC-UNKNOWN-01",
        correlation_id="CORR-UNK-01",
        service_id="non-existent-service",
    )
    report = evidence_analyst.analyze_incident(req)

    assert len(report.observed_facts) == 0
    assert len(report.telemetry_facts) == 0
    assert report.confidence_level == FactConfidence.SPECULATIVE_HYPOTHESIS
    assert report.confidence_score < 0.5
    assert "Uncertainty" in report.uncertainty_notes or "uncertainty" in report.uncertainty_notes.lower()


def test_clinical_continuity_ehr_impact(clinical_analyst):
    req = ClinicalImpactRequest(
        incident_id="INC-CLIN-01",
        correlation_id="CORR-CLIN-01",
        service_id="ehr-core-api",
    )
    report = clinical_analyst.assess_impact(req)

    assert report.service_id == "ehr-core-api"
    # Should affect life-critical departments: ED, ICU, OR
    affected_dept_ids = [d.department_id for d in report.affected_departments]
    assert "ED" in affected_dept_ids
    assert "ICU" in affected_dept_ids
    assert "OR" in affected_dept_ids
    assert "PHARMACY" in affected_dept_ids

    # High impact escalation must be triggered due to life-critical departments
    assert report.high_impact_escalation_required is True
    assert report.escalation_reason is not None

    # Curated downtime procedures must be attached
    proc_ids = [p.procedure_id for p in report.recommended_downtime_procedures]
    assert "DP-MAR-01" in proc_ids
    assert "DP-CPOE-02" in proc_ids

    # Check versioned procedures
    emar_proc = next(p for p in report.recommended_downtime_procedures if p.procedure_id == "DP-MAR-01")
    assert emar_proc.version == "v2.4"
    assert len(emar_proc.immediate_mitigation_steps) > 0
    assert len(emar_proc.paper_forms_required) > 0


def test_clinical_continuity_pacs_impact(clinical_analyst):
    req = ClinicalImpactRequest(
        incident_id="INC-PACS-01",
        correlation_id="CORR-PACS-01",
        service_id="pacs-gateway",
    )
    report = clinical_analyst.assess_impact(req)

    affected_dept_ids = [d.department_id for d in report.affected_departments]
    assert "RADIOLOGY" in affected_dept_ids
    assert "OR" in affected_dept_ids
    assert "ED" in affected_dept_ids

    proc_ids = [p.procedure_id for p in report.recommended_downtime_procedures]
    assert "DP-PACS-03" in proc_ids
    pacs_proc = next(p for p in report.recommended_downtime_procedures if p.procedure_id == "DP-PACS-03")
    assert pacs_proc.version == "v1.8"
    assert any("DICOM CDs" in step or "scanner" in step.lower() for step in pacs_proc.immediate_mitigation_steps)
