"""Agent 3 — Clinical Continuity Analyst.

Maps affected simulated services to fictional hospital departments and care workflows.
Retrieves curated, versioned downtime procedures.
Explains affected workflows and mitigations. Escalates high-impact situations.
Never diagnoses patients or invents medical instructions.
"""

from datetime import datetime, timezone
import uuid
from typing import Dict, List
from medshield.schemas.continuity import (
    ClinicalImpactRequest,
    ClinicalImpactReport,
    ClinicalImpactSeverity,
    DepartmentImpact,
    DowntimeProcedure,
)
from medshield.simulator.scenarios import (
    DEFAULT_DEPARTMENTS,
    DEFAULT_WORKFLOWS,
    SyntheticDepartment,
    SyntheticWorkflow,
)


CURATED_DOWNTIME_PROCEDURES: Dict[str, DowntimeProcedure] = {
    "DP-MAR-01": DowntimeProcedure(
        procedure_id="DP-MAR-01",
        title="Emergency Paper Medication Administration Record (eMAR) Activation",
        version="v2.4",
        target_workflows=["EMAR_MEDICATION"],
        immediate_mitigation_steps=[
            "Switch to bedside paper MAR binders located in emergency downtime cart.",
            "Enforce mandatory independent double-check by two RNs for all high-alert medications (heparin, insulin, narcotics).",
            "Pharmacy to deliver 24-hour printed medication profile backups to all acute nurse stations.",
        ],
        paper_forms_required=["FORM-MAR-101 (Bedside Medication Flowsheet)", "FORM-HIGH-ALERT-04 (Dual Sign-off)"],
        escalation_threshold="Service outage > 15 minutes or any delay in emergency STAT medication administration.",
    ),
    "DP-CPOE-02": DowntimeProcedure(
        procedure_id="DP-CPOE-02",
        title="Manual Paper Physician Order Entry & STAT Runner Protocol",
        version="v3.1",
        target_workflows=["CPOE_ORDERS"],
        immediate_mitigation_steps=[
            "Deploy multi-copy carbonless physician downtime order sheets (Form CPOE-PAPER-01).",
            "Dispatch designated unit runner to hand-deliver STAT pharmacy and blood bank requisitions.",
            "Telephone verbal order read-back policy enacted strictly for life-critical emergent interventions.",
        ],
        paper_forms_required=["FORM-CPOE-PAPER-01 (Physician Orders)", "FORM-STAT-ORDER-RED (Urgent Dispatch Tag)"],
        escalation_threshold="Backlog of unverified critical care orders exceeding 10 minutes in ED or ICU.",
    ),
    "DP-PACS-03": DowntimeProcedure(
        procedure_id="DP-PACS-03",
        title="Radiology Local Console Viewing & Mobile Ultrasound Standby",
        version="v1.8",
        target_workflows=["PACS_IMAGING"],
        immediate_mitigation_steps=[
            "Radiologists conduct direct diagnostic reads at physical CT/MRI scanner diagnostic consoles.",
            "Burn encrypted DICOM CDs for emergent surgical trauma cases requiring operating room review.",
            "Deploy point-of-care ultrasound (POCUS) carts to ED and Trauma bays for rapid bedside evaluation.",
        ],
        paper_forms_required=["FORM-RAD-EMERG-ROUTING-02 (Emergency Image Tracking)"],
        escalation_threshold="Inability to review cross-sectional imaging for ongoing acute stroke or surgical trauma cases.",
    ),
    "DP-ADT-04": DowntimeProcedure(
        procedure_id="DP-ADT-04",
        title="Manual Patient Armband & Paper Downtime Census Protocol",
        version="v2.0",
        target_workflows=["PATIENT_ADMISSION"],
        immediate_mitigation_steps=[
            "Affix pre-printed downtime wristbands with unique temporary medical record numbers (T-MRN).",
            "Maintain centralized dry-erase unit census board for patient room and bed tracking.",
            "Log all transfers, admissions, and discharges on paper Form ADT-LOG-01.",
        ],
        paper_forms_required=["FORM-ADT-LOG-01 (Downtime Census Sheet)", "FORM-TEMP-ID-BAND (Emergency Wristband)"],
        escalation_threshold="Emergency department overcrowding or inability to verify patient identity during mass casualty intake.",
    ),
}


class ClinicalContinuityAnalystAgent:
    """Evaluates clinical workflow disruption and assigns versioned downtime mitigations."""

    def __init__(self):
        self.departments = DEFAULT_DEPARTMENTS
        self.workflows = DEFAULT_WORKFLOWS
        self.procedures = CURATED_DOWNTIME_PROCEDURES

    def assess_impact(self, request: ClinicalImpactRequest) -> ClinicalImpactReport:
        report_id = f"CIR-{uuid.uuid4().hex[:8]}"
        service_id = request.service_id

        # 1. Identify all workflows depending on this simulated service
        impacted_workflows: List[SyntheticWorkflow] = [
            wf for wf in self.workflows.values()
            if service_id in wf.dependent_services
        ]

        # 2. Identify all departments participating in these workflows
        dept_ids_impacted = set()
        for wf in impacted_workflows:
            for d_id in wf.primary_departments:
                dept_ids_impacted.add(d_id)

        # 3. Build DepartmentImpact records
        department_impacts: List[DepartmentImpact] = []
        life_critical_affected = False

        for d_id in sorted(dept_ids_impacted):
            dept = self.departments.get(d_id)
            if not dept:
                continue

            # Determine severity based on department criticality
            if dept.criticality == "LIFE_CRITICAL":
                severity = ClinicalImpactSeverity.CRITICAL
                life_critical_affected = True
                safety_risk = "IMMEDIATE: Potential for delayed bedside resuscitation, STAT medication errors, or surgical delay."
            elif dept.criticality == "HIGH":
                severity = ClinicalImpactSeverity.HIGH
                safety_risk = "MODERATE: Delayed clinical documentation and order verification. Manual workarounds required."
            else:
                severity = ClinicalImpactSeverity.MODERATE
                safety_risk = "LOW: Non-urgent administrative delay."

            # Find matching workflows for this department
            matching_wf_names = [
                wf.name for wf in impacted_workflows
                if d_id in wf.primary_departments
            ]

            department_impacts.append(
                DepartmentImpact(
                    department_id=dept.department_id,
                    department_name=dept.name,
                    impact_level=severity,
                    affected_workflows=matching_wf_names,
                    patient_safety_risk=safety_risk,
                )
            )

        # 4. Collect applicable downtime procedures
        applicable_procedures: List[DowntimeProcedure] = []
        seen_proc_ids = set()
        for wf in impacted_workflows:
            proc_id = wf.downtime_procedure_id
            if proc_id in self.procedures and proc_id not in seen_proc_ids:
                applicable_procedures.append(self.procedures[proc_id])
                seen_proc_ids.add(proc_id)

        escalation_reason = None
        if life_critical_affected:
            crit_names = [d.department_name for d in department_impacts if d.impact_level == ClinicalImpactSeverity.CRITICAL]
            escalation_reason = (
                f"Life-critical departments affected ({', '.join(crit_names)}). "
                f"Emergency downtime procedures must be activated immediately."
            )

        return ClinicalImpactReport(
            report_id=report_id,
            incident_id=request.incident_id,
            correlation_id=request.correlation_id,
            service_id=service_id,
            affected_departments=department_impacts,
            recommended_downtime_procedures=applicable_procedures,
            high_impact_escalation_required=life_critical_affected,
            escalation_reason=escalation_reason,
        )
