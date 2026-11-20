from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app.config import settings

def estimate_tokens(text: str) -> int:
    # Approximation for display/accounting when provider usage is unavailable.
    return max(1, len(text) // 4)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=4),
       retry=retry_if_exception_type(Exception), reraise=True)
def _open_stream(messages):
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    client = OpenAI(api_key=settings.openai_api_key)
    return client.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True}
    )

def stream_answer(messages):
    stream = _open_stream(messages)
    for chunk in stream:
        if getattr(chunk, "usage", None):
            yield {"type": "usage",
                   "input_tokens": chunk.usage.prompt_tokens,
                   "output_tokens": chunk.usage.completion_tokens}
        if chunk.choices:
            delta = chunk.choices[0].delta.content
            if delta:
                yield {"type": "delta", "content": delta}
