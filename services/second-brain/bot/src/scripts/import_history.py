"""
Скрипт импорта истории Telegram-групп через Telethon (userbot).

Запуск:
    TELEGRAM_API_ID=xxx TELEGRAM_API_HASH=yyy python -m src.scripts.import_history

Требует переменных окружения:
    TELEGRAM_API_ID      — из my.telegram.org/apps
    TELEGRAM_API_HASH    — из my.telegram.org/apps
    TELEGRAM_GROUP_IDS   — из .env (уже заданы)
    Postgres + Anthropic — из .env
"""
import asyncio
import logging
import os

from telethon import TelegramClient
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

from src.config import settings
from src.services import storage, classifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _media_type(media) -> str | None:
    if isinstance(media, MessageMediaPhoto):
        return "photo"
    if isinstance(media, MessageMediaDocument):
        return "document"
    return None


async def _get_last_imported(chat_id: int) -> int:
    row = await storage._pool.fetchrow(
        "SELECT last_msg_id FROM brain.import_progress WHERE chat_id=$1", chat_id
    )
    return row["last_msg_id"] if row else 0


async def _update_progress(chat_id: int, last_msg_id: int) -> None:
    await storage._pool.execute(
        """
        INSERT INTO brain.import_progress (chat_id, last_msg_id)
        VALUES ($1, $2)
        ON CONFLICT (chat_id) DO UPDATE
            SET last_msg_id=$2, imported_at=NOW()
        """,
        chat_id,
        last_msg_id,
    )


async def import_group(client: TelegramClient, chat_id: int) -> None:
    last_id = await _get_last_imported(chat_id)
    logger.info("Group %s: importing from message_id > %s", chat_id, last_id)

    count = 0
    max_id = last_id

    async for msg in client.iter_messages(chat_id, min_id=last_id, reverse=True):
        text = msg.text or msg.message or ""
        media_type = _media_type(msg.media) if msg.media else None

        if not text and not media_type:
            continue

        result = await classifier.classify(text, media_type)
        await storage.save_item(
            {
                "source_type": "telegram",
                "source_id": str(msg.id),
                "source_chat": chat_id,
                "raw_text": text or None,
                "media_type": media_type,
                "category": result["category"],
                "summary": result["summary"],
                "tags": result["tags"],
                "importance": result["importance"],
            }
        )
        max_id = max(max_id, msg.id)
        count += 1
        if count % 50 == 0:
            logger.info("Group %s: processed %s messages…", chat_id, count)

    if max_id > last_id:
        await _update_progress(chat_id, max_id)
    logger.info("Group %s: done, %s messages imported.", chat_id, count)


async def main() -> None:
    api_id = int(os.environ["TELEGRAM_API_ID"])
    api_hash = os.environ["TELEGRAM_API_HASH"]

    await storage.init_pool(settings.asyncpg_dsn)

    async with TelegramClient("brain_import_session", api_id, api_hash) as client:
        for chat_id in settings.telegram_group_ids:
            try:
                await import_group(client, chat_id)
            except Exception as exc:
                logger.error("Failed to import group %s: %s", chat_id, exc)

    await storage.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
