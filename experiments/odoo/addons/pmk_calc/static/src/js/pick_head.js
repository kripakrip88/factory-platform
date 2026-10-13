/** @odoo-module **/
// «Отметить все» — в заголовке колонки галочек (Антон 13.10.2026: «кнопку
// выделить всё можно перенести сюда» — в пустую ячейку над галочками строк,
// как в МоёмСкладе). Колонка — поле с виджетом pmk_pick_toggle (pick_toggle.js),
// шаблон заголовка — pick_toggle.xml.

import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";

export const PICK_WIDGET = "pmk_pick_toggle";

// Поставить всем строкам списка одно значение — пачкой: промежуточные строки
// без пересчёта с сервером, последняя — обычным update (счётчик «Отмечено»).
export async function pickAll(records, name, value) {
    const recs = records.filter((r) => r.data[name] !== value);
    for (const [i, rec] of recs.entries()) {
        if (i < recs.length - 1) {
            await rec._update({ [name]: value }, { withoutOnchange: true, withoutParentUpdate: true });
        } else {
            await rec.update({ [name]: value });
        }
    }
}

patch(ListRenderer.prototype, {
    pmkPickAllOn(column) {
        const recs = this.props.list.records;
        return recs.length > 0 && recs.every((r) => r.data[column.name]);
    },

    async pmkPickSet(column, value) {
        await pickAll(this.props.list.records, column.name, value);
    },
});
