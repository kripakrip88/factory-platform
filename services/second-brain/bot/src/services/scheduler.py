import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot

from src.config import settings
from src.services import storage
from src.keyboards import CATEGORY_EMOJI, CATEGORY_RU

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def build_review_card(item: dict) -> tuple[str, list]:
    emoji = CATEGORY_EMOJI.get(item["category"], "📌")
    tags_str = ", ".join(item["tags"]) if item["tags"] else "—"
    cat_ru = CATEGORY_RU.get(item["category"], item["category"])
    text = (
        f"{emoji} <b>{cat_ru}</b>\n\n"
        f"{item['summary']}\n\n"
        f"🏷 {tags_str}\n"
        f"⭐ Важность: {item['importance']}/5"
    )
    buttons = [
        [
            {"text": "👍 Сохранить", "callback_data": f"review_like_{item['id']}"},
            {"text": "⏭ Скипнуть", "callback_data": f"review_skip_{item['id']}"},
            {"text": "★ Избранное", "callback_data": f"review_save_{item['id']}"},
        ]
    ]
    return text, buttons


async def send_digest(bot: Bot) -> None:
    items = await storage.get_unreviewed(settings.review_batch_size)
    if not items:
        await bot.send_message(settings.owner_user_id, "📭 Нет новых айтемов для review.")
        return

    await bot.send_message(
        settings.owner_user_id,
        f"📬 <b>Дайджест</b> — {len(items)} айтемов на review:",
        parse_mode="HTML",
    )
    for item in items:
        text, buttons = build_review_card(item)
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=b["text"], callback_data=b["callback_data"]) for b in row]
                for row in buttons
            ]
        )
        await bot.send_message(
            settings.owner_user_id,
            text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )


def start_scheduler(bot: Bot) -> None:
    global _scheduler
    parts = settings.review_cron.split()
    trigger = CronTrigger(
        minute=parts[0], hour=parts[1], day=parts[2],
        month=parts[3], day_of_week=parts[4],
    )
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(send_digest, trigger, args=[bot], id="daily_digest")
    _scheduler.start()
    logger.info("Scheduler started, cron=%s", settings.review_cron)


def stop_scheduler() -> None:
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
