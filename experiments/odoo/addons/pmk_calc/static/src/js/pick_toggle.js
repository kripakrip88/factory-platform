/** @odoo-module **/
// «Перенести» в списке изделий расчёта (13.10.2026): переключатель с выбором
// диапазона через Shift, как в проводнике (просьба Антона: «выбрал 2 позицию,
// зажал шифт и выделил сразу 10 позиций по порядку»).
//
// Щелчок с Shift ставит то же значение всем строкам между прошлым щелчком и
// этим — в порядке строк на экране. Работает в браузере, до сохранения:
// записи вложенного списка меняются так же, как обычным щелчком.

import { toRaw } from "@odoo/owl";
import { registry } from "@web/core/registry";
import {
    BooleanToggleField,
    booleanToggleField,
} from "@web/views/fields/boolean_toggle/boolean_toggle_field";

// Прошлый щелчок: список и строка. Один на страницу — список изделий один.
let last = null;

// Нажат ли Shift — по самой клавише: признак shiftKey у щелчка по переключателю
// теряется (щелчок по подписи порождает внутренний щелчок по флажку без Shift).
let shiftDown = false;
window.addEventListener("keydown", (ev) => {
    if (ev.key === "Shift") {
        shiftDown = true;
    }
}, true);
window.addEventListener("keyup", (ev) => {
    if (ev.key === "Shift") {
        shiftDown = false;
    }
}, true);
window.addEventListener("blur", () => {
    shiftDown = false;
});

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

export class PmkPickToggle extends BooleanToggleField {
    static template = "pmk_calc.PmkPickToggle";

    // Shift с нажатием мыши выделял бы текст таблицы — не даём.
    onMouseDown(ev) {
        if (ev.shiftKey || shiftDown) {
            ev.preventDefault();
        }
    }

    // Щелчок с Shift диапазон отмечает сам (до переключателя: его внутренний
    // щелчок по флажку Shift теряет). Без Shift — обычный переключатель, а
    // строка запоминается как начало следующего диапазона.
    async onClickCapture(ev) {
        const record = this.props.record;
        const list = listOf(record);
        const name = this.props.name;
        if ((ev.shiftKey || shiftDown) && last && list && toRaw(last.list) === toRaw(list)) {
            ev.preventDefault();
            ev.stopPropagation();
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
            last = { list, record };
            return;
        }
        last = { list, record };
    }
}

registry.category("fields").add("pmk_pick_toggle", {
    ...booleanToggleField,
    component: PmkPickToggle,
});
