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
import { useState } from "@odoo/owl";
import { ListRenderer } from "@web/views/list/list_renderer";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";

const SECTIONS = [
    { mode: "linear", title: "Линейный прокат" },
    { mode: "sheet", title: "Листовой прокат" },
    { mode: "fastener", title: "Метизы" },
    { mode: "paint", title: "Лакокрасочное покрытие" },
];

// Состав правят во вкладках диалога, то есть через ОТФИЛЬТРОВАННЫЕ наборы.
// Общий line_ids при этом не обновляется — для Odoo это разные наборы данных,
// и счётчик показывал бы прежнее число до сохранения документа.
const LINE_FIELDS = ["line_linear_ids", "line_sheet_ids", "line_fastener_ids", "line_paint_ids"];

export class ProductLinesRenderer extends ListRenderer {
    static rowsTemplate = "pmk_calc.ProductRows";

    setup() {
        super.setup();
        // Раскрытие держим сами: браузерный <details> внутри таблицы Odoo
        // не открывается — клик по строке перехватывается списком.
        this.expanded = useState({});
    }

    /** Число колонок под составом: занимаем всю ширину строки. */
    get compositionColspan() {
        return this.nbCols;
    }

    isExpanded(record) {
        return !!this.expanded[record.id];
    }

    toggleComposition(record) {
        this.expanded[record.id] = !this.expanded[record.id];
    }

    /** Все детали изделия — из четырёх отфильтрованных наборов сразу. */
    allLines(record) {
        const lines = [];
        for (const field of LINE_FIELDS) {
            const list = record.data[field];
            for (const line of (list && list.records) || []) {
                lines.push(line.data);
            }
        }
        return lines;
    }

    /** Состав изделия, разложенный по разделам. Данные берутся из памяти
        формы, поэтому правки видны сразу, без сохранения документа. */
    composition(record) {
        const lines = this.allLines(record);
        return SECTIONS.map((section) => ({
            title: section.title,
            rows: lines
                .filter((l) => l.calc_mode === section.mode)
                .map((l) => this.compositionRow(l)),
        })).filter((section) => section.rows.length);
    }

    countLines(record) {
        return this.allLines(record).length;
    }

    /** «1 деталь», «3 детали», «7 деталей» — иначе счётчик читается коряво. */
    linesLabel(record) {
        const n = this.countLines(record);
        const last = n % 10;
        const teen = n % 100 >= 11 && n % 100 <= 14;
        if (!teen && last === 1) {
            return `${n} деталь`;
        }
        if (!teen && last >= 2 && last <= 4) {
            return `${n} детали`;
        }
        return `${n} деталей`;
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
