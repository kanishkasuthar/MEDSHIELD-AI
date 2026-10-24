"""Agent 5 — Recovery Verifier.

Independently checks actual simulator health after recovery attempts.
Requires three consecutive successful health probes before declaring recovery.
Resets the consecutive-success count when any check fails.
Reports unavailable checks as UNKNOWN/UNVERIFIED, never as recovered.
Escalates persistent failures.
"""

from datetime import datetime, timezone
import time
from typing import List
from medshield.schemas.verification import (
    ProbeStatus,
    SingleHealthProbeResult,
    VerificationRequest,
    VerificationResult,
)
from medshield.simulator.service import SyntheticHospitalSimulator


class RecoveryVerifierAgent:
    """Verifies service health by conducting independent sequential probes."""

    def __init__(self, simulator: SyntheticHospitalSimulator):
        self.simulator = simulator

    def verify_recovery(
        self,
        request: VerificationRequest,
        max_probe_cycles: int = 5,
        sleep_between_probes: bool = False,
    ) -> VerificationResult:
        """Conduct independent health checks requiring 3 consecutive successes."""
        consecutive_success_count = 0
        probes_conducted: List[SingleHealthProbeResult] = []
        required_successes = request.required_consecutive_successes

        for probe_idx in range(1, max_probe_cycles + 1):
            if sleep_between_probes and request.interval_seconds > 0:
                time.sleep(request.interval_seconds)

            probe = self.simulator.probe_health(
                service_id=request.target_service,
                probe_index=probe_idx,
            )
            probes_conducted.append(probe)

            if probe.status == ProbeStatus.HEALTHY:
                consecutive_success_count += 1
                if consecutive_success_count >= required_successes:
                    summary = (
                        f"Independent verification succeeded: {consecutive_success_count} "
                        f"consecutive successful health probes observed on {request.target_service}."
                    )
                    return VerificationResult(
                        incident_id=request.incident_id,
                        target_service=request.target_service,
                        verified_recovered=True,
                        consecutive_success_count=consecutive_success_count,
                        probes_conducted=probes_conducted,
                        overall_status="RECOVERED",
                        summary=summary,
                        completed_at=datetime.now(timezone.utc),
                    )
            else:
                # Any non-healthy probe (UNHEALTHY, UNKNOWN, TIMEOUT) resets the counter!
                consecutive_success_count = 0

        # If loop finished without reaching required consecutive successes
        has_unknown = any(p.status in (ProbeStatus.UNKNOWN, ProbeStatus.UNVERIFIED) for p in probes_conducted)
        overall_status = "UNVERIFIED" if has_unknown else "FAILED_VERIFICATION"
        summary = (
            f"Independent verification failed: Achieved only {consecutive_success_count} / {required_successes} "
            f"consecutive successful health probes on {request.target_service}. Escalation required."
        )

        return VerificationResult(
            incident_id=request.incident_id,
            target_service=request.target_service,
            verified_recovered=False,
            consecutive_success_count=consecutive_success_count,
            probes_conducted=probes_conducted,
            overall_status=overall_status,
            summary=summary,
            completed_at=datetime.now(timezone.utc),
        )
