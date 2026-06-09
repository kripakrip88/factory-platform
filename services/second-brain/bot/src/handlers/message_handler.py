import asyncio
import logging
import re
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

URL_RE = re.compile(r'https?://[^\s<>"\']+')


def _find_url(text: str) -> str | None:
    m = URL_RE.search(text or "")
    return m.group(0) if m else None

from src.config import settings
from src.services import classifier, storage
from src.keyboards import review_keyboard, main_menu, CATEGORY_EMOJI, CATEGORY_RU

logger = logging.getLogger(__name__)
router = Router()

# Буфер для группировки альбомов: media_group_id -> список сообщений
_album_buffer: dict[str, list] = {}
_album_tasks: dict[str, asyncio.Task] = {}


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


async def _process_and_reply(message: Message, text, media_type, media_url, album_count=1):
    """Классифицирует, сохраняет и отвечает карточкой."""
    logger.info("Processing: media_type=%s, has_media_url=%s, text_len=%s", media_type, bool(media_url), len(text or ""))
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
            "original_url": _find_url(text),
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
            album_note = f" <i>({album_count} фото)</i>" if album_count > 1 else ""
            caption = (
                f"✅ <b>Сохранено</b>{album_note}\n"
                f"{emoji} <b>{cat_ru}</b>  ⭐{result['importance']}/5\n\n"
                f"{result['summary']}\n"
                f"{tags_str}"
            ).strip()

            neighbours = await storage.get_neighbours(item_id)
            url = _find_url(text)
            keyboard = review_keyboard(item_id, neighbours["prev"], neighbours["next"], url=url)
            await message.reply(caption, parse_mode="HTML", reply_markup=keyboard)

    except Exception as exc:
        logger.error("Failed to process message %s: %s", message.message_id, exc)
        if is_direct and message.chat.type == "private":
            await message.reply("❌ Ошибка при сохранении. Попробуй ещё раз.")


async def _flush_album(group_id: str, trigger_message: Message):
    """Ждёт 0.5с и обрабатывает весь альбом как один айтем."""
    await asyncio.sleep(0.5)
    messages = _album_buffer.pop(group_id, [])
    _album_tasks.pop(group_id, None)
    if not messages:
        return

    # Берём текст из caption первого сообщения с подписью
    text = next((m.caption for m in messages if m.caption), None)
    media_url = None
    for m in messages:
        if m.photo:
            media_url = m.photo[-1].file_id
            break

    await _process_and_reply(trigger_message, text, "photo", media_url, album_count=len(messages))


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
    logger.info("Incoming: chat=%s type=%s has_photo=%s has_text=%s", message.chat.id, message.chat.type, bool(message.photo), bool(message.text))
    if not _is_allowed(message):
        logger.info("Rejected: not allowed user=%s chat=%s", getattr(message.from_user, 'id', None), message.chat.id)
        return

    # Кнопки главного меню
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

    # Альбом (несколько фото в одном посте)
    if message.media_group_id:
        group_id = message.media_group_id
        _album_buffer.setdefault(group_id, []).append(message)
        if group_id not in _album_tasks:
            task = asyncio.create_task(_flush_album(group_id, message))
            _album_tasks[group_id] = task
        return

    text, media_type, media_url = _extract_content(message)
    if not text and not media_url:
        return

    # Отфильтровываем мусор: слэш-команды и слишком короткий текст без медиа/URL
    if text and text.startswith("/"):
        return
    if text and not media_url and not _find_url(text) and len(text.strip()) < 10:
        return

    await _process_and_reply(message, text, media_type, media_url)
