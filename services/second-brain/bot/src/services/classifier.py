import base64
import json
import logging
import re
import httpx
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

OG_RE = re.compile(r'<meta[^>]+property=["\']og:(\w+)["\'][^>]+content=["\']([^"\']+)["\']', re.I)
TITLE_RE = re.compile(r'<title[^>]*>([^<]+)</title>', re.I)


def get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def fetch_og(url: str) -> str:
    """Возвращает краткое описание страницы по OG-тегам."""
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as c:
            resp = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
            html = resp.text[:20000]
        tags = dict(OG_RE.findall(html))
        title = tags.get("title") or (TITLE_RE.search(html) and TITLE_RE.search(html).group(1)) or ""
        desc = tags.get("description", "")
        parts = [p.strip() for p in [title, desc] if p.strip()]
        return " — ".join(parts) if parts else ""
    except Exception:
        return ""


async def download_tg_photo(file_id: str) -> bytes | None:
    """Скачивает фото из Telegram по file_id, возвращает байты."""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/getFile",
                params={"file_id": file_id},
            )
            data = r.json()
            if not data.get("ok"):
                return None
            file_path = data["result"]["file_path"]
            r2 = await c.get(
                f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{file_path}"
            )
            return r2.content
    except Exception as e:
        logger.warning("download_tg_photo error: %s", e)
        return None


async def classify(text: str, media_type: str | None = None, media_url: str | None = None, original_url: str | None = None) -> dict:
    user_content = []

    # Фото — используем Vision
    if media_type == "photo" and media_url:
        photo_bytes = await download_tg_photo(media_url)
        if photo_bytes:
            b64 = base64.standard_b64encode(photo_bytes).decode()
            user_content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
            })

    # URL превью
    og_text = ""
    if original_url:
        og_text = await fetch_og(original_url)

    # Текст
    text_parts = [p for p in [text, og_text] if p]
    if text_parts:
        user_content.append({"type": "text", "text": "\n".join(text_parts)})
    elif media_type and not user_content:
        user_content.append({"type": "text", "text": f"[{media_type}]"})

    if not user_content:
        return {**_DEFAULT, "summary": "Пустое сообщение"}

    try:
        response = await get_client().messages.create(
            model="claude-sonnet-4-5",
            max_tokens=256,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        result = json.loads(raw)
        return {
            "category": result.get("category", "other"),
            "summary": result.get("summary", (text or "")[:100]),
            "tags": result.get("tags", []),
            "importance": int(result.get("importance", 3)),
        }
    except Exception as exc:
        logger.warning("Claude classify error: %s", exc)
        fallback_text = text or og_text or (media_type or "")
        return {**_DEFAULT, "summary": fallback_text[:100]}
