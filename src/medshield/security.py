"""Security utilities for HMAC token generation, verification, and tamper protection."""

import hmac
import hashlib
from datetime import datetime, timezone
from typing import Tuple
from medshield.config import settings


def generate_approval_token(
    incident_id: str,
    action: str,
    target_service: str,
    expires_at: datetime,
    secret: str = None
) -> str:
    """Generate an HMAC-SHA256 signature binding the approval to the incident and action."""
    key = (secret or settings.approval_signing_secret).encode("utf-8")
    payload = f"{incident_id}:{action}:{target_service}:{expires_at.isoformat()}".encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def verify_approval_token(
    token: str,
    incident_id: str,
    action: str,
    target_service: str,
    expires_at: datetime,
    secret: str = None
) -> Tuple[bool, str]:
    """Verify approval token validity and check whether it has expired."""
    now = datetime.now(timezone.utc)
    # Ensure timezone awareness
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if now > expires_at:
        return False, "Approval token has expired"

    expected = generate_approval_token(incident_id, action, target_service, expires_at, secret)
    if not hmac.compare_digest(token, expected):
        return False, "Invalid approval token signature"

    return True, "Token valid"
