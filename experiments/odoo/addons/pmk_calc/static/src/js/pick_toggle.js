/** @odoo-module **/
// «Перенести» в списке изделий расчёта (13.10.2026): переключатель с выбором
// диапазона через Shift, как в проводнике (просьба Антона: «выбрал 2 позицию,
// зажал шифт и выделил сразу 10 позиций по порядку»).
//
// В списке Odoo берёт не сам переключатель, а его списочный вариант
// (list.boolean_toggle: щелчок по всей ячейке). Наш — такой же, плюс Shift:
// щелчок с Shift ставит строкам между прошлым щелчком и этим то же значение,
// что получает эта строка, — в порядке строк на экране, до сохранения.

import { toRaw } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { booleanToggleField } from "@web/views/fields/boolean_toggle/boolean_toggle_field";
import {
    ListBooleanToggleField,
    listBooleanToggleField,
} from "@web/views/fields/boolean_toggle/list_boolean_toggle_field";

// Прошлый щелчок: список и строка. Список изделий на странице один.
let last = null;

// Нажат ли Shift — и по самой клавише: у щелчка признак shiftKey бывает
// потерян (внутренний щелчок по флажку).
let shiftDown = false;
window.addEventListener("keydown", (ev) => ev.key === "Shift" && (shiftDown = true), true);
window.addEventListener("keyup", (ev) => ev.key === "Shift" && (shiftDown = false), true);
window.addEventListener("blur", () => (shiftDown = false));
// Shift + нажатие мыши по переключателю выделяло бы текст таблицы — не даём.
window.addEventListener("mousedown", (ev) => {
    if ((ev.shiftKey || shiftDown) && ev.target.closest?.(".o_field_pmk_pick_toggle")) {
        ev.preventDefault();
    }
}, true);

function listOf(record) {
    const parent = record?._parentRecord;
    if (!parent) {
        return null;
    }
    const raw = toRaw(record);
    for (const value of Object.values(parent.data)) {
        if (value && Array.isArray(value.records) && value.records.some((r) => toRaw(r) === raw)) {
            return value;
        }
    }
    return null;
}

function indexIn(list, record) {
    const raw = toRaw(record);
    return list.records.findIndex((r) => toRaw(r) === raw);
}

export class PmkPickListToggle extends ListBooleanToggleField {
    async onClick(ev) {
        const record = this.props.record;
        const name = this.props.name;
        const list = listOf(record);
        const shift = Boolean(ev?.shiftKey) || shiftDown;
        if (shift && last && list && toRaw(last.list) === toRaw(list)
                && !this.props.readonly && record.isInEdition) {
            const a = indexIn(list, last.record);
            const b = indexIn(list, record);
            const value = !record.data[name];
            if (a >= 0 && b >= 0) {
                const [from, to] = a < b ? [a, b] : [b, a];
                for (const rec of list.records.slice(from, to + 1)) {
                    if (rec.data[name] !== value) {
                        await rec.update({ [name]: value });
                    }
                }
            }
        } else {
            await super.onClick(ev);
        }
        last = { list, record };
    }
}

registry.category("fields").add("pmk_pick_toggle", booleanToggleField);
registry.category("fields").add("list.pmk_pick_toggle", {
    ...listBooleanToggleField,
    component: PmkPickListToggle,
});
