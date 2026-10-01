/** @odoo-module **/
// «Копировать» у позиции доборки (приёмка 01.10.2026, R9b).
//
// Владелец: «В доборке нет функции копировать, было бы удобно, когда один
// профиль, но разными размерами». Кнопка в строке списка позиций заказа
// ДОБ- ставит копию СРАЗУ ПОД исходной: тот же профиль (чертёж), покрытие,
// металл, длина, количество, ширина рулона. Дальше позицию открывают и
// меняют размеры.
//
// ⚠️ ПОЧЕМУ НЕ СЕРВЕРНАЯ КНОПКА (type="object"). В Odoo 19 кнопка в строке
// вложенного списка у ещё не сохранённой строки не вызывает метод, а пишет
// «Сначала сохраните изменения» (list_renderer.xml: isX2Many and
// record.isNew → displaySaveNotification) — у нового заказа такие все
// строки. Поэтому копия делается в браузере штатным методом вложенного
// списка duplicateRecords (static_list.js; так ядро копирует разделы строк
// счёта): работает и у несохранённой доборки, копия встаёт за исходной,
// номера порядка у строк ниже сдвигаются, вычисляемое (развёртка, гибы, вес,
// эскиз) пересчитывает сервер, как у новой строки. Заказ становится
// изменённым и сохраняется вместе с остальными правками, как обычно.

import { Component, toRaw } from "@odoo/owl";
import { registry } from "@web/core/registry";

// Поля, которые в списке скрыты (column_invisible), но копия должна их
// взять: ядро не копирует скрытое и только-для-чтения. Чертёж профиля —
// главное, ради чего копируют; ширина рулона — параметр позиции.
//
// Толщины (thickness) здесь нет и не нужно: с 01.10.2026 она считается на
// сервере от металла (dobor.py, _compute_thickness), и копия получает ту же
// толщину, что исходная, — по тому же металлу. В печатном листе одна толщина
// и один вес на один металл.
const COPY_FIELDS = ["profile_snapshot_json", "coil_width"];

// Имя «Доборка N» ставит сервер сам, пока имени нет (dobor.py,
// _fill_default_titles). У копии такой позиции — следующий свободный номер,
// а не второй «Доборка 2» в производственном листе. Своё имя («Отлив»)
// копируется как есть: один профиль — одно название. Копия позиции БЕЗ
// имени остаётся без имени: номера подряд ей и исходной даст сервер при
// сохранении.
const AUTO_TITLE = /^Доборка \d+$/;

export class PmkDoborCopyLine extends Component {
    static template = "pmk_calc.DoborCopyLine";
    static props = { "*": true };

    /** Вложенный список, в котором стоит эта строка (позиции заказа). */
    get list() {
        const record = this.props.record;
        const parent = record?._parentRecord;
        if (!parent) {
            return null;
        }
        for (const value of Object.values(parent.data)) {
            if (value && Array.isArray(value.records) && indexOfRecord(value, record) >= 0) {
                return value;
            }
        }
        return null;
    }

    get canCopy() {
        const parent = this.props.record?._parentRecord;
        return Boolean(parent && parent.isInEdition && this.list);
    }

    async onClick() {
        const list = this.list;
        if (!list) {
            return;
        }
        const source = this.props.record;
        await list.duplicateRecords([source], { copyFields: COPY_FIELDS });
        if (AUTO_TITLE.test((source.data.title || "").trim())) {
            // После копирования список отсортирован по порядку: копия —
            // следующая за исходной.
            const index = indexOfRecord(list, source);
            const copy = index >= 0 ? list.records[index + 1] : null;
            if (copy && copy.isNew) {
                await copy.update({ title: nextAutoTitle(list) });
            }
        }
    }
}

/** Место записи в списке — по самой записи, а не по её реактивной обёртке. */
function indexOfRecord(list, record) {
    const raw = toRaw(record);
    return list.records.findIndex((r) => toRaw(r) === raw);
}

/**
 * «Доборка N» для копии: N — число позиций в заказе (копия — последняя
 * заведённая), а занятое имя пропускаем. Так же нумерует сервер
 * (dobor.py, _fill_default_titles): после удаления позиций счёт по
 * количеству может попасть на существующее имя.
 */
export function nextAutoTitle(list) {
    const taken = new Set(list.records.map((r) => (r.data.title || "").trim()));
    let number = list.count;
    while (taken.has(`Доборка ${number}`)) {
        number++;
    }
    return `Доборка ${number}`;
}

registry.category("view_widgets").add("pmk_dobor_copy_line", {
    component: PmkDoborCopyLine,
    listViewWidth: 120,
});
