"""Agent 6 — Hospital Operations Chatbot.

Answers natural language questions using actual incident records and agent outputs.
Validates operator authorization, handles missing information, distinguishes simulated data,
and routes questions to actual shared incident state.
"""

from datetime import datetime, timezone
import re
import uuid
from typing import List, Optional
from medshield.schemas.chatbot import (
    ChatRequest,
    ChatResponse,
    OperatorRole,
)
from medshield.schemas.incident import IncidentState
from medshield.agents.incident_commander import IncidentCommanderAgent


class HospitalOperationsChatbot:
    """Natural language interface for authorized hospital operations personnel."""

    def __init__(self, commander: IncidentCommanderAgent):
        self.commander = commander

    def handle_chat(self, request: ChatRequest) -> ChatResponse:
        response_id = f"CHAT-{uuid.uuid4().hex[:8]}"

        # 1. Authorization Check
        if request.operator_role == OperatorRole.UNAUTHORIZED_GUEST:
            return ChatResponse(
                response_id=response_id,
                request_id=request.request_id,
                answer="Access Denied: The requested incident data requires authorized IT or Clinical credentials.",
                authorized=False,
                data_sources=[],
            )

        q = request.query.strip().lower()

        # Extract incident ID if present in query, e.g. "INC-20261024-001" or "INC-..."
        inc_match = re.search(r"\b(inc-[a-zA-Z0-9\-_]+)\b", q, re.IGNORECASE)
        target_incident_id = inc_match.group(1).upper() if inc_match else request.active_incident_id

        # 2. Intent: List / Active incidents
        if any(keyword in q for keyword in ["what incidents", "active incident", "list incident", "current incident", "show incident"]):
            incidents = self.commander.list_incidents()
            if not incidents:
                ans = "There are currently no active incidents detected in the hospital IT monitoring cluster."
            else:
                lines = [f"- Incident **{inc.incident_id}** on `{inc.service_id}`: State = **{inc.current_state.value}**, Approval = {inc.approval_status or 'N/A'}" for inc in incidents]
                ans = "Current hospital IT incidents:\n" + "\n".join(lines)
            return ChatResponse(
                response_id=response_id,
                request_id=request.request_id,
                answer=ans,
                referenced_incident_id=None,
                data_sources=["IncidentCommander.list_incidents()"],
            )

        # 3. Intent: System capabilities / Help
        if any(keyword in q for keyword in ["capability", "capabilities", "what can you do", "help", "who are you"]):
            ans = (
                "MEDSHIELD AI Operations Chatbot Capabilities:\n"
                "- **Incident Status**: Inquire about live or past hospital IT service disruptions.\n"
                "- **Evidence Analysis**: Review synthetic logs, root-cause hypotheses, and confidence scores from Evidence Analyst.\n"
                "- **Clinical Continuity**: Review impacted hospital departments (ED, ICU, OR), workflows (eMAR, CPOE), and versioned downtime procedures.\n"
                "- **Recovery & Approvals**: Inspect proposed recovery actions and pending human operator approval tokens.\n"
                "- **Verification**: Review independent 3-probe health verification results.\n"
                "- **Audit Trail**: Inspect append-only cryptographic event history."
            )
            return ChatResponse(
                response_id=response_id,
                request_id=request.request_id,
                answer=ans,
                data_sources=["SystemDocumentation"],
            )

        # For specific incident queries, target_incident_id is required
        if not target_incident_id:
            return ChatResponse(
                response_id=response_id,
                request_id=request.request_id,
                answer="Please specify the Incident ID (e.g. INC-001 or INC-E2E-001) you would like to inspect.",
                missing_info_needed="incident_id",
                data_sources=[],
            )

        # Retrieve incident
        status = self.commander.get_incident(target_incident_id)
        if not status:
            return ChatResponse(
                response_id=response_id,
                request_id=request.request_id,
                answer=f"Incident '{target_incident_id}' was not found in the hospital incident records.",
                referenced_incident_id=target_incident_id,
                data_sources=["IncidentCommander.get_incident()"],
            )

        report = self.commander.generate_incident_report(target_incident_id)

        # 4. Intent: Evidence / Root Cause
        if any(k in q for k in ["evidence", "root cause", "likely cause", "why did it fail", "logs"]):
            ev = report.get("evidence_analysis", {})
            ans = (
                f"Evidence Analysis for Incident **{target_incident_id}** (`{status.service_id}`):\n"
                f"- **Likely Root Cause**: {ev.get('likely_root_cause')}\n"
                f"- **Confidence**: {ev.get('confidence_score', 0):.0%} ({ev.get('confidence_level')})\n"
                f"- **Observed Facts**: {ev.get('observed_logs_count', 0)} real synthetic log records analyzed.\n"
                f"- **Distinction**: {ev.get('distinction_summary')}"
            )
            return ChatResponse(
                response_id=response_id,
                request_id=request.request_id,
                answer=ans,
                referenced_incident_id=target_incident_id,
                data_sources=["EvidenceAnalyst.analyze_incident()"],
            )

        # 5. Intent: Clinical Continuity / Impact
        if any(k in q for k in ["clinical", "workflow", "department", "downtime", "mitigation", "patient"]):
            clin = report.get("clinical_continuity", {})
            depts = clin.get("departments_affected", [])
            procs = clin.get("downtime_procedures", [])
            escalate = clin.get("life_critical_escalation", False)
            ans = (
                f"Clinical Continuity Assessment for Incident **{target_incident_id}**:\n"
                f"- **Affected Departments**: {', '.join(depts) if depts else 'None'}\n"
                f"- **Life-Critical Escalation Active**: {'YES (Emergency workflows affected)' if escalate else 'NO'}\n"
                f"- **Recommended Downtime Procedures**:\n" +
                ("\n".join(f"  • {p}" for p in procs) if procs else "  • Standard monitoring")
            )
            return ChatResponse(
                response_id=response_id,
                request_id=request.request_id,
                answer=ans,
                referenced_incident_id=target_incident_id,
                data_sources=["ClinicalContinuityAnalyst.assess_impact()"],
            )

        # 6. Intent: Recovery proposed / Approval pending
        if any(k in q for k in ["action", "proposed", "approval", "pending", "operator approval"]):
            app_req = self.commander.get_approval_request(target_incident_id)
            ans = (
                f"Recovery & Approval Status for Incident **{target_incident_id}**:\n"
                f"- **Current State**: {status.current_state.value}\n"
                f"- **Proposed Action**: {status.proposed_action or 'None'}\n"
                f"- **Approval Status**: {status.approval_status or 'None'}\n"
            )
            if app_req:
                ans += (
                    f"- **Approval ID**: `{app_req.approval_id}`\n"
                    f"- **Target Service**: `{app_req.target_service}`\n"
                    f"- **Expires At (UTC)**: {app_req.expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                    f"- **Justification**: {app_req.justification}\n"
                    f"- **Human Authorization Pending**: {'YES' if status.current_state == IncidentState.AWAITING_APPROVAL else 'NO'}"
                )
            return ChatResponse(
                response_id=response_id,
                request_id=request.request_id,
                answer=ans,
                referenced_incident_id=target_incident_id,
                data_sources=["ResponseCoordinator", "IncidentCommander"],
            )

        # 7. Intent: Verification / Did recovery succeed
        if any(k in q for k in ["verify", "verification", "did recovery succeed", "succeed", "recovered"]):
            ver = report.get("verification", {})
            recovered = ver.get("verified_recovered", False)
            ans = (
                f"Recovery Verification for Incident **{target_incident_id}**:\n"
                f"- **State**: {status.current_state.value}\n"
                f"- **Verified Recovered**: {'YES (Passed 3 consecutive independent probes)' if recovered else 'NO'}\n"
                f"- **Verification Summary**: {ver.get('summary')}"
            )
            return ChatResponse(
                response_id=response_id,
                request_id=request.request_id,
                answer=ans,
                referenced_incident_id=target_incident_id,
                data_sources=["RecoveryVerifier.verify_recovery()"],
            )

        # 8. Intent: Escalation reason
        if any(k in q for k in ["escalated", "escalation", "why was it escalated"]):
            ans = (
                f"Incident **{target_incident_id}** Status: {status.current_state.value}\n"
                f"- **Escalation Reason**: {status.escalation_reason or 'No escalation recorded for this incident.'}"
            )
            return ChatResponse(
                response_id=response_id,
                request_id=request.request_id,
                answer=ans,
                referenced_incident_id=target_incident_id,
                data_sources=["IncidentCommander"],
            )

        # 9. Intent: Audit history / What happened
        if any(k in q for k in ["audit", "history", "what happened", "events", "timeline"]):
            history = report.get("state_transition_history", [])
            lines = [f"- [{h['timestamp'][:19]}] **{h['from_state']}** ➔ **{h['to_state']}** by {h['actor']}: {h['reason']}" for h in history]
            ans = f"Audit & Transition History for Incident **{target_incident_id}**:\n" + "\n".join(lines)
            return ChatResponse(
                response_id=response_id,
                request_id=request.request_id,
                answer=ans,
                referenced_incident_id=target_incident_id,
                data_sources=["DBAuditEvent", "IncidentCommander.state_history"],
            )

        # Default fallback
        ans = (
            f"Incident **{target_incident_id}** (`{status.service_id}`):\n"
            f"- State: **{status.current_state.value}**\n"
            f"- Proposed Action: {status.proposed_action or 'N/A'}\n"
            f"- Approval: {status.approval_status or 'N/A'}\n"
            f"You can ask about evidence, clinical workflows, downtime procedures, verification, or audit history."
        )
        return ChatResponse(
            response_id=response_id,
            request_id=request.request_id,
            answer=ans,
            referenced_incident_id=target_incident_id,
            data_sources=["IncidentCommander"],
        )
