import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from src.config import settings
from src.services import storage, scheduler, importer
from src.keyboards import (
    review_keyboard, categories_keyboard, category_nav_keyboard,
    CATEGORY_EMOJI, main_menu,
)

logger = logging.getLogger(__name__)
router = Router()

SCORE_MAP = {
    "review_like": 1,
    "review_skip": -1,
    "review_save": 2,
}
SCORE_REPLY = {
    1: "👍 Сохранено",
    -1: "⏭ Пропущено",
    2: "★ В избранное",
}


def _owner_only(message: Message) -> bool:
    return message.from_user and message.from_user.id == settings.owner_user_id


def _build_item_text(item: dict) -> str:
    emoji = CATEGORY_EMOJI.get(item["category"], "📌")
    tags_str = " ".join(f"#{t}" for t in item["tags"]) if item["tags"] else ""
    text = (
        f"{emoji} <b>{item['category']}</b>  ⭐{item['importance']}/5\n\n"
        f"{item['summary'] or item.get('raw_text', '')[:200]}\n"
        f"{tags_str}"
    ).strip()
    return text


# ── Логика (вызывается и из команд, и из кнопок меню) ────────────────────────

async def cmd_review_logic(message: Message) -> None:
    items = await storage.get_unreviewed(settings.review_batch_size)
    if not items:
        await message.answer("📭 Нет новых айтемов для review.")
        return
    await message.answer(f"📬 <b>{len(items)} айтемов на review:</b>", parse_mode="HTML")
    for item in items:
        neighbours = await storage.get_neighbours(item["id"])
        keyboard = review_keyboard(item["id"], neighbours["prev"], neighbours["next"])
        await message.answer(_build_item_text(item), parse_mode="HTML", reply_markup=keyboard)


async def cmd_stats_logic(message: Message) -> None:
    stats = await storage.get_stats()
    lines = [
        "📊 <b>Second Brain — статистика</b>\n",
        f"Всего: <b>{stats['total']}</b>",
        f"На review: <b>{stats['unreviewed']}</b>\n",
        "<b>По категориям:</b>",
    ]
    for cat, cnt in stats["by_category"]:
        emoji = CATEGORY_EMOJI.get(cat, "📌")
        lines.append(f"  {emoji} {cat}: <b>{cnt}</b>")
    await message.answer("\n".join(lines), parse_mode="HTML")


async def cmd_categories_logic(message: Message) -> None:
    await message.answer("📂 <b>Выбери категорию:</b>", parse_mode="HTML",
                         reply_markup=categories_keyboard())


# ── Команды ───────────────────────────────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    if not _owner_only(message):
        return
    await message.answer(
        "👋 Second Brain запущен. Используй меню:",
        reply_markup=main_menu(),
    )


@router.message(Command("review"))
async def cmd_review(message: Message) -> None:
    if not _owner_only(message):
        return
    await cmd_review_logic(message)


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not _owner_only(message):
        return
    await cmd_stats_logic(message)


@router.message(Command("categories"))
async def cmd_categories(message: Message) -> None:
    if not _owner_only(message):
        return
    await cmd_categories_logic(message)


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
    await message.answer(f"🔍 Найдено: <b>{len(results)}</b>", parse_mode="HTML")
    for item in results:
        neighbours = await storage.get_neighbours(item["id"])
        keyboard = review_keyboard(item["id"], neighbours["prev"], neighbours["next"])
        await message.answer(_build_item_text(item), parse_mode="HTML", reply_markup=keyboard)


@router.message(Command("import"))
async def cmd_import(message: Message) -> None:
    if not _owner_only(message):
        return
    text = await importer.handle_import_command()
    await message.answer(text, parse_mode="HTML")


# ── Callback: review кнопки (👍 / ⏭ / ★) ────────────────────────────────────

@router.callback_query(F.data.startswith("review_"))
async def handle_review_callback(callback: CallbackQuery) -> None:
    if callback.from_user.id != settings.owner_user_id:
        await callback.answer("Нет доступа.")
        return

    parts = callback.data.rsplit("_", 1)
    if len(parts) != 2:
        await callback.answer("Неверный формат.")
        return

    action_key = parts[0]
    item_id = parts[1]

    score = SCORE_MAP.get(action_key)
    if score is None:
        await callback.answer("Неизвестное действие.")
        return

    await storage.mark_reviewed(item_id, score)
    await callback.answer(SCORE_REPLY[score])
    await callback.message.edit_reply_markup(reply_markup=None)


# ── Callback: навигация ‹ / › ────────────────────────────────────────────────

@router.callback_query(F.data.startswith("nav_"))
async def handle_nav_callback(callback: CallbackQuery) -> None:
    if callback.from_user.id != settings.owner_user_id:
        await callback.answer()
        return

    _, _, item_id = callback.data.split("_", 2)
    item = await storage.get_item(item_id)
    if not item:
        await callback.answer("Айтем не найден.")
        return

    neighbours = await storage.get_neighbours(item_id)
    keyboard = review_keyboard(item_id, neighbours["prev"], neighbours["next"])
    await callback.message.edit_text(
        _build_item_text(item), parse_mode="HTML", reply_markup=keyboard
    )
    await callback.answer()


# ── Callback: категории ───────────────────────────────────────────────────────

@router.callback_query(F.data == "show_categories")
async def handle_show_categories(callback: CallbackQuery) -> None:
    if callback.from_user.id != settings.owner_user_id:
        await callback.answer()
        return
    await callback.message.edit_text(
        "📂 <b>Выбери категорию:</b>", parse_mode="HTML",
        reply_markup=categories_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cat_"))
async def handle_category_callback(callback: CallbackQuery) -> None:
    if callback.from_user.id != settings.owner_user_id:
        await callback.answer()
        return

    parts = callback.data.split("_")
    # формат: cat_{category}_{offset}
    category = parts[1]
    offset = int(parts[2])

    items = await storage.get_by_category(category, limit=5, offset=offset)
    if not items:
        await callback.answer("Нет айтемов в этой категории.")
        return

    emoji = CATEGORY_EMOJI.get(category, "📌")
    header = f"{emoji} <b>{category}</b> (показано {offset + 1}–{offset + len(items)})\n\n"
    lines = []
    for item in items:
        tags_str = " ".join(f"#{t}" for t in item["tags"]) if item["tags"] else ""
        lines.append(f"• {item['summary'] or item.get('raw_text','')[:100]}\n  {tags_str}")

    has_more = len(items) == 5
    keyboard = category_nav_keyboard(category, offset, has_more)

    await callback.message.edit_text(
        header + "\n\n".join(lines),
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    await callback.answer()
