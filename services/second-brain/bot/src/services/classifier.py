import json
import logging
from anthropic import AsyncAnthropic
from src.config import settings

logger = logging.getLogger(__name__)

_client: AsyncAnthropic | None = None

SYSTEM_PROMPT = """Ты — личный ассистент для управления знаниями. Классифицируй входящий контент.
Верни JSON без markdown и пояснений:
{
  "category": "idea|health|article|inspiration|video|image|file|link|other",
  "summary": "1-2 предложения на русском языке",
  "tags": ["тег1", "тег2"],
  "importance": 1-5
}
Importance: 5=срочно важно, 3=интересно, 1=просто сохранить."""

_DEFAULT = {"category": "other", "tags": [], "importance": 2}


def get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def classify(text: str, media_type: str | None = None) -> dict:
    content = text or ""
    if media_type:
        content = f"[{media_type}] {content}".strip()

    if not content:
        return {**_DEFAULT, "summary": "Пустое сообщение"}

    try:
        response = await get_client().messages.create(
            model="claude-sonnet-4-5",
            max_tokens=256,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
        raw = response.content[0].text.strip()
        result = json.loads(raw)
        return {
            "category": result.get("category", "other"),
            "summary": result.get("summary", content[:100]),
            "tags": result.get("tags", []),
            "importance": int(result.get("importance", 3)),
        }
    except Exception as exc:
        logger.warning("Claude classify error: %s", exc)
        return {**_DEFAULT, "summary": content[:100]}
