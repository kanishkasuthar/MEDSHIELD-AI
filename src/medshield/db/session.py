"""Database session management and audit repository."""

import json
from datetime import datetime, timezone
from typing import Generator, List, Optional
from sqlalchemy import create_engine, desc
from sqlalchemy.orm import sessionmaker, Session
from medshield.config import settings
from medshield.db.models import Base, DBAuditEvent
from medshield.schemas.audit import AuditEvent


def get_engine(database_url: Optional[str] = None):
    url = database_url or settings.database_url
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(url, connect_args=connect_args, echo=False)


engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db(target_engine=None) -> None:
    """Initialize all tables."""
    eng = target_engine or engine
    Base.metadata.create_all(bind=eng)


def get_db() -> Generator[Session, None, None]:
    """Dependency for yielding database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class AuditLogger:
    """Append-only audit logger with cryptographic hash chaining."""

    @staticmethod
    def record_event(db: Session, event: AuditEvent) -> DBAuditEvent:
        # Fetch the most recent event to obtain hash_prev
        last_event = (
            db.query(DBAuditEvent)
            .order_by(desc(DBAuditEvent.id))
            .first()
        )
        prev_hash = last_event.hash_current if last_event else "GENESIS_BLOCK_MEDSHIELD_2026"
        computed_hash = event.calculate_hash(prev_hash)

        db_event = DBAuditEvent(
            event_id=event.event_id,
            correlation_id=event.correlation_id,
            incident_id=event.incident_id,
            actor=event.actor,
            event_type=event.event_type,
            payload_json=json.dumps(event.payload, sort_keys=True),
            previous_state=event.previous_state,
            new_state=event.new_state,
            hash_prev=prev_hash,
            hash_current=computed_hash,
            timestamp=event.timestamp,
        )
        db.add(db_event)
        db.commit()
        db.refresh(db_event)
        return db_event

    @staticmethod
    def get_events_for_incident(db: Session, incident_id: str) -> List[DBAuditEvent]:
        return (
            db.query(DBAuditEvent)
            .filter(DBAuditEvent.incident_id == incident_id)
            .order_by(DBAuditEvent.id.asc())
            .all()
        )

    @staticmethod
    def verify_audit_chain(db: Session) -> bool:
        """Verify tamper-evidence across the entire audit log."""
        events = db.query(DBAuditEvent).order_by(DBAuditEvent.id.asc()).all()
        prev_hash = "GENESIS_BLOCK_MEDSHIELD_2026"
        for ev in events:
            if ev.hash_prev != prev_hash:
                return False
            ts = ev.timestamp if ev.timestamp.tzinfo else ev.timestamp.replace(tzinfo=timezone.utc)
            ts_str = ts.astimezone(timezone.utc).isoformat()
            data = {
                "event_id": ev.event_id,
                "timestamp": ts_str,
                "correlation_id": ev.correlation_id,
                "incident_id": ev.incident_id,
                "actor": ev.actor,
                "event_type": ev.event_type,
                "payload": json.loads(ev.payload_json),
                "previous_state": ev.previous_state,
                "new_state": ev.new_state,
                "hash_prev": ev.hash_prev,
            }
            import hashlib
            serialized = json.dumps(data, sort_keys=True)
            recalculated = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
            if recalculated != ev.hash_current:
                return False
            prev_hash = ev.hash_current
        return True
