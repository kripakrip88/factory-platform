/** @odoo-module **/
/**
 * Фундаментные болты — таблица Бутика (21.10.2026, Антон: «почему строка ввода не
 * как в бутике? … принцип единообразия») — <widget name="pmk_bolt_grid"/>.
 *
 * Та же таблица, что у Бутика и «Конструкций» (pmk_butik/static/src/js/butik_grid.js):
 * клавиши, вставка из Excel, сохранение ячейки при уходе. Строки плоские — болт;
 * ячейка «Болт» — короткая запись «бф 2.1 м30 640мм ст3 10шт» (pmk_bolt/tools/parse.py),
 * под ней — название по ГОСТ, комплект, себестоимость, прошлые продажи. Методы bolt_*.
 */
import { registry } from "@web/core/registry";
import { PmkButikGrid } from "@pmk_butik/js/butik_grid";

const METHODS = {
    butik_rows: "bolt_rows",
    butik_save_row: "bolt_save_row",
    butik_insert_rows: "bolt_insert_rows",
    butik_delete_row: "bolt_delete_row",
    butik_duplicate_row: "bolt_duplicate_row",
};
const NUMERIC = new Set(["qty", "nut_price", "markup", "price"]);

export class PmkBoltGrid extends PmkButikGrid {
    static template = "pmk_bolt.BoltGrid";
    static MODEL = "pmk.bolt.calc";

    method(name) {
        return METHODS[name] || name;
    }

    colsOf() {
        return ["name", "qty", "nut_kind", "nut_price", "markup", "price"];
    }

    isNum(col) {
        return NUMERIC.has(col);
    }

    saved(row, key) {
        const value = row[key];
        if (key === "price" || key === "nut_price") {
            return value ? value.toLocaleString("ru-RU", { maximumFractionDigits: 2 }) : "";
        }
        if (key === "markup") {
            return value ? String(value).replace(".", ",") : "";
        }
        if (key === "qty") {
            return value ? String(value) : "";
        }
        return value || "";
    }

    money(value) {
        return value ? Math.round(value).toLocaleString("ru-RU") : "";
    }

    // У болтов нет подсказок справочника: запись разбирает сервер.
    onNameInput() {}

    // Новое изделие (Ctrl+Enter у Бутика) — у болтов просто новая строка.
    async addProduct() {
        return this.addRow();
    }

    async onKeydown(index, col, ev) {
        if (ev.key === "Tab") {
            // Tab — штатно в соседнюю ячейку (у Бутика из наименования — в «Ширину»/«Длину»).
            return;
        }
        return super.onKeydown(index, col, ev);
    }
}

registry.category("view_widgets").add("pmk_bolt_grid", { component: PmkBoltGrid });
