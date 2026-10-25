/** @odoo-module **/
/**
 * Опоры трубопроводов — таблица Бутика (25.10.2026) — <widget name="pmk_opora_grid"/>.
 *
 * Та же таблица, что у Бутика, «Конструкций» и болтов (pmk_bolt/static/src/js/bolt_grid.js):
 * клавиши, вставка из Excel, сохранение ячейки при уходе, свернуть/развернуть.
 * Опора — как изделие, под ней состав — как детали: корпус, рёбра, полухомуты, болты,
 * гайки, упоры. Методы opora_* (models/grid.py).
 */
import { registry } from "@web/core/registry";
import { PmkButikGrid } from "@pmk_butik/js/butik_grid";

const METHODS = {
    butik_rows: "opora_rows",
    butik_save_row: "opora_save_row",
    butik_insert_rows: "opora_insert_rows",
    butik_delete_row: "opora_delete_row",
    butik_duplicate_row: "opora_duplicate_row",
    butik_move_row: "opora_move_row",
    butik_add_product: "opora_add_product",
};
const NUMERIC = new Set(["product_qty", "qty", "markup", "price"]);

export class PmkOporaGrid extends PmkButikGrid {
    static template = "pmk_opora.OporaGrid";
    static MODEL = "pmk.opora.calc";

    method(name) {
        return METHODS[name] || name;
    }

    colsOf(row) {
        if (row.kind === "product") {
            return ["name", "product_qty", "markup", "price"];
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

    // У опор нет подсказок справочника: запись разбирает сервер.
    onNameInput() {}

    // «+ Опора» (Ctrl+Enter): новая опора встаёт последней — туда и курсор.
    async addProduct() {
        this.releaseFocus();
        await this.call("butik_add_product");
        this.focusCell(this.rows.length - 1, "name");
    }

    async onKeydown(index, col, ev) {
        if (ev.key === "Tab") {
            return;
        }
        return super.onKeydown(index, col, ev);
    }
}

registry.category("view_widgets").add("pmk_opora_grid", { component: PmkOporaGrid });
