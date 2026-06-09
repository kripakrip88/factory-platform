import logging
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.config import settings
from src.services import classifier, storage
from src.keyboards import review_keyboard, main_menu, CATEGORY_EMOJI, CATEGORY_RU

logger = logging.getLogger(__name__)
router = Router()


def _extract_content(message: Message):
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


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    if not (message.from_user and message.from_user.id == settings.owner_user_id):
        return
    await message.answer(
        "👋 Привет! Я твой <b>Second Brain</b>.\n\n"
        "Отправляй мне всё что хочешь сохранить — идеи, ссылки, заметки о здоровье.\n"
        "Я классифицирую и сохраню с резюме от Claude.\n\n"
        "Используй меню внизу для навигации.",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


@router.message()
async def handle_message(message: Message) -> None:
    if not _is_allowed(message):
        return

    # Обработка кнопок главного меню
    if message.text in ("📬 Дайджест", "📊 Статистика", "📂 Категории", "🔍 Поиск"):
        from src.handlers.review_handler import (
            cmd_review_logic, cmd_stats_logic, cmd_categories_logic
        )
        if message.text == "📬 Дайджест":
            await cmd_review_logic(message)
        elif message.text == "📊 Статистика":
            await cmd_stats_logic(message)
        elif message.text == "📂 Категории":
            await cmd_categories_logic(message)
        elif message.text == "🔍 Поиск":
            await message.answer("Введи запрос:\n/search <текст>")
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
        item_id = await storage.save_item(item_data)

        if is_direct and message.chat.type == "private":
            emoji = CATEGORY_EMOJI.get(result["category"], "📌")
            cat_ru = CATEGORY_RU.get(result["category"], result["category"])
            tags_str = " ".join(f"#{t}" for t in result["tags"]) if result["tags"] else ""
            caption = (
                f"✅ <b>Сохранено</b>\n"
                f"{emoji} <b>{cat_ru}</b>  ⭐{result['importance']}/5\n\n"
                f"{result['summary']}\n"
                f"{tags_str}"
            ).strip()

            neighbours = await storage.get_neighbours(item_id)
            keyboard = review_keyboard(item_id, neighbours["prev"], neighbours["next"])
            await message.reply(caption, parse_mode="HTML", reply_markup=keyboard)

    except Exception as exc:
        logger.error("Failed to process message %s: %s", message.message_id, exc)
        if is_direct and message.chat.type == "private":
            await message.reply("❌ Ошибка при сохранении. Попробуй ещё раз.")
