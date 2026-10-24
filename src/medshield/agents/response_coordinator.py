"""Agent 4 — Response Coordinator.

Maintains an explicit allowlist of simulator-only recovery actions.
Validates action parameters, incident binding, authorization, expiry, and replay protection.
Executes only approved actions against the controlled simulator. Never runs shell commands.
"""

from datetime import datetime, timedelta, timezone
import uuid
from typing import Dict, Optional, Set
from sqlalchemy.orm import Session
from medshield.config import settings
from medshield.db.models import DBActionExecution
from medshield.schemas.actions import (
    AllowedRecoveryAction,
    ApprovalRequest,
    ApprovalDecision,
    ActionExecutionRequest,
    ActionExecutionResult,
    ExecutionStatus,
)
from medshield.security import generate_approval_token, verify_approval_token
from medshield.simulator.service import SyntheticHospitalSimulator


class ResponseCoordinatorAgent:
    """Coordinates and executes explicitly authorized recovery actions against the simulator."""

    def __init__(self, simulator: SyntheticHospitalSimulator, db_session: Optional[Session] = None):
        self.simulator = simulator
        self.db = db_session
        self._executed_idempotency_keys: Set[str] = set()

    def set_db_session(self, db_session: Session) -> None:
        self.db = db_session

    def create_approval_request(
        self,
        incident_id: str,
        correlation_id: str,
        proposed_action: AllowedRecoveryAction,
        target_service: str,
        justification: str,
        clinical_impact_summary: str,
        action_parameters: Optional[Dict] = None,
        expiry_seconds: Optional[int] = None,
    ) -> ApprovalRequest:
        """Create a cryptographically signed human operator approval request."""
        approval_id = f"APP-{uuid.uuid4().hex[:8]}"
        duration = expiry_seconds if expiry_seconds is not None else settings.approval_expiry_seconds
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=duration)

        token = generate_approval_token(
            incident_id=incident_id,
            action=proposed_action.value,
            target_service=target_service,
            expires_at=expires_at,
        )

        return ApprovalRequest(
            approval_id=approval_id,
            incident_id=incident_id,
            correlation_id=correlation_id,
            proposed_action=proposed_action,
            target_service=target_service,
            action_parameters=action_parameters or {},
            justification=justification,
            clinical_impact_summary=clinical_impact_summary,
            expires_at=expires_at,
            approval_token=token,
        )

    def execute_action(
        self,
        request: ActionExecutionRequest,
        approval_request: Optional[ApprovalRequest] = None,
    ) -> ActionExecutionResult:
        """Validate approval, token signature, expiry, and replay protection before executing."""
        execution_id = request.execution_id or f"EXEC-{uuid.uuid4().hex[:8]}"

        # 1. Replay / idempotency check
        if request.idempotency_key in self._executed_idempotency_keys:
            return ActionExecutionResult(
                execution_id=execution_id,
                incident_id=request.incident_id,
                action=request.action,
                target_service=request.target_service,
                status=ExecutionStatus.REPLAY_DETECTED,
                simulator_output="",
                error_message=f"Duplicate execution blocked: idempotency key '{request.idempotency_key}' already used",
            )

        if self.db:
            existing = (
                self.db.query(DBActionExecution)
                .filter(DBActionExecution.idempotency_key == request.idempotency_key)
                .first()
            )
            if existing:
                self._executed_idempotency_keys.add(request.idempotency_key)
                return ActionExecutionResult(
                    execution_id=execution_id,
                    incident_id=request.incident_id,
                    action=request.action,
                    target_service=request.target_service,
                    status=ExecutionStatus.REPLAY_DETECTED,
                    simulator_output="",
                    error_message=f"Duplicate execution blocked: idempotency key '{request.idempotency_key}' already in DB",
                )

        # 2. Verify explicit operator approval
        decision: ApprovalDecision = request.approval_decision
        if not decision.approved:
            return ActionExecutionResult(
                execution_id=execution_id,
                incident_id=request.incident_id,
                action=request.action,
                target_service=request.target_service,
                status=ExecutionStatus.REJECTED,
                simulator_output="",
                error_message=f"Execution blocked: Operator {decision.operator_id} rejected authorization: {decision.operator_notes}",
            )

        # 3. Verify incident binding
        if decision.incident_id != request.incident_id:
            return ActionExecutionResult(
                execution_id=execution_id,
                incident_id=request.incident_id,
                action=request.action,
                target_service=request.target_service,
                status=ExecutionStatus.INVALID_TOKEN,
                simulator_output="",
                error_message=f"Incident mismatch: Decision is bound to {decision.incident_id}, requested {request.incident_id}",
            )

        # 4. Verify token cryptographic signature and expiration
        if approval_request:
            token_valid, reason = verify_approval_token(
                token=decision.approval_token,
                incident_id=request.incident_id,
                action=request.action.value,
                target_service=request.target_service,
                expires_at=approval_request.expires_at,
            )
            if not token_valid:
                status = ExecutionStatus.EXPIRED if "expired" in reason.lower() else ExecutionStatus.INVALID_TOKEN
                return ActionExecutionResult(
                    execution_id=execution_id,
                    incident_id=request.incident_id,
                    action=request.action,
                    target_service=request.target_service,
                    status=status,
                    simulator_output="",
                    error_message=f"Security check failed: {reason}",
                )

        # 5. Execute action strictly against Synthetic Hospital Simulator
        sim_result = self.simulator.execute_recovery_action(
            action=request.action,
            target_service=request.target_service,
            parameters=request.parameters,
            incident_id=request.incident_id,
        )

        # 6. Mark idempotency key as consumed
        self._executed_idempotency_keys.add(request.idempotency_key)

        # 7. Persist execution record
        if self.db:
            db_record = DBActionExecution(
                execution_id=execution_id,
                incident_id=request.incident_id,
                action=request.action.value,
                target_service=request.target_service,
                idempotency_key=request.idempotency_key,
                status=sim_result.status.value,
                simulator_output=sim_result.simulator_output,
                error_message=sim_result.error_message,
                executed_at=datetime.now(timezone.utc),
            )
            self.db.add(db_record)
            self.db.commit()

        return sim_result
