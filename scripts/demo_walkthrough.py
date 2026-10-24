"""MEDSHIELD AI — Automated End-to-End Demonstration Script.

Runs through the complete multi-agent hospital incident response lifecycle:
1. Simulator Failure Injection
2. Detection & Incident Initiation
3. Evidence Analysis (Observed Facts vs Hypotheses)
4. Clinical Continuity Assessment & Downtime Procedures
5. Chatbot Operations Inquiries (ACP compatible)
6. Operator Authorization Gate (Cryptographic HMAC validation)
7. Controlled Remediation Execution on Simulator
8. Independent 3-Probe Health Verification
9. Tamper-Proof Cryptographic Audit Verification
10. Institutional Sandbox Payment with Idempotency Protection
"""

import sys
from datetime import datetime, timezone

from medshield.db.session import init_db, SessionLocal, AuditLogger
from medshield.simulator.service import SyntheticHospitalSimulator
from medshield.simulator.scenarios import ScenarioType
from medshield.agents.evidence_analyst import EvidenceAnalystAgent
from medshield.agents.clinical_continuity import ClinicalContinuityAnalystAgent
from medshield.agents.response_coordinator import ResponseCoordinatorAgent
from medshield.agents.recovery_verifier import RecoveryVerifierAgent
from medshield.agents.incident_commander import IncidentCommanderAgent
from medshield.agents.chatbot import HospitalOperationsChatbot
from medshield.agents.payment_agent import PaymentAgent
from medshield.schemas.incident import IncidentRequest, IncidentSeverity
from medshield.schemas.actions import ApprovalDecision
from medshield.schemas.chatbot import ChatRequest, OperatorRole
from medshield.schemas.payment import (
    InvoiceRequest,
    PaymentApproval,
    PaymentExecutionRequest,
)


