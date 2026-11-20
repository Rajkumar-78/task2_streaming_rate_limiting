from datetime import datetime
from pydantic import BaseModel, ConfigDict

class SessionCreated(BaseModel):
    id: str
    created_at: datetime

class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    session_id: str
    role: str
    content: str
    tokens: int
    created_at: datetime

class ChatRequest(BaseModel):
    message: str
