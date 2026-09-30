/** @odoo-module **/
/**
 * Таблицы одного вида (разбор UX, шаг 24, 01.10.2026) — правила без импортов
 * Odoo, чтобы прогонять их в node без браузера. Использует js/list_table.js.
 *
 * ЗНАКИ ИТОГА КАК В СТРОКАХ. Итог колонки внизу таблицы ядро форматирует
 * только по атрибуту колонки digits (web/views/list/list_renderer.js,
 * computeAggregates), а без него — двумя знаками. Строки и строки групп
 * берут знаки поля. Отсюда в заданиях лазера «77,4» в строке и «77,40» в
 * итоге. Проставляем колонке digits из options.digits или из поля — итог
 * получает те же знаки, что строки; сами строки не меняются: без атрибута
 * они брали те же знаки поля.
 *
 * ГДЕ. Только колонка с итогом (sum / avg / max / min) у дробного поля без
 * виджета или с виджетом float. Деньги — нет: их знаки ставит
 * js/list_money.js (без копеек). Проценты, время, полоски и свои виджеты —
 * нет: у них итог и ячейка форматируются не так, как число. Колонку, где
 * digits задан в виде, не трогаем — вид важнее.
 */

const AGGREGATE_ATTRS = ["sum", "avg", "max", "min"];
const PLAIN_WIDGETS = new Set([undefined, null, "", "float"]);

/**
 * Колонка со знаками итога, как у строк. Возвращает новую колонку или ту
 * же самую, если править нечего; исходную не меняет.
 *
 * @param {Object} column колонка списка (archInfo.columns)
 * @param {Object} [field] описание поля (fields_get)
 * @returns {Object}
 */
export function columnWithRowDigits(column, field) {
    if (!column || column.type !== "field" || !field || field.type !== "float") {
        return column;
    }
    const attrs = column.attrs || {};
    if (attrs.digits || !PLAIN_WIDGETS.has(column.widget)) {
        return column;
    }
    if (!AGGREGATE_ATTRS.some((name) => attrs[name])) {
        return column;
    }
    const digits = column.options?.digits || field.digits;
    if (!Array.isArray(digits) || digits.length !== 2) {
        return column;
    }
    return { ...column, attrs: { ...attrs, digits: JSON.stringify(digits) } };
}
