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

// По id записи-данных (datapoint), а не по объекту: после изменения строки
// список может отдать её новым объектом-обёрткой.
function indexIn(list, recordId) {
    return list.records.findIndex((r) => r.id === recordId);
}

export class PmkPickListToggle extends ListBooleanToggleField {
    // Строка вложенного списка «в правке» не бывает (список не редактируемый),
    // и штатный onClick списочного переключателя щелчок по ячейке пропускает.
    // Здесь щелчок по ячейке переключает сам; по самому флажку — его штатное
    // изменение (onChange), без двойного переключения.
    async onClick(ev) {
        if (this.props.readonly) {
            return;
        }
        const record = this.props.record;
        const name = this.props.name;
        const list = listOf(record);
        const onCheckbox = Boolean(ev?.target?.closest?.("input, label"));
        const shift = Boolean(ev?.shiftKey) || shiftDown;
        if (shift && last && list && last.parentId === record._parentRecord?.id && last.field === list.resModel) {
            if (onCheckbox) {
                ev.preventDefault(); // флажок не переключать — диапазон ставим сами
            }
            const a = indexIn(list, last.recordId);
            const b = indexIn(list, record.id);
            const value = !record.data[name];
            if (a >= 0 && b >= 0) {
                const [from, to] = a < b ? [a, b] : [b, a];
                // Пачкой: строки меняются без пересчёта с сервером, пересчёт — один
                // раз на последней (иначе десять строк — десять запросов подряд).
                const recs = list.records.slice(from, to + 1).filter((r) => r.data[name] !== value);
                // Публичный update в Odoo 19 опций не принимает — промежуточные
                // строки через _update без пересчёта и без обновления расчёта,
                // последнюю — обычным update (пересчёт счётчика «Отмечено»).
                for (const [i, rec] of recs.entries()) {
                    if (i < recs.length - 1) {
                        await rec._update({ [name]: value }, { withoutOnchange: true, withoutParentUpdate: true });
                    } else {
                        await rec.update({ [name]: value });
                    }
                }
            }
        } else if (!onCheckbox) {
            await record.update({ [name]: !record.data[name] });
        }
        last = { parentId: record._parentRecord?.id, field: list?.resModel, recordId: record.id };
    }
}

registry.category("fields").add("pmk_pick_toggle", booleanToggleField);
registry.category("fields").add("list.pmk_pick_toggle", {
    ...listBooleanToggleField,
    component: PmkPickListToggle,
});
