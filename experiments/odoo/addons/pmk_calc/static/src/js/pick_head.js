/** @odoo-module **/
// «Отметить все» — в заголовке колонки галочек (Антон 13.10.2026: «кнопку
// выделить всё можно перенести сюда» — в пустую ячейку над галочками строк,
// как в МоёмСкладе). Рядом, пока что-то отмечено, — действия (pick_bar.js).
// Колонка — поле с виджетом pmk_pick_toggle (pick_toggle.js),
// шаблон заголовка — pick_toggle.xml.

import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { PmkPickActions, pickAll } from "@pmk_calc/js/pick_bar";

export const PICK_WIDGET = "pmk_pick_toggle";

patch(ListRenderer.prototype, {
    // Компонент действий — через t-component: у наследников ListRenderer свои
    // static components, добавка в штатный до них не доходит.
    get pmkPickActions() {
        return PmkPickActions;
    },

    pmkPickedCount(column) {
        return this.props.list.records.filter((r) => r.data[column.name]).length;
    },

    pmkPickAllOn(column) {
        const recs = this.props.list.records;
        return recs.length > 0 && recs.every((r) => r.data[column.name]);
    },

    async pmkPickSet(column, value) {
        await pickAll(this.props.list.records, column.name, value);
    },
});
