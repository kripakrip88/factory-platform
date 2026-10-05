/** @odoo-module **/
/**
 * ПРАВКА ПМК (шаг 41 разбора удобства, А9, 05.10.2026): ширина колонок
 * почты — правила без Owl и без сервисов (node-тест
 * static/tests/step41_rules.test.mjs).
 *
 * Границы «папки | список» и «список | письмо» перетаскиваются (и стрелками
 * ← → с клавиатуры), двойной щелчок по границе — ширина по умолчанию. Выбор
 * помнится у человека в этом браузере: ключ с номером пользователя
 * (widthsKey), чтобы на общем компьютере у каждого была своя раскладка.
 * Хранятся только ширины, которые человек менял: остальные — из стилей
 * (mail_client.scss), как было.
 *
 * Ширины — в пикселях. У компактного вида списка своя ширина (listCompact):
 * он шире, и ширина удобного вида ему не подходит.
 */

export const PANE_DEFAULTS = { folders: 240, list: 384, listCompact: 544 };
export const PANE_LIMITS = {
    folders: [160, 400],
    list: [280, 1200],
    listCompact: [400, 1400],
};
/** Письму не меньше стольких пикселей: иначе в окне чтения не прочесть. */
export const READER_MIN = 360;
/** Шаг стрелки на границе колонок. */
export const KEY_STEP = 16;

const KEYS = Object.keys(PANE_DEFAULTS);

export function widthsKey(uid) {
    return `mail_client.pane_widths.u${uid || 0}`;
}

/** Сохранённые ширины; битая запись — как будто ничего не сохраняли. */
export function parseWidths(raw) {
    let data = null;
    try {
        data = raw ? JSON.parse(raw) : null;
    } catch {
        data = null;
    }
    const widths = {};
    if (!data || typeof data !== "object" || Array.isArray(data)) {
        return widths;
    }
    for (const key of KEYS) {
        const value = Number(data[key]);
        if (Number.isFinite(value) && value > 0) {
            const [low, high] = PANE_LIMITS[key];
            widths[key] = Math.round(Math.min(high, Math.max(low, value)));
        }
    }
    return widths;
}

/**
 * Ширина колонки key после перетаскивания: в своих пределах, и письму
 * остаётся не меньше READER_MIN. available — ширина всей области почты,
 * others — сколько занимают остальные колонки рядом (папки или список) и
 * границы между ними.
 */
export function clampPane(key, value, { available = 0, others = 0 } = {}) {
    const [low, high] = PANE_LIMITS[key] || [0, Infinity];
    let max = high;
    if (available > 0) {
        max = Math.min(max, available - others - READER_MIN);
    }
    return Math.round(Math.max(low, Math.min(max, Number(value) || low)));
}

/** CSS-переменные корня почты для заданных ширин. */
export function paneVars(widths) {
    const names = { folders: "--mc-folders-w", list: "--mc-list-w", listCompact: "--mc-list-w-compact" };
    return KEYS.filter((key) => widths && widths[key])
        .map((key) => `${names[key]}: ${widths[key]}px`)
        .join("; ");
}
