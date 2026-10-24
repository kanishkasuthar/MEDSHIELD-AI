"""FastAPI Application providing REST endpoints and health checks for MEDSHIELD AI."""

from contextlib import asynccontextmanager
from typing import Dict, List, Optional
from fastapi import FastAPI, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from medshield.config import settings
from medshield.db.session import init_db, get_db, AuditLogger
from medshield.simulator.service import SyntheticHospitalSimulator
from medshield.simulator.scenarios import ScenarioType
from medshield.agents.evidence_analyst import EvidenceAnalystAgent
from medshield.agents.clinical_continuity import ClinicalContinuityAnalystAgent
from medshield.agents.response_coordinator import ResponseCoordinatorAgent
from medshield.agents.recovery_verifier import RecoveryVerifierAgent
from medshield.agents.incident_commander import IncidentCommanderAgent
from medshield.agents.chatbot import HospitalOperationsChatbot
from medshield.agents.payment_agent import PaymentAgent
from medshield.protocols.acp_adapter import ACPMessageAdapter

from medshield.schemas.incident import IncidentRequest, IncidentStatus
from medshield.schemas.actions import ApprovalDecision
from medshield.schemas.chatbot import ChatRequest, ChatResponse
from medshield.schemas.payment import (
    InvoiceRequest,
    InvoiceRecord,
    PaymentApproval,
    PaymentExecutionRequest,
    PaymentResult,
    PaymentStatus,
)


class SystemContainer:
    """Singleton holding initialized agents and shared components."""
    simulator: SyntheticHospitalSimulator
    commander: IncidentCommanderAgent
    chatbot: HospitalOperationsChatbot
    payment: PaymentAgent
    acp_adapter: ACPMessageAdapter

    def __init__(self):
        self.initialize()

    def initialize(self):
        init_db()
        self.simulator = SyntheticHospitalSimulator()
        evidence_agent = EvidenceAnalystAgent(self.simulator)
        continuity_agent = ClinicalContinuityAnalystAgent()
        coordinator_agent = ResponseCoordinatorAgent(self.simulator)
        verifier_agent = RecoveryVerifierAgent(self.simulator)

        self.commander = IncidentCommanderAgent(
            simulator=self.simulator,
            evidence_analyst=evidence_agent,
            continuity_analyst=continuity_agent,
            response_coordinator=coordinator_agent,
            recovery_verifier=verifier_agent,
        )
        self.chatbot = HospitalOperationsChatbot(self.commander)
        self.payment = PaymentAgent()
        self.acp_adapter = ACPMessageAdapter(
            chatbot=self.chatbot,
            commander=self.commander,
        )


container = SystemContainer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure initialized
    if not hasattr(container, "simulator") or container.simulator is None:
        container.initialize()
    yield
    # Shutdown logic if any


app = FastAPI(
    title="MEDSHIELD AI — API",
    description="Multi-Agent Hospital IT Incident Response & Clinical Continuity Platform",
    version="0.1.0",
    lifespan=lifespan,
)


# ------------------------------------------------------------------------------
# Health Check Endpoint
# ------------------------------------------------------------------------------
@app.get("/healthz", tags=["Health"])
def health_check(db: Session = Depends(get_db)):
    """Liveness and readiness health probe for cloud deployment."""
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    return {
        "status": "HEALTHY" if db_ok else "DEGRADED",
        "app_env": settings.app_env,
        "database_connected": db_ok,
        "agents": {
            "incident_commander": "ONLINE",
            "evidence_analyst": "ONLINE",
            "clinical_continuity_analyst": "ONLINE",
            "response_coordinator": "ONLINE",
            "recovery_verifier": "ONLINE",
            "hospital_operations_chatbot": "ONLINE",
            "payment_agent": "ONLINE",
        },
        "simulator_active": container.simulator is not None,
    }


# ------------------------------------------------------------------------------
# Simulator Scenario Injection Endpoint
# ------------------------------------------------------------------------------
class ScenarioInjectionRequest(BaseModel):
    scenario_type: ScenarioType


@app.post("/api/v1/simulator/scenario", tags=["Simulator"])
def inject_scenario(req: ScenarioInjectionRequest):
    """Trigger one of the 6 deterministic hospital failure scenarios."""
    scen = container.simulator.inject_scenario(req.scenario_type)
    return {
        "status": "SCENARIO_INJECTED",
        "scenario_id": scen.scenario_id.value,
        "name": scen.name,
        "target_service": scen.target_service,
        "description": scen.description,
        "required_recovery_action": scen.required_recovery_action.value,
    }


