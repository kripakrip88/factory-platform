import logging
import re
from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

URL_RE = re.compile(r'https?://[^\s<>"\']+')


def _extract_url(item: dict) -> str | None:
    if item.get("original_url"):
        return item["original_url"]
    text = item.get("raw_text") or ""
    m = URL_RE.search(text)
    return m.group(0) if m else None

from src.config import settings
from src.services import storage, scheduler, importer, classifier
from src.keyboards import (
    review_keyboard, categories_keyboard, category_nav_keyboard,
    CATEGORY_EMOJI, CATEGORY_RU, main_menu,
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


async def _send_item_card(target, item: dict, keyboard=None) -> None:
    """Отправляет карточку айтема — с фото если есть, иначе текстом."""
    if keyboard is None:
        neighbours = await storage.get_neighbours(item["id"])
        url = _extract_url(item)
        keyboard = review_keyboard(item["id"], neighbours["prev"], neighbours["next"], url=url)

    text = _build_item_text(item)
    media_url = item.get("media_url")
    media_type = item.get("media_type")

    try:
        if media_url and media_type == "photo":
            await target.answer_photo(media_url, caption=text, parse_mode="HTML", reply_markup=keyboard)
        elif media_url and media_type == "video":
            await target.answer_video(media_url, caption=text, parse_mode="HTML", reply_markup=keyboard)
        else:
            await target.answer(text, parse_mode="HTML", reply_markup=keyboard)
    except Exception:
        await target.answer(text, parse_mode="HTML", reply_markup=keyboard)


def _build_item_text(item: dict) -> str:
    emoji = CATEGORY_EMOJI.get(item["category"], "📌")
    cat_ru = CATEGORY_RU.get(item["category"], item["category"])
    tags_str = " ".join(f"#{t}" for t in item["tags"]) if item["tags"] else ""
    text = (
        f"{emoji} <b>{cat_ru}</b>  ⭐{item['importance']}/5\n\n"
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
        await _send_item_card(message, item)


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
        cat_ru = CATEGORY_RU.get(cat, cat)
        lines.append(f"  {emoji} {cat_ru}: <b>{cnt}</b>")
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
        await _send_item_card(message, item)


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
    url = _extract_url(item)
    keyboard = review_keyboard(item_id, neighbours["prev"], neighbours["next"], url=url)
    text = _build_item_text(item)
    media_url = item.get("media_url")
    media_type = item.get("media_type")
    try:
        if media_url and media_type == "photo":
            await callback.message.answer_photo(media_url, caption=text, parse_mode="HTML", reply_markup=keyboard)
            await callback.message.delete()
        else:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    except Exception:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
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
    category = parts[1]
    offset = int(parts[2])

    items = await storage.get_by_category(category, limit=5, offset=offset)
    if not items:
        await callback.answer("Нет айтемов в этой категории.")
        return

    emoji = CATEGORY_EMOJI.get(category, "📌")
    has_more = len(items) == 5

    # Заголовок с навигацией по страницам
    nav_row = []
    if offset > 0:
        nav_row.append(InlineKeyboardButton(text="‹ Назад", callback_data=f"cat_{category}_{offset - 5}"))
    if has_more:
        nav_row.append(InlineKeyboardButton(text="Ещё ›", callback_data=f"cat_{category}_{offset + 5}"))

    header_kb = InlineKeyboardMarkup(inline_keyboard=[
        nav_row,
        [InlineKeyboardButton(text="↩ К категориям", callback_data="show_categories")],
    ]) if nav_row else InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩ К категориям", callback_data="show_categories")],
    ])

    await callback.message.edit_text(
        f"{emoji} <b>{category}</b> — айтемы {offset + 1}–{offset + len(items)}:",
        parse_mode="HTML",
        reply_markup=header_kb,
    )

    # Каждый айтем отдельной карточкой с кнопками
    for item in items:
        await _send_item_card(callback.message, item)

    await callback.answer()


# ── Callback: рейтинг ⭐ ──────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("rate_"))
async def handle_rating(callback: CallbackQuery) -> None:
    _, rating, item_id = callback.data.split("_", 2)
    await storage.set_user_rating(item_id, int(rating))
    await callback.answer(f"Рейтинг {'⭐' * int(rating)} сохранён")


# ── Callback: переописать ✏️ ──────────────────────────────────────────────────

@router.callback_query(F.data.startswith("redesc_"))
async def handle_redescribe(callback: CallbackQuery, state: FSMContext) -> None:
    item_id = callback.data.split("_", 1)[1]
    await state.set_state("waiting_redesc")
    await state.update_data(item_id=item_id)
    await callback.message.answer(
        "Напиши комментарий для Claude (например: 'это про здоровье, не про идею'):"
    )
    await callback.answer()


@router.message(StateFilter("waiting_redesc"))
async def handle_redesc_comment(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    item_id = data["item_id"]
    item = await storage.get_item(item_id)
    comment = message.text

    result = await classifier.classify(
        f"{item.get('raw_text', '')} [Подсказка пользователя: {comment}]",
        item.get("media_type"),
    )
    await storage.update_classification(item_id, result)
    await state.clear()
    await message.answer(
        f"✅ Переописано:\n{result['summary']}\nКатегория: {result['category']}"
    )


# ── Callback: сменить категорию 📂 ────────────────────────────────────────────

@router.callback_query(F.data.startswith("chcat_"))
async def handle_change_category(callback: CallbackQuery) -> None:
    item_id = callback.data.split("_", 1)[1]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{CATEGORY_EMOJI[cat]} {CATEGORY_RU[cat]}",
            callback_data=f"setcat_{cat}_{item_id}",
        )]
        for cat in CATEGORY_EMOJI
    ])
    await callback.message.answer("Выбери категорию:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("setcat_"))
async def handle_set_category(callback: CallbackQuery) -> None:
    _, cat, item_id = callback.data.split("_", 2)
    await storage.update_category(item_id, cat)
    emoji = CATEGORY_EMOJI.get(cat, "📌")
    await callback.answer(f"Категория изменена: {emoji} {CATEGORY_RU.get(cat, cat)}")
    await callback.message.delete()
