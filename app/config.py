import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/chat_app"
    )
    api_key: str = os.getenv("CHAT_API_KEY", "change-me")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    max_history_messages: int = int(os.getenv("MAX_HISTORY_MESSAGES", "20"))
    cost_per_1k_input_tokens: float = float(os.getenv("COST_PER_1K_INPUT_TOKENS", "0.00015"))
    cost_per_1k_output_tokens: float = float(os.getenv("COST_PER_1K_OUTPUT_TOKENS", "0.0006"))
    rate_limit: int = int(os.getenv("RATE_LIMIT_PER_HOUR", "20"))

settings = Settings()