@app.post("/api/v1/simulator/reset", tags=["Simulator"])
def reset_simulator():
    """Reset simulator cluster to healthy baseline."""
    container.simulator.reset_to_clean_state()
    return {"status": "RESET_SUCCESS", "message": "All synthetic services restored to clean baseline."}


# ------------------------------------------------------------------------------
# Incident Management Endpoints
# ------------------------------------------------------------------------------
@app.post("/api/v1/incidents", response_model=IncidentStatus, tags=["Incidents"])
def create_incident(req: IncidentRequest, db: Session = Depends(get_db)):
    container.commander.set_db_session(db)
    return container.commander.start_incident(req)


@app.get("/api/v1/incidents", response_model=List[IncidentStatus], tags=["Incidents"])
def list_incidents(db: Session = Depends(get_db)):
    container.commander.set_db_session(db)
    return container.commander.list_incidents()


@app.get("/api/v1/incidents/{incident_id}", response_model=IncidentStatus, tags=["Incidents"])
def get_incident(incident_id: str, db: Session = Depends(get_db)):
    container.commander.set_db_session(db)
    inc = container.commander.get_incident(incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    return inc


@app.post("/api/v1/incidents/{incident_id}/investigate", response_model=IncidentStatus, tags=["Incidents"])
def investigate_incident(incident_id: str, db: Session = Depends(get_db)):
    container.commander.set_db_session(db)
    try:
        return container.commander.investigate(incident_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")


@app.post("/api/v1/incidents/{incident_id}/approval", response_model=IncidentStatus, tags=["Incidents"])
def submit_approval(incident_id: str, decision: ApprovalDecision, db: Session = Depends(get_db)):
    container.commander.set_db_session(db)
    try:
        return container.commander.process_approval(incident_id, decision)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/incidents/{incident_id}/report", tags=["Incidents"])
def get_incident_report(incident_id: str, db: Session = Depends(get_db)):
    container.commander.set_db_session(db)
    report = container.commander.generate_incident_report(incident_id)
    if "error" in report:
        raise HTTPException(status_code=404, detail=report["error"])
    return report


# ------------------------------------------------------------------------------
# Chatbot Endpoints
# ------------------------------------------------------------------------------
@app.post("/api/v1/chat", response_model=ChatResponse, tags=["Chatbot"])
def chat(req: ChatRequest, db: Session = Depends(get_db)):
    container.commander.set_db_session(db)
    return container.chatbot.handle_chat(req)


# ------------------------------------------------------------------------------
# Payment Agent Endpoints
# ------------------------------------------------------------------------------
@app.post("/api/v1/invoices", response_model=InvoiceRecord, tags=["Payments"])
def create_invoice(req: InvoiceRequest, db: Session = Depends(get_db)):
    container.payment.set_db_session(db)
    try:
        return container.payment.create_invoice(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/invoices/{invoice_id}", response_model=InvoiceRecord, tags=["Payments"])
def get_invoice(invoice_id: str, db: Session = Depends(get_db)):
    container.payment.set_db_session(db)
    inv = container.payment.get_invoice(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
    return inv


@app.post("/api/v1/invoices/{invoice_id}/approve", response_model=InvoiceRecord, tags=["Payments"])
def approve_invoice(invoice_id: str, approval: PaymentApproval, db: Session = Depends(get_db)):
    container.payment.set_db_session(db)
    try:
        return container.payment.approve_invoice(approval)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/payments", response_model=PaymentResult, tags=["Payments"])
def execute_payment(
    req: PaymentExecutionRequest,
    simulation_mode: str = Query("SUCCESS"),
    db: Session = Depends(get_db),
):
    container.payment.set_db_session(db)
    try:
        return container.payment.execute_payment(req, simulation_mode=simulation_mode)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Invoice {req.invoice_id} not found")


# ------------------------------------------------------------------------------
# Audit Endpoints
# ------------------------------------------------------------------------------
@app.get("/api/v1/audit/{incident_id}", tags=["Audit"])
def get_incident_audit(incident_id: str, db: Session = Depends(get_db)):
    events = AuditLogger.get_events_for_incident(db, incident_id)
    chain_valid = AuditLogger.verify_audit_chain(db)
    return {
        "incident_id": incident_id,
        "chain_tamper_verified": chain_valid,
        "event_count": len(events),
        "events": [
            {
                "event_id": e.event_id,
                "timestamp": e.timestamp.isoformat(),
                "actor": e.actor,
                "event_type": e.event_type,
                "previous_state": e.previous_state,
                "new_state": e.new_state,
                "hash_prev": e.hash_prev,
                "hash_current": e.hash_current,
            }
            for e in events
        ],
    }
