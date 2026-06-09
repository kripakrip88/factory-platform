from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)

CATEGORY_EMOJI = {
    "idea": "💡",
    "health": "🩺",
    "article": "📖",
    "inspiration": "✨",
    "video": "🎬",
    "image": "🖼",
    "file": "📎",
    "link": "🔗",
    "other": "📌",
}

CATEGORIES = list(CATEGORY_EMOJI.keys())


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📬 Дайджест"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="📂 Категории"), KeyboardButton(text="🔍 Поиск")],
        ],
        resize_keyboard=True,
        persistent=True,
    )


def review_keyboard(item_id: str, prev_id: str = None, next_id: str = None) -> InlineKeyboardMarkup:
    action_row = [
        InlineKeyboardButton(text="👍", callback_data=f"review_like_{item_id}"),
        InlineKeyboardButton(text="⏭ Скип", callback_data=f"review_skip_{item_id}"),
        InlineKeyboardButton(text="★ Избранное", callback_data=f"review_save_{item_id}"),
    ]
    nav_row = []
    if prev_id:
        nav_row.append(InlineKeyboardButton(text="‹ Пред", callback_data=f"nav_prev_{prev_id}"))
    if next_id:
        nav_row.append(InlineKeyboardButton(text="След ›", callback_data=f"nav_next_{next_id}"))

    rows = [action_row]
    if nav_row:
        rows.append(nav_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def categories_keyboard() -> InlineKeyboardMarkup:
    rows = []
    row = []
    for cat, emoji in CATEGORY_EMOJI.items():
        row.append(InlineKeyboardButton(text=f"{emoji} {cat}", callback_data=f"cat_{cat}_0"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def category_nav_keyboard(category: str, offset: int, has_more: bool) -> InlineKeyboardMarkup:
    rows = []
    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton(text="‹ Назад", callback_data=f"cat_{category}_{offset - 5}"))
    if has_more:
        nav.append(InlineKeyboardButton(text="Ещё ›", callback_data=f"cat_{category}_{offset + 5}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="↩ К категориям", callback_data="show_categories")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
