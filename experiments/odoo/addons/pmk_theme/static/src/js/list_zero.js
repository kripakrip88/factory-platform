/** @odoo-module **/
// Нули в таблицах — бледные.
//
// «Оживить таблицы», приём 2 (Антон, 29.09.2026: «делай всё из
// предложения»). Как на кнопках-счётчиках: пустой расчёт «0 кг · 0 руб» не
// должен спорить с настоящими суммами — глаз сразу видит строки, где что-то
// есть. Число не прячем: оно остаётся на месте, только серое.
//
// КАК. Классы ячейки списка собирает ListRenderer.getCellClass — патч
// прототипа доходит до всех списков (все подклассы ядра зовут super).
// Добавляем класс o_pmk_zero, если значение числового поля ровно ноль;
// цвет — в scss/forms_nexus.scss, раздел «Таблицы».
//
// ГДЕ НЕ ДЕЛАЕМ:
//   • вложенные таблицы документов (строки расчёта, заказа): там ноль часто
//     значит «нет цены», и это сигнал, его нельзя приглушать;
//   • строка в правке — в ячейке поле ввода;
//   • виджеты, у которых ноль — не «пусто» (номер по порядку handle,
//     проценты-полосы) — берём только ячейки без виджета или с числовым.
// Смысловой цвет ячейки (decoration-danger и т. п.) важнее серого: у него
// !important, наш класс его не перебивает.

import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";

const NUMERIC_TYPES = new Set(["integer", "float", "monetary"]);
const PLAIN_WIDGETS = new Set([undefined, null, "", "monetary", "float", "integer", "float_time"]);

patch(ListRenderer.prototype, {
    getCellClass(column, record) {
        const classNames = super.getCellClass(...arguments);
        if (column.type !== "field" || this.isX2Many || record.isInEdition) {
            return classNames;
        }
        const field = this.fields[column.name];
        if (!field || !NUMERIC_TYPES.has(field.type) || !PLAIN_WIDGETS.has(column.widget)) {
            return classNames;
        }
        return record.data[column.name] === 0 ? `${classNames} o_pmk_zero` : classNames;
    },
});
