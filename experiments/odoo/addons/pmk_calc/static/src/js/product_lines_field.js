/**
 * Список изделий с составом, раскрывающимся под строкой.
 *
 * Odoo не умеет вкладывать таблицу в таблицу, а состав хотелось видеть там
 * же, где изделия, а не отдельным блоком. Поэтому вклиниваемся в разметку
 * строк списка: после строки каждого изделия добавляем свою, со составом.
 *
 * Наследование ПЕРВИЧНОЕ (t-inherit-mode="primary"): расширение изменило бы
 * ВСЕ списки в системе, а нам нужен только этот. Свой рендерер просто
 * указывает на новый шаблон строк.
 *
 * Ввод остаётся штатным: добавление, удаление, перетаскивание и открытие
 * изделия работают как раньше — мы ничего не перехватываем, только дорисовываем.
 */

import { registry } from "@web/core/registry";
import { ListRenderer } from "@web/views/list/list_renderer";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";

const SECTIONS = [
    { mode: "linear", title: "Линейный прокат" },
    { mode: "sheet", title: "Листовой прокат" },
    { mode: "fastener", title: "Метизы" },
    { mode: "paint", title: "Лакокрасочное покрытие" },
];

export class ProductLinesRenderer extends ListRenderer {
    static rowsTemplate = "pmk_calc.ProductRows";

    /** Число колонок под составом: занимаем всю ширину строки. */
    get compositionColspan() {
        return this.nbCols;
    }

    /** Состав изделия, разложенный по разделам. Данные берутся из памяти
        формы, поэтому правки видны сразу, без сохранения документа. */
    composition(record) {
        const lines = ((record.data.line_ids && record.data.line_ids.records) || [])
            .map((l) => l.data);
        return SECTIONS.map((section) => ({
            title: section.title,
            rows: lines
                .filter((l) => l.calc_mode === section.mode)
                .map((l) => this.compositionRow(l)),
        })).filter((section) => section.rows.length);
    }

    countLines(record) {
        return ((record.data.line_ids && record.data.line_ids.records) || []).length;
    }

    /** Что показывать в «позиции» и «размерах» — зависит от вида детали:
        у проката длина, у листа две стороны, у метиза размеров нет вовсе. */
    compositionRow(line) {
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
            // Толщину показываем всегда: именно она объясняет расход краски.
            const th = line.paint_thickness_um ? `, ${num(line.paint_thickness_um)} мкм` : "";
            size = line.area_m2 ? `${num(line.area_m2)} м²${th}` : "площадь не задана";
        }
        return {
            detail: line.detail_name || "—",
            what,
            size,
            qty: line.qty || 0,
            weight: num(line.weight_total),
        };
    }
}

export class ProductLinesField extends X2ManyField {
    static components = { ...X2ManyField.components, ListRenderer: ProductLinesRenderer };
}

registry.category("fields").add("pmk_product_lines", {
    ...x2ManyField,
    component: ProductLinesField,
});
