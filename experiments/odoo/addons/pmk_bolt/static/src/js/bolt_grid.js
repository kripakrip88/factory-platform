/** @odoo-module **/
/**
 * Фундаментные болты — таблица Бутика (21.10.2026, Антон: «почему строка ввода не
 * как в бутике? … принцип единообразия») — <widget name="pmk_bolt_grid"/>.
 *
 * Та же таблица, что у Бутика и «Конструкций» (pmk_butik/static/src/js/butik_grid.js):
 * клавиши, вставка из Excel, сохранение ячейки при уходе, свернуть/развернуть.
 * Болт — как изделие, под ним состав — как детали: круг, гайки, шайба, плита, работа
 * (Антон: «состав вида как у металлоизделия»). Методы bolt_* (models/grid.py).
 */
import { registry } from "@web/core/registry";
import { PmkButikGrid } from "@pmk_butik/js/butik_grid";

const METHODS = {
    butik_rows: "bolt_rows",
    butik_save_row: "bolt_save_row",
    butik_insert_rows: "bolt_insert_rows",
    butik_delete_row: "bolt_delete_row",
    butik_duplicate_row: "bolt_duplicate_row",
    butik_move_row: "bolt_move_row",
    butik_add_product: "bolt_add_product",
};
const NUMERIC = new Set(["product_qty", "qty", "markup", "price"]);

export class PmkBoltGrid extends PmkButikGrid {
    static template = "pmk_bolt.BoltGrid";
    static MODEL = "pmk.bolt.calc";

    method(name) {
        return METHODS[name] || name;
    }

    colsOf(row) {
        if (row.kind === "product") {
            return ["name", "product_qty", "nut_kind", "markup", "price"];
        }
        return ["name", "qty", "price"];
    }

    isNum(col) {
        return NUMERIC.has(col);
    }

    saved(row, key) {
        const value = row[key];
        if (key === "price") {
            return value ? value.toLocaleString("ru-RU", { maximumFractionDigits: 2 }) : "";
        }
        if (NUMERIC.has(key)) {
            return value ? String(value).replace(".", ",") : "";
        }
        return value || "";
    }

    money(value) {
        return value ? Math.round(value).toLocaleString("ru-RU") : "";
    }

    // У болтов нет подсказок справочника: запись разбирает сервер.
    onNameInput() {}

    // «+ Болт» (Ctrl+Enter): новый болт встаёт последним — туда и курсор.
    async addProduct() {
        this.releaseFocus();
        await this.call("butik_add_product");
        this.focusCell(this.rows.length - 1, "name");
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
