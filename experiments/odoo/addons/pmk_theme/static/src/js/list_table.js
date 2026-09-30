/** @odoo-module **/
// Таблицы одного вида (разбор UX, шаг 24, 01.10.2026) — на все списки
// системы и таблицы внутри форм. Геометрия (шапка без капса с переносом,
// строка ~31 px, без пустой полосы итогов) — scss/forms_nexus.scss, раздел 6.
//
// 1. БЕЗ ПУСТЫХ СТРОК-РАСПОРОК. Ядро добивает таблицу до четырёх строк
//    пустыми (list_renderer.js, getEmptyRowIds; шаблон рисует их, когда у
//    действия нет подсказки пустого экрана — это все таблицы внутри форм,
//    доборка, обрезки, справочники). Под «Добавить строку» они читались как
//    незаполненные записи, а пустой список — как четыре полосатые строки
//    «что-то сломалось». Состав расчёта убрал их у себя ещё на шаге 32
//    (pmk_calc/static/src/js/product_lines_field.js) — там переопределение
//    осталось и ничему не мешает.
//
// 2. ЗНАКИ ИТОГА КАК В СТРОКАХ — правило в js/list_table_rules.js (чистая
//    функция, её гоняет node). Здесь только подключение к списку.
//
// Вернуть штатное поведение: убрать этот файл из __manifest__.py (или
// удалить нужный метод ниже) и выложить pmk_theme.

import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { columnWithRowDigits } from "@pmk_theme/js/list_table_rules";

// Колонки вида живут, пока открыт вид, и приходят в getActiveColumns одними
// и теми же объектами. Запоминаем результат, чтобы на каждую отрисовку не
// выдавать полям новый fieldInfo: поле с новым объектом свойств
// перерисовывается, даже если ничего не поменялось.
const withRowDigits = new WeakMap();

patch(ListRenderer.prototype, {
    get getEmptyRowIds() {
        return [];
    },

    getActiveColumns() {
        return super.getActiveColumns(...arguments).map((column) => {
            if (!withRowDigits.has(column)) {
                withRowDigits.set(column, columnWithRowDigits(column, this.fields[column.name]));
            }
            return withRowDigits.get(column);
        });
    },
});