def run_demo():
    print("=" * 80)
    print("           MEDSHIELD AI — LIVE MULTI-AGENT DEMONSTRATION")
    print("=" * 80)

    # Setup database and components
    init_db()
    db = SessionLocal()
    sim = SyntheticHospitalSimulator()
    ev_agent = EvidenceAnalystAgent(sim)
    clin_agent = ClinicalContinuityAnalystAgent()
    coord_agent = ResponseCoordinatorAgent(sim, db)
    verif_agent = RecoveryVerifierAgent(sim)
    commander = IncidentCommanderAgent(sim, ev_agent, clin_agent, coord_agent, verif_agent, db)
    chatbot = HospitalOperationsChatbot(commander)
    payment = PaymentAgent(db)

    print("\n[STEP 1] INJECTING SIMULATED FAILURE SCENARIO")
    scenario = sim.inject_scenario(ScenarioType.EHR_APP_OUTAGE)
    print(f"  • Scenario:             {scenario.name}")
    print(f"  • Target Service:       {scenario.target_service}")
    print(f"  • Root Cause Symptom:   {scenario.root_cause_explanation}")
    print(f"  • Error Rate Telemetry: {scenario.telemetry_impact['error_rate_percent']}%")
    print(f"  • Latency Telemetry:    {scenario.telemetry_impact['latency_ms']} ms")

    print("\n[STEP 2] INGESTING INCIDENT INTO INCIDENT COMMANDER")
    inc_id = f"INC-DEMO-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    req = IncidentRequest(
        incident_id=inc_id,
        correlation_id=f"CORR-{inc_id}",
        service_id=scenario.target_service,
        title=scenario.name,
        description="Bedside clinician workstations reporting 503 HTTP errors",
        severity=IncidentSeverity.CRITICAL,
    )
    status = commander.start_incident(req)
    print(f"  • Incident ID:  {status.incident_id}")
    print(f"  • Current State: {status.current_state.value}")

    print("\n[STEP 3] DISPATCHING SPECIALIST INVESTIGATION")
    status = commander.investigate(inc_id)
    print(f"  • Updated State:     {status.current_state.value}")
    print(f"  • Proposed Action:   {status.proposed_action}")
    print(f"  • Approval Required: {status.approval_status}")

    # Evidence details
    report = commander.generate_incident_report(inc_id)
    ev = report["evidence_analysis"]
    print("\n[STEP 4] EVIDENCE ANALYST FINDINGS:")
    print(f"  • Likely Root Cause: {ev['likely_root_cause']}")
    print(f"  • Confidence Score:  {ev['confidence_score']:.1%} ({ev['confidence_level']})")
    print(f"  • Observed Logs:     {ev['observed_logs_count']} synthetic log events")
    print(f"  • Distinction:       {ev['distinction_summary']}")

    clin = report["clinical_continuity"]
    print("\n[STEP 5] CLINICAL CONTINUITY ASSESSMENT:")
    print(f"  • Impacted Departments:    {', '.join(clin['departments_affected'])}")
    print(f"  • Life-Critical Escalation:{' ACTIVE' if clin['life_critical_escalation'] else ' INACTIVE'}")
    print("  • Activated Downtime Protocols:")
    for proc in clin["downtime_procedures"]:
        print(f"    - {proc}")

    print("\n[STEP 6] HOSPITAL OPERATIONS CHATBOT Q&A (ACP SIMULATION)")
    chat_query = f"What recovery action is proposed for {inc_id}?"
    print(f"  [Operator Query]: \"{chat_query}\"")
    chat_resp = chatbot.handle_chat(
        ChatRequest(
            request_id="CHAT-DEMO-01",
            operator_id="CHIEF_MEDICAL_OFFICER",
            operator_role=OperatorRole.IT_OPERATOR,
            query=chat_query,
        )
    )
    print("  [Chatbot Response]:")
    for line in chat_resp.answer.splitlines()[:6]:
        print(f"    {line}")

    print("\n[STEP 7] OPERATOR AUTHORIZATION GATE")
    app_req = commander.get_approval_request(inc_id)
    print(f"  • Approval ID:       {app_req.approval_id}")
    print(f"  • Expiration (UTC):  {app_req.expires_at.isoformat()}")
    print(f"  • HMAC Token:        {app_req.approval_token[:16]}... (tamper-resistant)")

    decision = ApprovalDecision(
        approval_id=app_req.approval_id,
        incident_id=inc_id,
        approved=True,
        operator_id="DR_HOSPITAL_CIO",
        operator_notes="Restart approved for rapid clinical recovery during shift change",
        approval_token=app_req.approval_token,
    )
    print(f"  • Operator Decision: APPROVED by {decision.operator_id}")

    print("\n[STEP 8] EXECUTING RECOVERY & VERIFICATION")
    final_status = commander.process_approval(inc_id, decision)
    final_report = commander.generate_incident_report(inc_id)
    print(f"  • Execution Status:  {final_report['recovery_execution']['status']}")
    print(f"  • Final State:       {final_status.current_state.value}")
    ver = final_report["verification"]
    print(f"  • Verified Recovered:{ver['verified_recovered']}")
    print(f"  • Verifier Summary:  {ver['summary']}")

    print("\n[STEP 9] CRYPTOGRAPHIC AUDIT LOG INTEGRITY")
    is_valid = AuditLogger.verify_audit_chain(db)
    events = AuditLogger.get_events_for_incident(db, inc_id)
    print(f"  • Tamper-Proof Chain Valid: {is_valid}")
    print(f"  • Total Events Recorded:    {len(events)}")
    for ev in events[-3:]:
        print(f"    - [{ev.timestamp.strftime('%H:%M:%S')}] {ev.event_type} by {ev.actor} (Hash: {ev.hash_current[:10]}...)")

    print("\n[STEP 10] INSTITUTIONAL SANDBOX PAYMENT")
    inv = payment.create_invoice(
        InvoiceRequest(
            vendor_name="HealthGrid Emergency SLA Support Corp",
            service_description="High-Priority EHR Recovery Engineering Support",
            amount=4500.00,
            currency="USD",
            invoice_reference=f"INV-REF-{inc_id}",
        )
    )
    print(f"  • Created Invoice:  {inv.invoice_id} for ${inv.amount:,.2f} {inv.currency} (Sandbox={inv.sandbox_mode})")

    pay_approval = PaymentApproval(
        approval_id="APP-DEMO-PAY",
        invoice_id=inv.invoice_id,
        approved=True,
        approver_id="HOSPITAL_CFO",
        approver_role="CFO",
        notes="Approved emergency support invoice",
    )
    payment.approve_invoice(pay_approval)
    print("  • Invoice Approved by CFO")

    pay_result = payment.execute_payment(
        PaymentExecutionRequest(
            invoice_id=inv.invoice_id,
            approval=pay_approval,
            idempotency_key=f"idemp-demo-{inc_id}",
        ),
        simulation_mode="SUCCESS",
    )
    print(f"  • Payment Executed: Transaction ID = {pay_result.transaction_id}")
    print(f"  • Payment Status:   {pay_result.status.value}")
    print(f"  • Reconciliation:   {pay_result.reconciliation_notes}")

    print("\n" + "=" * 80)
    print("       DEMONSTRATION COMPLETED SUCCESSFULLY — ALL AGENTS VERIFIED")
    print("=" * 80)


if __name__ == "__main__":
    run_demo()
