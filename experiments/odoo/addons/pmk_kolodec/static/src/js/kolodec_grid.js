/** @odoo-module **/
/**
 * Металлоизделия колодцев — таблица Бутика (25.10.2026) — <widget name="pmk_kolodec_grid"/>.
 *
 * Та же таблица, что у Бутика, «Конструкций», болтов и опор (pmk_opora/static/src/js/opora_grid.js):
 * клавиши, вставка из Excel, сохранение ячейки при уходе, свернуть/развернуть.
 * Изделие (стремянка, МС, МН1, проставка, ЗО, К1) — строка изделия, под ней состав — как детали:
 * стойки, ступени, пластины, фланцы, шпильки. Методы kolodec_* (models/grid.py).
 */
import { registry } from "@web/core/registry";
import { PmkButikGrid } from "@pmk_butik/js/butik_grid";

const METHODS = {
    butik_rows: "kolodec_rows",
    butik_save_row: "kolodec_save_row",
    butik_insert_rows: "kolodec_insert_rows",
    butik_delete_row: "kolodec_delete_row",
    butik_duplicate_row: "kolodec_duplicate_row",
    butik_move_row: "kolodec_move_row",
    butik_add_product: "kolodec_add_product",
};
const NUMERIC = new Set(["product_qty", "qty", "markup", "price"]);

export class PmkKolodecGrid extends PmkButikGrid {
    static template = "pmk_kolodec.KolodecGrid";
    static MODEL = "pmk.kolodec.calc";

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

    // Подсказок справочника нет: запись разбирает сервер.
    onNameInput() {}

    // «+ Изделие» (Ctrl+Enter): новое изделие встаёт последним — туда и курсор.
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

registry.category("view_widgets").add("pmk_kolodec_grid", { component: PmkKolodecGrid });
