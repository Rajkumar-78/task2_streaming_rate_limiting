import uuid, hashlib, json
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from app.auth import require_api_key
from app.config import settings
from app.database import get_db
from app.models import ChatSession, Message, APIKeyUsage
from app.schemas import SessionCreated, MessageOut, ChatRequest
from app.llm import stream_answer, estimate_tokens
from app.history import load_full_history, sliding_window

router = APIRouter(dependencies=[Depends(require_api_key)])

@router.post("/sessions", response_model=SessionCreated, status_code=status.HTTP_201_CREATED)
def create_session(db: Session = Depends(get_db)):
    session = ChatSession(id=str(uuid.uuid4()))
    db.add(session); db.commit(); db.refresh(session)
    return session

@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
def get_messages(session_id: str, db: Session = Depends(get_db)):
    if not db.get(ChatSession, session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return list(db.scalars(select(Message).where(
        Message.session_id == session_id
    ).order_by(Message.created_at, Message.id)).all())

@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, db: Session = Depends(get_db)):
    session = db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    db.delete(session); db.commit()
    return {"detail": "Session deleted"}

def enforce_rate_limit(db: Session, api_key: str):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=1)
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    count = db.scalar(select(func.count(APIKeyUsage.id)).where(
        APIKeyUsage.api_key_hash == key_hash,
        APIKeyUsage.created_at >= cutoff
    )) or 0
    if count >= settings.rate_limit:
        oldest = db.scalar(select(func.min(APIKeyUsage.created_at)).where(
            APIKeyUsage.api_key_hash == key_hash,
            APIKeyUsage.created_at >= cutoff
        ))
        retry_after = max(1, int((oldest + timedelta(hours=1) - now).total_seconds())) if oldest else 3600
        raise HTTPException(status_code=429, detail="Rate limit exceeded",
                            headers={"Retry-After": str(retry_after)})
    db.add(APIKeyUsage(api_key_hash=key_hash))
    db.commit()

@router.post("/sessions/{session_id}/chat")
def chat(session_id: str, body: ChatRequest, api_key: str = Depends(require_api_key),
         db: Session = Depends(get_db)):
    session = db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    enforce_rate_limit(db, api_key)
    user_msg = Message(session_id=session_id, role="user", content=body.message,
                       tokens=estimate_tokens(body.message))
    db.add(user_msg); db.commit()

    # Load the complete persisted conversation on every model request, then trim
    # only the prompt sent to the model using the configured sliding window.
    full_history = load_full_history(db, session_id)
    prompt_history = sliding_window(full_history)
    messages = [{"role": m.role, "content": m.content} for m in prompt_history]

    def generate():
        answer_parts = []
        input_tokens = sum(m.tokens for m in prompt_history)
        output_tokens = 0
        try:
            for item in stream_answer(messages):
                if item["type"] == "delta":
                    answer_parts.append(item["content"])
                    yield "data: " + json.dumps({"content": item["content"]}) + "\n\n"
                elif item["type"] == "usage":
                    input_tokens = item.get("input_tokens", input_tokens)
                    output_tokens = item.get("output_tokens", output_tokens)
            answer = "".join(answer_parts)
            if not output_tokens:
                output_tokens = estimate_tokens(answer)
            cost = (input_tokens / 1000 * settings.cost_per_1k_input_tokens +
                    output_tokens / 1000 * settings.cost_per_1k_output_tokens)
            # Persist final assistant response and update per-session totals.
            db.add(Message(session_id=session_id, role="assistant", content=answer,
                           tokens=output_tokens))
            current = db.get(ChatSession, session_id)
            current.total_tokens += input_tokens + output_tokens
            current.total_cost += cost
            db.commit()
            yield "data: " + json.dumps({"done": True, "input_tokens": input_tokens,
                                         "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens,
                                         "cost": round(cost, 8)}) + "\n\n"
        except Exception:
            db.rollback()
            yield "data: " + json.dumps({"error": "Sorry, the AI service is temporarily unavailable. Please try again."}) + "\n\n"
        finally:
            db.close()
    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@router.get("/usage")
def get_usage(api_key: str = Depends(require_api_key), db: Session = Depends(get_db)):
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    messages_last_hour = db.scalar(select(func.count(APIKeyUsage.id)).where(
        APIKeyUsage.api_key_hash == key_hash, APIKeyUsage.created_at >= since
    )) or 0
    return {"messages_last_hour": messages_last_hour, "limit_per_hour": settings.rate_limit,
            "remaining": max(0, settings.rate_limit - messages_last_hour)}
