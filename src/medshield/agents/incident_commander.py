"""Agent 1 — Incident Commander.

Main entry agent and orchestrator.
Accepts incidents, coordinates specialist agents, drives the incident state machine,
enforces approval gates, logs append-only audit events, and produces final incident reports.
"""

from datetime import datetime, timezone
import json
import uuid
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from medshield.db.models import DBIncident
from medshield.db.session import AuditLogger
from medshield.schemas.incident import (
    IncidentRequest,
    IncidentStatus,
    IncidentState,
    IncidentSeverity,
    StateTransitionEvent,
)
from medshield.schemas.evidence import EvidenceRequest, EvidenceReport
from medshield.schemas.continuity import ClinicalImpactRequest, ClinicalImpactReport
from medshield.schemas.actions import (
    AllowedRecoveryAction,
    ApprovalRequest,
    ApprovalDecision,
    ActionExecutionRequest,
    ActionExecutionResult,
    ExecutionStatus,
)
from medshield.schemas.verification import VerificationRequest, VerificationResult
from medshield.schemas.audit import AuditEvent, AgentError
from medshield.agents.evidence_analyst import EvidenceAnalystAgent
from medshield.agents.clinical_continuity import ClinicalContinuityAnalystAgent
from medshield.agents.response_coordinator import ResponseCoordinatorAgent
from medshield.agents.recovery_verifier import RecoveryVerifierAgent
from medshield.simulator.service import SyntheticHospitalSimulator


