import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from src.config import settings
from src.services import storage, scheduler, importer

logger = logging.getLogger(__name__)
router = Router()

SCORE_MAP = {
    "review_like": 1,
    "review_skip": -1,
    "review_save": 2,
}
SCORE_REPLY = {
    1: "✅ Сохранено",
    -1: "⏭ Пропущено",
    2: "★ В избранное",
}


def _owner_only(message: Message) -> bool:
    return message.from_user and message.from_user.id == settings.owner_user_id


@router.message(Command("review"))
async def cmd_review(message: Message) -> None:
    if not _owner_only(message):
        return
    items = await storage.get_unreviewed(settings.review_batch_size)
    if not items:
        await message.answer("📭 Нет айтемов для review.")
        return
    for item in items:
        text, buttons = scheduler.build_review_card(item)
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=b["text"], callback_data=b["callback_data"]) for b in row]
                for row in buttons
            ]
        )
        await message.answer(text, parse_mode="HTML", reply_markup=keyboard)


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not _owner_only(message):
        return
    stats = await storage.get_stats()
    lines = [
        f"📊 <b>Статистика Second Brain</b>\n",
        f"Всего айтемов: <b>{stats['total']}</b>",
        f"Непросмотрено: <b>{stats['unreviewed']}</b>\n",
        "<b>По категориям:</b>",
    ]
    for cat, cnt in stats["by_category"]:
        emoji = scheduler.CATEGORY_EMOJI.get(cat, "📌")
        lines.append(f"  {emoji} {cat}: {cnt}")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("search"))
async def cmd_search(message: Message) -> None:
    if not _owner_only(message):
        return
    query = message.text.removeprefix("/search").strip()
    if not query:
        await message.answer("Использование: /search <запрос>")
        return
    results = await storage.search(query)
    if not results:
        await message.answer("🔍 Ничего не найдено.")
        return
    lines = [f"🔍 Найдено: {len(results)}\n"]
    for item in results:
        emoji = scheduler.CATEGORY_EMOJI.get(item["category"], "📌")
        lines.append(f"{emoji} <b>{item['category']}</b>\n{item['summary']}\n")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("import"))
async def cmd_import(message: Message) -> None:
    if not _owner_only(message):
        return
    text = await importer.handle_import_command()
    await message.answer(text, parse_mode="HTML")


@router.callback_query(F.data.startswith("review_"))
async def handle_review_callback(callback: CallbackQuery) -> None:
    if callback.from_user.id != settings.owner_user_id:
        await callback.answer("Нет доступа.")
        return

    parts = callback.data.rsplit("_", 1)
    if len(parts) != 2:
        await callback.answer("Неверный формат.")
        return

    action_key = parts[0]  # e.g. "review_like"
    item_id = parts[1]

    score = SCORE_MAP.get(action_key)
    if score is None:
        await callback.answer("Неизвестное действие.")
        return

    await storage.mark_reviewed(item_id, score)
    await callback.answer(SCORE_REPLY[score])
    await callback.message.edit_reply_markup(reply_markup=None)
