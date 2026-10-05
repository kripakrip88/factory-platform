/** @odoo-module **/
/**
 * ПРАВКА ПМК (шаг 41 разбора удобства, А7 и В4, 05.10.2026): поиск по мере
 * ввода, кнопки-фильтры над списком, имена вложений в строке — правила без
 * Owl и без сервисов (node-тест static/tests/step41_rules.test.mjs).
 */

/**
 * Кнопки-фильтры над списком — фильтры модуля почты (MESSAGE_FILTERS в
 * mail_client_action.js), в этом порядке. «Без ответа» из плана — это
 * фильтр «Ждут ответа» шага 18 (awaiting): одно понятие — одно слово.
 * Надстройка добавляет свои (pmk_mail_ui: «С лидом»).
 */
export const QUICK_FILTER_IDS = ["unread", "attachments", "awaiting"];

/** Поиск по мере ввода: с какого числа знаков и после какой паузы. */
export const SEARCH_MIN_CHARS = 2;
export const SEARCH_DELAY_MS = 400;

/** Повторный щелчок по нажатой кнопке-фильтру снимает фильтр. */
export function toggleQuickFilter(current, id) {
    return current === id ? "all" : id;
}

/**
 * Что делать с набранным в поиске.
 *
 * text — что в поле; applied — по чему список ищет сейчас; enter — нажали
 * Enter (искать сразу, даже один знак).
 *   "same"   — список уже такой, ничего не делать;
 *   "reset"  — поле пусто (или стёрли до одного знака) — обычный список;
 *   "wait"   — один знак: ждать продолжения;
 *   "search" — искать.
 */
export function searchDecision(text, { enter = false, applied = "" } = {}) {
    const value = String(text || "").trim();
    const current = String(applied || "").trim();
    if (value === current) {
        return "same";
    }
    if (!value) {
        return "reset";
    }
    if (value.length < SEARCH_MIN_CHARS && !enter) {
        return current ? "reset" : "wait";
    }
    return "search";
}

/**
 * Плашки имён вложений в строке: до max имён и «+N» за остальные.
 * names — имена (сервер присылает до трёх), count — сколько вложений всего.
 */
export function attachmentChips(names, count, max = 3) {
    const list = (names || []).filter(Boolean);
    const shown = list.slice(0, max);
    const total = Math.max(Number(count) || 0, list.length);
    return { shown, more: Math.max(0, total - shown.length) };
}