class IncidentCommanderAgent:
    """Orchestrates multi-agent hospital IT incident response and clinical continuity."""

    def __init__(
        self,
        simulator: SyntheticHospitalSimulator,
        evidence_analyst: EvidenceAnalystAgent,
        continuity_analyst: ClinicalContinuityAnalystAgent,
        response_coordinator: ResponseCoordinatorAgent,
        recovery_verifier: RecoveryVerifierAgent,
        db_session: Optional[Session] = None,
    ):
        self.simulator = simulator
        self.evidence_analyst = evidence_analyst
        self.continuity_analyst = continuity_analyst
        self.response_coordinator = response_coordinator
        self.recovery_verifier = recovery_verifier
        self.db = db_session

        self._active_incidents: Dict[str, IncidentStatus] = {}
        self._evidence_reports: Dict[str, EvidenceReport] = {}
        self._continuity_reports: Dict[str, ClinicalImpactReport] = {}
        self._pending_approvals: Dict[str, ApprovalRequest] = {}
        self._execution_results: Dict[str, ActionExecutionResult] = {}
        self._verification_results: Dict[str, VerificationResult] = {}

    def set_db_session(self, db_session: Session) -> None:
        self.db = db_session
        self.response_coordinator.set_db_session(db_session)

    def _audit(
        self,
        incident_id: str,
        correlation_id: str,
        event_type: str,
        actor: str,
        payload: Dict,
        prev_state: Optional[str] = None,
        new_state: Optional[str] = None,
    ) -> None:
        if self.db:
            event = AuditEvent(
                event_id=f"AUD-{uuid.uuid4().hex[:8]}",
                timestamp=datetime.now(timezone.utc),
                correlation_id=correlation_id,
                incident_id=incident_id,
                actor=actor,
                event_type=event_type,
                payload=payload,
                previous_state=prev_state,
                new_state=new_state,
            )
            AuditLogger.record_event(self.db, event)

    def _persist_incident(self, status: IncidentStatus) -> None:
        if not self.db:
            return
        db_inc = self.db.query(DBIncident).filter(DBIncident.incident_id == status.incident_id).first()
        history_json = json.dumps([h.model_dump(mode="json") for h in status.state_history])
        ev_json = self._evidence_reports[status.incident_id].model_dump_json() if status.incident_id in self._evidence_reports else None
        clin_json = self._continuity_reports[status.incident_id].model_dump_json() if status.incident_id in self._continuity_reports else None
        exec_json = self._execution_results[status.incident_id].model_dump_json() if status.incident_id in self._execution_results else None
        verif_json = self._verification_results[status.incident_id].model_dump_json() if status.incident_id in self._verification_results else None

        if not db_inc:
            db_inc = DBIncident(
                incident_id=status.incident_id,
                correlation_id=status.correlation_id,
                service_id=status.service_id,
                current_state=status.current_state.value,
                previous_state=status.previous_state.value if status.previous_state else None,
                severity="HIGH",
                title=f"Incident on {status.service_id}",
                description="Synthetic hospital service outage",
                proposed_action=status.proposed_action,
                approval_status=status.approval_status,
                escalation_reason=status.escalation_reason,
                state_history_json=history_json,
                evidence_report_json=ev_json,
                continuity_report_json=clin_json,
                execution_result_json=exec_json,
                verification_result_json=verif_json,
            )
            self.db.add(db_inc)
        else:
            db_inc.current_state = status.current_state.value
            db_inc.previous_state = status.previous_state.value if status.previous_state else None
            db_inc.proposed_action = status.proposed_action
            db_inc.approval_status = status.approval_status
            db_inc.escalation_reason = status.escalation_reason
            db_inc.state_history_json = history_json
            db_inc.evidence_report_json = ev_json
            db_inc.continuity_report_json = clin_json
            db_inc.execution_result_json = exec_json
            db_inc.verification_result_json = verif_json
            db_inc.updated_at = datetime.now(timezone.utc)

        self.db.commit()

    def start_incident(self, request: IncidentRequest) -> IncidentStatus:
        """Entry point for accepting a new incident."""
        status = IncidentStatus(
            incident_id=request.incident_id,
            correlation_id=request.correlation_id,
            service_id=request.service_id,
            current_state=IncidentState.INCIDENT_DETECTED,
            previous_state=IncidentState.NORMAL_MONITORING,
        )
        status.state_history.append(
            StateTransitionEvent(
                from_state=IncidentState.NORMAL_MONITORING,
                to_state=IncidentState.INCIDENT_DETECTED,
                reason=f"Incident ingested: {request.title}",
                actor="IncidentCommander",
            )
        )
        self._active_incidents[request.incident_id] = status
        self._audit(
            incident_id=request.incident_id,
            correlation_id=request.correlation_id,
            event_type="INCIDENT_STARTED",
            actor="IncidentCommander",
            payload=request.model_dump(mode="json"),
            prev_state=IncidentState.NORMAL_MONITORING.value,
            new_state=IncidentState.INCIDENT_DETECTED.value,
        )
        self._persist_incident(status)
        return status

    def investigate(self, incident_id: str) -> IncidentStatus:
        """Transition to INVESTIGATING, dispatch Evidence & Continuity analysts, propose action."""
        status = self._active_incidents.get(incident_id)
        if not status:
            raise KeyError(f"Incident {incident_id} not found in Commander registry")

        prev = status.current_state
        status.transition_to(IncidentState.INVESTIGATING, "Dispatched Evidence and Clinical analysts", "IncidentCommander")
        self._audit(
            incident_id=incident_id,
            correlation_id=status.correlation_id,
            event_type="STATE_TRANSITION",
            actor="IncidentCommander",
            payload={"transition": "INVESTIGATING"},
            prev_state=prev.value,
            new_state=status.current_state.value,
        )

        try:
            # 1. Dispatch Evidence Analyst
            ev_req = EvidenceRequest(
                incident_id=incident_id,
                correlation_id=status.correlation_id,
                service_id=status.service_id,
            )
            ev_report = self.evidence_analyst.analyze_incident(ev_req)
            self._evidence_reports[incident_id] = ev_report
            self._audit(
                incident_id=incident_id,
                correlation_id=status.correlation_id,
                event_type="EVIDENCE_REPORT_RECEIVED",
                actor="EvidenceAnalyst",
                payload={"likely_root_cause": ev_report.likely_root_cause, "confidence": ev_report.confidence_score},
            )

            # 2. Dispatch Clinical Continuity Analyst
            clin_req = ClinicalImpactRequest(
                incident_id=incident_id,
                correlation_id=status.correlation_id,
                service_id=status.service_id,
                root_cause_hint=ev_report.likely_root_cause,
            )
            clin_report = self.continuity_analyst.assess_impact(clin_req)
            self._continuity_reports[incident_id] = clin_report
            self._audit(
                incident_id=incident_id,
                correlation_id=status.correlation_id,
                event_type="CLINICAL_IMPACT_ASSESSED",
                actor="ClinicalContinuityAnalyst",
                payload={
                    "departments_impacted": [d.department_id for d in clin_report.affected_departments],
                    "escalation_required": clin_report.high_impact_escalation_required,
                },
            )

            # 3. Determine proposed action
            action_name = ev_report.recommended_action_type
            action_enum = AllowedRecoveryAction(action_name)
            status.proposed_action = action_name

            # 4. Formulate Approval Request
            clin_summary = (
                f"Affects {len(clin_report.affected_departments)} departments "
                f"({', '.join(d.department_id for d in clin_report.affected_departments)}). "
                f"Downtime procedures active: {len(clin_report.recommended_downtime_procedures)}."
            )
            app_req = self.response_coordinator.create_approval_request(
                incident_id=incident_id,
                correlation_id=status.correlation_id,
                proposed_action=action_enum,
                target_service=status.service_id,
                justification=ev_report.likely_root_cause,
                clinical_impact_summary=clin_summary,
            )
            self._pending_approvals[incident_id] = app_req

            # 5. Move to AWAITING_APPROVAL
            prev = status.current_state
            status.transition_to(IncidentState.AWAITING_APPROVAL, "Recovery plan proposed, awaiting human authorization", "IncidentCommander")
            status.approval_status = "PENDING_OPERATOR_DECISION"
            self._audit(
                incident_id=incident_id,
                correlation_id=status.correlation_id,
                event_type="APPROVAL_REQUESTED",
                actor="IncidentCommander",
                payload={"approval_id": app_req.approval_id, "action": action_name},
                prev_state=prev.value,
                new_state=status.current_state.value,
            )
            self._persist_incident(status)
            return status

        except Exception as e:
            # Safe escalation on unexpected specialist failure
            prev = status.current_state
            status.transition_to(IncidentState.ESCALATED, f"Specialist agent error: {str(e)}", "IncidentCommander")
            status.escalation_reason = str(e)
            self._audit(
                incident_id=incident_id,
                correlation_id=status.correlation_id,
                event_type="INCIDENT_ESCALATED",
                actor="IncidentCommander",
                payload={"error": str(e)},
                prev_state=prev.value,
                new_state=status.current_state.value,
            )
            self._persist_incident(status)
            return status

    def process_approval(self, incident_id: str, decision: ApprovalDecision) -> IncidentStatus:
        """Handle human operator authorization decision."""
        status = self._active_incidents.get(incident_id)
        if not status:
            raise KeyError(f"Incident {incident_id} not found in Commander registry")

        app_req = self._pending_approvals.get(incident_id)
        if not app_req:
            raise ValueError(f"No pending approval request found for incident {incident_id}")

        if not decision.approved:
            # Operator denied approval
            prev = status.current_state
            status.transition_to(IncidentState.ESCALATED, f"Operator denied authorization: {decision.operator_notes}", "HumanOperator")
            status.approval_status = "REJECTED"
            status.escalation_reason = decision.operator_notes
            self._audit(
                incident_id=incident_id,
                correlation_id=status.correlation_id,
                event_type="APPROVAL_REJECTED",
                actor=decision.operator_id,
                payload={"notes": decision.operator_notes},
                prev_state=prev.value,
                new_state=status.current_state.value,
            )
            self._persist_incident(status)
            return status

        # Operator granted approval: move to RECOVERY_IN_PROGRESS
        status.approval_status = "APPROVED"
        prev = status.current_state
        status.transition_to(IncidentState.RECOVERY_IN_PROGRESS, f"Operator approved {app_req.proposed_action.value}", decision.operator_id)
        self._audit(
            incident_id=incident_id,
            correlation_id=status.correlation_id,
            event_type="APPROVAL_GRANTED",
            actor=decision.operator_id,
            payload={"action": app_req.proposed_action.value},
            prev_state=prev.value,
            new_state=status.current_state.value,
        )

        # Execute recovery action via Response Coordinator
        exec_req = ActionExecutionRequest(
            execution_id=f"EXEC-{uuid.uuid4().hex[:8]}",
            incident_id=incident_id,
            correlation_id=status.correlation_id,
            action=app_req.proposed_action,
            target_service=status.service_id,
            approval_id=app_req.approval_id,
            approval_decision=decision,
            idempotency_key=f"idemp-{incident_id}-{uuid.uuid4().hex[:6]}",
        )
        exec_result = self.response_coordinator.execute_action(exec_req, approval_request=app_req)
        self._execution_results[incident_id] = exec_result
        self._audit(
            incident_id=incident_id,
            correlation_id=status.correlation_id,
            event_type="ACTION_EXECUTED",
            actor="ResponseCoordinator",
            payload={"status": exec_result.status.value, "output": exec_result.simulator_output},
        )

        if exec_result.status != ExecutionStatus.SUCCESS:
            prev = status.current_state
            status.transition_to(IncidentState.FAILED, f"Execution failed: {exec_result.error_message}", "ResponseCoordinator")
            self._persist_incident(status)
            return status

        # Move to VERIFYING
        prev = status.current_state
        status.transition_to(IncidentState.VERIFYING, "Action executed; dispatching Recovery Verifier", "IncidentCommander")
        self._persist_incident(status)

        # Dispatch Recovery Verifier (requires 3 consecutive successful checks)
        verif_req = VerificationRequest(
            incident_id=incident_id,
            correlation_id=status.correlation_id,
            target_service=status.service_id,
            required_consecutive_successes=3,
        )
        verif_result = self.recovery_verifier.verify_recovery(verif_req, max_probe_cycles=5)
        self._verification_results[incident_id] = verif_result
        self._audit(
            incident_id=incident_id,
            correlation_id=status.correlation_id,
            event_type="VERIFICATION_COMPLETED",
            actor="RecoveryVerifier",
            payload={"recovered": verif_result.verified_recovered, "status": verif_result.overall_status},
        )

        if verif_result.verified_recovered:
            prev = status.current_state
            status.transition_to(IncidentState.RECOVERED, "Verified 3 consecutive healthy health probes", "RecoveryVerifier")
        else:
            prev = status.current_state
            status.transition_to(IncidentState.ESCALATED, f"Verification failed: {verif_result.summary}", "RecoveryVerifier")
            status.escalation_reason = verif_result.summary

        self._persist_incident(status)
        return status

    def get_incident(self, incident_id: str) -> Optional[IncidentStatus]:
        if incident_id in self._active_incidents:
            return self._active_incidents[incident_id]
        if self.db:
            db_inc = self.db.query(DBIncident).filter(DBIncident.incident_id == incident_id).first()
            if db_inc:
                history = [StateTransitionEvent.model_validate(h) for h in json.loads(db_inc.state_history_json)]
                status = IncidentStatus(
                    incident_id=db_inc.incident_id,
                    correlation_id=db_inc.correlation_id,
                    service_id=db_inc.service_id,
                    current_state=IncidentState(db_inc.current_state),
                    previous_state=IncidentState(db_inc.previous_state) if db_inc.previous_state else None,
                    state_history=history,
                    proposed_action=db_inc.proposed_action,
                    approval_status=db_inc.approval_status,
                    escalation_reason=db_inc.escalation_reason,
                    created_at=db_inc.created_at,
                    updated_at=db_inc.updated_at,
                )
                self._active_incidents[incident_id] = status
                return status
        return None

    def list_incidents(self) -> List[IncidentStatus]:
        if self.db:
            db_incs = self.db.query(DBIncident).all()
            results = []
            for d in db_incs:
                inc = self.get_incident(d.incident_id)
                if inc:
                    results.append(inc)
            return results
        return list(self._active_incidents.values())

    def get_approval_request(self, incident_id: str) -> Optional[ApprovalRequest]:
        return self._pending_approvals.get(incident_id)

    def generate_incident_report(self, incident_id: str) -> Dict:
        """Produce final structured incident report."""
        status = self.get_incident(incident_id)
        if not status:
            return {"error": f"Incident {incident_id} not found"}

        ev = self._evidence_reports.get(incident_id)
        clin = self._continuity_reports.get(incident_id)
        exc = self._execution_results.get(incident_id)
        ver = self._verification_results.get(incident_id)

        return {
            "incident_id": status.incident_id,
            "correlation_id": status.correlation_id,
            "service_id": status.service_id,
            "final_state": status.current_state.value,
            "approval_status": status.approval_status,
            "evidence_analysis": {
                "likely_root_cause": ev.likely_root_cause if ev else "N/A",
                "confidence_score": ev.confidence_score if ev else 0.0,
                "confidence_level": ev.confidence_level.value if ev else "N/A",
                "distinction_summary": ev.distinction_summary if ev else "N/A",
                "observed_logs_count": len(ev.observed_facts) if ev else 0,
            },
            "clinical_continuity": {
                "departments_affected": [d.department_name for d in clin.affected_departments] if clin else [],
                "downtime_procedures": [f"{p.procedure_id}: {p.title}" for p in clin.recommended_downtime_procedures] if clin else [],
                "life_critical_escalation": clin.high_impact_escalation_required if clin else False,
            },
            "recovery_execution": {
                "action": exc.action.value if exc else "N/A",
                "status": exc.status.value if exc else "N/A",
                "output": exc.simulator_output if exc else "N/A",
            },
            "verification": {
                "verified_recovered": ver.verified_recovered if ver else False,
                "status": ver.overall_status if ver else "N/A",
                "summary": ver.summary if ver else "N/A",
            },
            "state_transition_history": [
                {
                    "from_state": s.from_state.value,
                    "to_state": s.to_state.value,
                    "reason": s.reason,
                    "actor": s.actor,
                    "timestamp": s.timestamp.isoformat(),
                }
                for s in status.state_history
            ],
            "report_generated_at": datetime.now(timezone.utc).isoformat(),
        }
