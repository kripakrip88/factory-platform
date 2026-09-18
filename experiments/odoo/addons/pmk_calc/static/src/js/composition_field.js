/**
 * Состав изделий с раскрытием — живой, без сохранения документа.
 *
 * Прежняя версия собиралась на сервере и показывала прежнее состояние, пока
 * документ не сохранён. Этот виджет читает данные ИЗ ПАМЯТИ формы, поэтому
 * правка детали видна сразу: и в составе, и в весах.
 *
 * Чтобы состав был в памяти, вложенные строки перечислены в разметке поля
 * (см. metal_spec_views.xml). Без этого Odoo их просто не загрузит: в списке
 * подгружаются только те поля, которые в нём объявлены.
 *
 * Виджет только показывает. Ввод остаётся в таблице изделий выше: смешивать
 * чтение и правку в одном месте — как раз тот случай, когда в списке
 * появляются пустые колонки и лишние клики.
 */

import { registry } from "@web/core/registry";
import { Component, useState } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const SECTIONS = [
    { mode: "linear", title: "Линейный прокат" },
    { mode: "sheet", title: "Листовой прокат" },
    { mode: "fastener", title: "Метизы" },
    { mode: "paint", title: "Лакокрасочное покрытие" },
];

export class CompositionField extends Component {
    static template = "pmk_calc.CompositionField";
    static props = { ...standardFieldProps };

    setup() {
        // Раскрытие держим по индексу изделия: записи до сохранения не имеют
        // постоянного идентификатора, и ключом он быть не может.
        this.ui = useState({ open: { 0: true } });
    }

    get products() {
        const list = this.props.record.data[this.props.name];
        const records = (list && list.records) || [];
        return records.map((rec, index) => {
            const d = rec.data;
            const lines = ((d.line_ids && d.line_ids.records) || []).map((l) => l.data);
            return {
                index,
                name: d.name || "Без названия",
                qty: d.qty || 0,
                weightOne: d.weight_one || 0,
                weightTotal: d.weight_total || 0,
                sections: SECTIONS.map((s) => ({
                    title: s.title,
                    rows: lines.filter((l) => l.calc_mode === s.mode).map((l) => this.row(l)),
                })).filter((s) => s.rows.length),
            };
        });
    }

    /** Что показывать в «позиции» и «размерах» — зависит от вида детали. */
    row(line) {
        const name = (rel) => (rel && rel.display_name) || "—";
        const num = (v) => (v || 0).toLocaleString("ru-RU", { maximumFractionDigits: 3 });
        let what = "—";
        let size = "";
        if (line.calc_mode === "linear") {
            what = name(line.profile_id);
            size = `${num(line.length_mm)} мм`;
        } else if (line.calc_mode === "sheet") {
            what = name(line.sheet_id);
            size = `${num(line.a_mm)}×${num(line.b_mm)} мм`;
        } else if (line.calc_mode === "fastener") {
            what = name(line.fastener_id);
        } else {
            what = name(line.paint_id);
            // Толщину показываем всегда: именно она объясняет расход, и без
            // неё цифра выглядит взятой с потолка.
            const thickness = line.paint_thickness_um
                ? `, ${num(line.paint_thickness_um)} мкм`
                : "";
            size = line.area_m2
                ? `${num(line.area_m2)} м²${thickness}`
                : "площадь не задана";
        }
        return {
            detail: line.detail_name || "—",
            what,
            size,
            qty: line.qty || 0,
            weight: num(line.weight_total),
        };
    }

    toggle(index) {
        this.ui.open[index] = !this.ui.open[index];
    }

    fmt(value) {
        return (value || 0).toLocaleString("ru-RU", {
            minimumFractionDigits: 3, maximumFractionDigits: 3,
        });
    }
}

registry.category("fields").add("pmk_composition", {
    component: CompositionField,
    supportedTypes: ["one2many"],
    relatedFields: () => [
        { name: "name", type: "char" },
        { name: "qty", type: "integer" },
        { name: "weight_one", type: "float" },
        { name: "weight_total", type: "float" },
    ],
});
