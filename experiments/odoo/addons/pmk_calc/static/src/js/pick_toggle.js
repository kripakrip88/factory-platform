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

    setup() {
        super.setup();
        this.shift = false;
    }

    // Shift с нажатием мыши выделял бы текст таблицы — не даём.
    // Признак Shift только ставим: щелчок по подписи переключателя порождает
    // второй, внутренний щелчок по флажку уже без Shift — он не должен его снять.
    onMouseDown(ev) {
        if (ev.shiftKey) {
            ev.preventDefault();
            this.shift = true;
        }
    }

    onClickCapture(ev) {
        if (ev.shiftKey) {
            this.shift = true;
        }
    }

    async onChange(newValue) {
        const record = this.props.record;
        const list = listOf(record);
        if (this.shift && last && list && toRaw(last.list) === toRaw(list)) {
            const a = indexIn(list, last.record);
            const b = indexIn(list, record);
            if (a >= 0 && b >= 0) {
                const [from, to] = a < b ? [a, b] : [b, a];
                for (const rec of list.records.slice(from, to + 1)) {
                    if (toRaw(rec) !== toRaw(record) && rec.data[this.props.name] !== newValue) {
                        await rec.update({ [this.props.name]: newValue });
                    }
                }
            }
        }
        last = { list, record };
        this.shift = false;
        return super.onChange(newValue);
    }
}

registry.category("fields").add("pmk_pick_toggle", {
    ...booleanToggleField,
    component: PmkPickToggle,
});
