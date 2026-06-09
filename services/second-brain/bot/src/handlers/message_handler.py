import logging
from aiogram import Router
from aiogram.types import Message

from src.config import settings
from src.services import classifier, storage

logger = logging.getLogger(__name__)
router = Router()


def _extract_content(message: Message) -> tuple[str | None, str | None, str | None]:
    """Returns (text, media_type, media_url)."""
    if message.sticker:
        return None, None, None

    text = message.text or message.caption or ""
    media_type = None
    media_url = None

    if message.photo:
        media_type = "photo"
        media_url = message.photo[-1].file_id
    elif message.video:
        media_type = "video"
        media_url = message.video.file_id
    elif message.document:
        media_type = "document"
        media_url = message.document.file_id
    elif message.voice:
        media_type = "voice"
        media_url = message.voice.file_id

    if not text and not media_url:
        return None, None, None

    return text or None, media_type, media_url


def _is_allowed(message: Message) -> bool:
    user_id = message.from_user.id if message.from_user else None
    chat_id = message.chat.id
    return user_id == settings.owner_user_id or chat_id in settings.telegram_group_ids


@router.message()
async def handle_message(message: Message) -> None:
    if not _is_allowed(message):
        return

    text, media_type, media_url = _extract_content(message)
    if not text and not media_url:
        return

    is_direct = message.from_user and message.from_user.id == settings.owner_user_id

    try:
        result = await classifier.classify(text or "", media_type)
        item_data = {
            "source_type": "telegram",
            "source_id": str(message.message_id),
            "source_chat": message.chat.id,
            "raw_text": text,
            "media_url": media_url,
            "media_type": media_type,
            "category": result["category"],
            "summary": result["summary"],
            "tags": result["tags"],
            "importance": result["importance"],
        }
        await storage.save_item(item_data)

        if is_direct and message.chat.type == "private":
            await message.reply(
                f"✅ Сохранено\n"
                f"📂 <b>{result['category']}</b>\n"
                f"{result['summary']}",
                parse_mode="HTML",
            )
    except Exception as exc:
        logger.error("Failed to process message %s: %s", message.message_id, exc)
        if is_direct and message.chat.type == "private":
            await message.reply("❌ Ошибка при сохранении. Попробуй ещё раз.")
