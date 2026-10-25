/** @odoo-module **/
/**
 * Шапка документа — разбор UX, шаг 48 (06.10.2026): правила без Odoo.
 *
 * Чистые функции без импортов Odoo — их гоняет node
 * (static/tests/form_head_step48.test.mjs). Использует form_head.js.
 */

/** Метка формы: кнопки и этап из <header> — в строку пути. */
export const HEADER_UP_CLASS = "o_pmk_header_up";

/**
 * Метка формы: шапка «вариант А» (Антон 25.10.2026) — одна главная кнопка
 * (следующий шаг), остальные кнопки — в «Ещё ▾», статус — у номера.
 */
export const HEAD_A_CLASS = "o_pmk_head_a";

/**
 * Флаги кнопки шапки по её классам: primary — кандидат в главную кнопку
 * (btn-primary / oe_highlight); more — уступает другой главной (o_pmk_more);
 * keep — всегда в ряду (o_pmk_keep; виджеты — меню «Создать ▾»); skip — в
 * шапке не показывать, есть в меню (o_pmk_in_create — пункт «Создать ▾»,
 * o_pmk_in_cog — пункт «⚙»; Антон 25.10.2026).
 */
export function headButtonFlags(classes, isWidget = false) {
    const list = String(classes || "").split(/[\s`'"+]+/);
    const has = (c) => list.includes(c);
    return {
        primary: has("btn-primary") || has("oe_highlight"),
        more: has("o_pmk_more"),
        keep: isWidget || has("o_pmk_keep"),
        skip: has("o_pmk_in_create") || has("o_pmk_in_cog"),
    };
}

/**
 * Раскладка видимых кнопок шапки «вариант А»: main — первая главная кнопка,
 * inline — второстепенные в ряду, more — в «Ещё ▾», keep — в ряду после них.
 * Главная с o_pmk_more УСТУПАЕТ: главная, только если другой нет. «Ещё ▾» —
 * от двух кнопок: меню ради одной — «глупость настоящая» (Антон 25.10.2026),
 * одна — обычной кнопкой. skip — не показывается вовсе.
 * slots — [{name, primary, more, keep, skip}] в порядке шапки.
 */
export function splitHeadSlots(slots) {
    const shown = slots.filter((slot) => !slot.skip);
    const rest = shown.filter((slot) => !slot.keep);
    const main =
        rest.find((slot) => slot.primary && !slot.more) || rest.find((slot) => slot.primary) || null;
    const others = rest.filter((slot) => slot !== main).map((slot) => slot.name);
    return {
        main: main ? main.name : null,
        inline: others.length === 1 ? others : [],
        more: others.length > 1 ? others : [],
        keep: shown.filter((slot) => slot.keep).map((slot) => slot.name),
    };
}

/**
 * Размер экрана ядра (SIZES в @web/core/ui/ui_service), с которого шапка
 * уходит в строку пути: XL — от 1200 px. Уже — отдельной строкой, как было.
 *
 * Не LG (992): у сделки в работе с несохранёнными правками строка пути —
 * номер 172 px, «⚙ ▾» и «✓ ✕» ~160, кнопки и счётчики 446, этап и стрелки
 * 306 (этап сжимается не уже ~140: деления, срок и стрелка списка) — ряд
 * помещается лишь примерно от 1060 px, на 992–1060 строка пути наезжала
 * на «Расчёт и КП», а стрелки — на этап (проверка шага 48). Между 1060 и
 * 1199 ядро не перерисовывает форму при смене ширины (ui.bus «resize» —
 * только на границах SIZES), поэтому порог — ближайшая граница ядра, 1200.
 */
export const HEADER_UP_MIN_SIZE = 4;

export function headerUpAt(size, minSize = HEADER_UP_MIN_SIZE) {
    return Number.isInteger(size) && size >= minSize;
}

/**
 * Узел шапки уходит к этапу (справа, перед стрелками) или к кнопкам (после
 * названия). Та же раскладка, что у ядра в FormCompiler.compileHeader: поле
 * без класса btn — этап (statusbar), остальное — кнопки.
 */
export function isStatusNode(tagName, classes = []) {
    const list = typeof classes === "string" ? classes.split(/\s+/) : [...classes];
    return String(tagName || "").toLowerCase() === "field" && !list.includes("btn");
}

/** Узел скрыт насовсем (invisible="1"/"True") — ядро его не рисует. */
export function isAlwaysHidden(invisible) {
    return ["1", "True", "true"].includes(String(invisible || "").trim());
}

/** «Control+N» на Mac (ядро подменяет там Alt на Control,
 *  hotkey_service.js), «Alt+N» на остальных. */
export function hotkeyLabel(letter, isMac) {
    return `${isMac ? "Control" : "Alt"}+${String(letter || "").toUpperCase()}`;
}

/**
 * Подсказка стрелки листалки формы: «Следующая — Control+N (2 из 6)».
 * dir: 1 — следующая, -1 — предыдущая; offset — номер текущей записи с нуля.
 * Счётчика «1 / 2» на экране нет — «N из M» только здесь.
 */
export function pagerTooltip(dir, offset, total, isMac) {
    const next = dir > 0;
    const word = next ? "Следующая" : "Предыдущая";
    const key = hotkeyLabel(next ? "n" : "p", isMac);
    const count = Number(total) || 0;
    if (count < 1) {
        return `${word} — ${key}`;
    }
    const current = Math.min(Math.max((Number(offset) || 0) + 1, 1), count);
    return `${word} — ${key} (${current} из ${count})`;
}

const DOC_NUMBER = /^[A-ZА-ЯЁ]{1,4}-\d{3,}( от \d\d\.\d\d\.\d{4})?$/;

/**
 * Звено строки пути, которое сжимать нельзя: короткое (до 16 знаков —
 * номер «СМ-00025» или раздел) или номер документа с датой
 * («СД-00001 от 27.09.2026», 22 знака). Сжимается только длинное название.
 */
export function isShortCrumb(name) {
    const text = String(name || "").trim();
    if (!text) {
        return false;
    }
    return text.length <= 16 || DOC_NUMBER.test(text);
}
