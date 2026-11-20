from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import settings
from app.models import Message

def load_full_history(db: Session, session_id: str) -> list[Message]:
    """Fetch all persisted messages in chronological order for this session."""
    return list(db.scalars(select(Message).where(
        Message.session_id == session_id
    ).order_by(Message.created_at, Message.id)).all())

def sliding_window(history: list[Message]) -> list[Message]:
    """Trim only the LLM prompt; never delete older database history."""
    return history[-settings.max_history_messages:]
