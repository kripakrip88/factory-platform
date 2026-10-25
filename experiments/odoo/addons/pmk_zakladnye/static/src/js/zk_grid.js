/** @odoo-module **/
/**
 * Закладные — таблица Бутика (25.10.2026) — <widget name="pmk_zk_grid"/>.
 *
 * Та же таблица, что у Бутика и болтов (pmk_butik/static/src/js/butik_grid.js): клавиши,
 * вставка столбика марок из Excel, сохранение ячейки при уходе. Строка — изделие
 * («мн 201-5 12шт»); состав и чертёж выбранной строки — панелью под таблицей
 * (прототип, принят 25.10.2026). Методы zk_* (models/grid.py).
 */
import { onWillUnmount, useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { PmkButikGrid } from "@pmk_butik/js/butik_grid";

const METHODS = {
    butik_rows: "zk_rows",
    butik_save_row: "zk_save_row",
    butik_insert_rows: "zk_insert_rows",
    butik_delete_row: "zk_delete_row",
    butik_duplicate_row: "zk_duplicate_row",
    butik_move_row: "zk_move_row",
    butik_add_product: "zk_add_product",
    butik_set_position: "zk_set_position",
};
const NUMERIC = new Set(["product_qty", "length"]);
// Пока чертежи рисуются — раз в 3 с забрать готовое (zk_rows смотрит файлы задания;
// база и процесс не нагружаются). Без этого ждать cron до минуты, а на копии cron выключен.
const POLL_MS = 3000;
const DRAW_ICON = { done: "fa-check", queued: "fa-hourglass-half", stale: "fa-refresh", error: "fa-exclamation-triangle" };

export class PmkZkGrid extends PmkButikGrid {
    static template = "pmk_zakladnye.ZkGrid";
    static MODEL = "pmk.zk.calc";

    setup() {
        super.setup();
        this.pollTimer = null;
        useEffect(
            (busy) => {
                if (busy && !this.pollTimer) {
                    this.pollTimer = setTimeout(() => this.poll(), POLL_MS);
                }
            },
            () => [this.state.data?.draw_busy, this.state.data]
        );
        onWillUnmount(() => clearTimeout(this.pollTimer));
    }

    async poll() {
        this.pollTimer = null;
        if (!this.alive() || !this.state.data?.draw_busy) {
            return;
        }
        await this.call("butik_rows");
        if (this.alive() && !this.state.data?.draw_busy) {
            // Чертежи готовы — карточка «Чертежи» и кнопка шапки.
            await this.props.record.load();
        }
    }

    method(name) {
        return METHODS[name] || name;
    }

    colsOf(row) {
        return row.pogon ? ["name", "length", "product_qty"] : ["name", "product_qty"];
    }

    isNum(col) {
        return NUMERIC.has(col);
    }

    saved(row, key) {
        const value = row[key];
        if (NUMERIC.has(key)) {
            return value ? String(value).replace(".", ",") : "";
        }
        return value || "";
    }

    // Марку разбирает сервер — подсказок справочника нет.
    onNameInput() {}

    drawIcon(row) {
        return DRAW_ICON[row.draw] || "";
    }

    /** Строка панели: выбранная, а если выбрана пустая — первая с составом. */
    get panelRow() {
        const sel = this.selRow;
        if (sel && sel.comp && sel.comp.length) {
            return sel;
        }
        return this.rows.find((r) => r.comp && r.comp.length) || null;
    }

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

registry.category("view_widgets").add("pmk_zk_grid", { component: PmkZkGrid });
