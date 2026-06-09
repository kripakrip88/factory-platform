from typing import Optional
"""
Импорт истории из экспорта Telegram Desktop (JSON).

Запуск:
    python3 import_tg_export.py <path_to_result.json> [<path_to_result2.json> ...]

Пример:
    python3 import_tg_export.py ~/Downloads/Завод/result.json ~/Downloads/Здоровье/result.json
"""
import asyncio
import json
import sys
import logging
import asyncpg
import anthropic

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Конфиг (вставь свои значения) ────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DB_DSN = os.environ.get("DB_DSN", "postgresql://brain_user:password@brain-db:5432/second_brain")
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Ты — личный ассистент для управления знаниями. Классифицируй входящий контент.
Верни JSON без markdown и пояснений:
{
  "category": "idea|health|article|inspiration|video|image|file|link|other",
  "summary": "1-2 предложения на русском языке",
  "tags": ["тег1", "тег2"],
  "importance": 1-5
}
Importance: 5=срочно важно, 3=интересно, 1=просто сохранить."""


def extract_text(msg: dict) -> str:
    text = msg.get("text", "")
    if isinstance(text, list):
        parts = []
        for part in text:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(part.get("text", ""))
        return "".join(parts).strip()
    return str(text).strip()


def extract_media_type(msg: dict) -> Optional[str]:
    mt = msg.get("media_type")
    if mt:
        return mt
    if msg.get("photo"):
        return "photo"
    if msg.get("file"):
        return "document"
    return None


async def classify(client: anthropic.AsyncAnthropic, text: str, media_type: Optional[str]) -> dict:
    content = text or ""
    if media_type:
        content = f"[{media_type}] {content}".strip()
    if not content:
        return {"category": "other", "summary": "", "tags": [], "importance": 1}
    try:
        response = await client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=256,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
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
            "summary": result.get("summary", content[:100]),
            "tags": result.get("tags", []),
            "importance": int(result.get("importance", 3)),
        }
    except Exception as e:
        logger.warning("Classify error: %s", e)
        return {"category": "other", "summary": content[:100], "tags": [], "importance": 2}


async def import_file(path: str, pool: asyncpg.Pool, client: anthropic.AsyncAnthropic) -> int:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    chat_name = data.get("name", path)
    messages = [m for m in data.get("messages", []) if m.get("type") == "message"]
    logger.info("Импорт '%s': %d сообщений", chat_name, len(messages))

    count = 0
    for i, msg in enumerate(messages):
        text = extract_text(msg)
        media_type = extract_media_type(msg)

        if not text and not media_type:
            continue

        # Проверяем дубликат
        exists = await pool.fetchval(
            "SELECT 1 FROM brain.items WHERE source_type='tg_export' AND source_id=$1",
            str(msg.get("id", ""))
        )
        if exists:
            continue

        result = await classify(client, text, media_type)

        await pool.execute(
            """
            INSERT INTO brain.items
                (source_type, source_id, raw_text, media_type,
                 category, summary, tags, importance)
            VALUES ('tg_export', $1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT DO NOTHING
            """,
            str(msg.get("id", "")),
            text or None,
            media_type,
            result["category"],
            result["summary"],
            result["tags"],
            result["importance"],
        )
        count += 1

        if count % 10 == 0:
            logger.info("  '%s': обработано %d/%d", chat_name, i + 1, len(messages))

    logger.info("  '%s': импортировано %d новых айтемов", chat_name, count)
    return count


async def main(paths: list[str]) -> None:
    pool = await asyncpg.create_pool(DB_DSN, min_size=2, max_size=5)
    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    total = 0
    for path in paths:
        total += await import_file(path, pool, client)

    await pool.close()
    logger.info("Готово. Всего импортировано: %d айтемов", total)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python3 import_tg_export.py <result.json> [<result2.json> ...]")
        sys.exit(1)
    asyncio.run(main(sys.argv[1:]))
