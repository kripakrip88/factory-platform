/** @odoo-module **/
/**
 * Бутик — таблица спецификации как в Excel (15.10.2026) — <widget name="pmk_butik_grid"/>.
 *
 * Антон 15.10: «для Бутова — отдельный модуль… при открытии — такая таблица… в строках
 * умный поиск по номенклатуре, как в основной системе». Прототип принят в чате.
 *
 * Строки живут на сервере (pmk.butik.spec.butik_*): правка ячейки уходит при выходе из
 * неё, ответ — таблица целиком (вес, распознавание, номера изделий). Клавиатура: Enter и
 * ↓/↑ — строка ниже/выше (в конце — новая), Tab — штатно вправо, Ctrl+D — значение
 * сверху, Ctrl+V блоком из Excel — новые строки «№ | наименование | длина | кол-во |
 * марка». Наименование: подсказки умного поиска справочников, щелчок — позиция выбрана.
 *
 * Сервисы — env.services (грабля шага 31), ответ после закрытия формы не пишем.
 */
import { Component, onPatched, status, useEffect, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

const NUMERIC = new Set(["width", "length_mm", "qty", "product_qty"]);

function fmt(value, digits = 1) {
    if (!value) {
        return "";
    }
    return (Math.round(value * 10 ** digits) / 10 ** digits).toLocaleString("ru-RU");
}

export class PmkButikGrid extends Component {
    static template = "pmk_butik.Grid";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = this.env.services.orm;
        this.notification = this.env.services.notification;
        this.root = useRef("root");
        this.state = useState({
            data: null, loading: true, sel: { row: 0, col: "name" }, busy: false,
            suggest: null, suggestRow: null,
        });
        this.pendingFocus = null;
        this.suggestTimer = null;
        // Набранное, но ещё не сохранённое: OWL при каждой перерисовке ставит
        // input.value из шаблона (сравнивает с живым значением поля), и без
        // черновика текст стирался, как только появлялись подсказки.
        this.drafts = {};
        useEffect(
            (resId) => {
                this.load(resId);
            },
            () => [this.props.record.resId]
        );
        onPatched(() => this.applyFocus());
    }

    alive() {
        return status(this) !== "destroyed";
    }

    get specId() {
        return this.props.record.resId || false;
    }

    get rows() {
        return this.state.data?.rows || [];
    }

    async call(method, args = []) {
        if (!this.specId) {
            return;
        }
        this.state.busy = true;
        try {
            const data = await this.orm.call("pmk.butik.spec", method, [[this.specId], ...args]);
            if (this.alive() && data) {
                this.state.data = data;
            }
        } finally {
            if (this.alive()) {
                this.state.busy = false;
            }
        }
    }

    async load(resId = this.specId) {
        if (!resId) {
            this.state.loading = false;
            return;
        }
        this.state.loading = true;
        const data = await this.orm.call("pmk.butik.spec", "butik_rows", [[resId]]);
        if (this.alive()) {
            this.state.data = data;
            this.state.loading = false;
        }
    }

    // ─── отображение ────────────────────────────────────────────────────
    val(row, key) {
        const draft = this.drafts[`${row.id}:${key}`];
        return draft !== undefined ? draft : this.saved(row, key);
    }

    saved(row, key) {
        const value = row[key];
        if (NUMERIC.has(key)) {
            return value ? String(value).replace(".", ",") : "";
        }
        return value || "";
    }

    isNum(col) {
        return NUMERIC.has(col);
    }

    kg(value) {
        // Метиз весит граммы: «0,028», а не «0».
        return fmt(value, value && Math.abs(value) < 1 ? 3 : 1);
    }

    total(row) {
        return fmt(row.qty_total, 2);
    }

    isSel(index, col) {
        return this.state.sel.row === index && this.state.sel.col === col;
    }

    // ─── фокус ──────────────────────────────────────────────────────────
    focusCell(index, col) {
        this.pendingFocus = { index, col };
        this.state.sel = { row: index, col };
        this.applyFocus();
    }

    applyFocus() {
        const target = this.pendingFocus;
        if (!target || !this.root.el) {
            return;
        }
        const input = this.root.el.querySelector(
            `input[data-index="${target.index}"][data-col="${target.col}"]`);
        if (input) {
            this.pendingFocus = null;
            input.focus();
            input.select();
        }
    }

    onFocus(index, col) {
        this.state.sel = { row: index, col };
    }

    // ─── правка ─────────────────────────────────────────────────────────
    onInput(row, index, col, ev) {
        this.drafts[`${row.id}:${col}`] = ev.target.value;
        if (col === "name" && row.kind !== "product") {
            this.onNameInput(index, ev);
        }
    }

    async commit(row, col, ev) {
        const key = `${row.id}:${col}`;
        const raw = ev.target.value;
        if (raw === this.saved(row, col)) {
            delete this.drafts[key];
            return;
        }
        this.drafts[key] = raw;
        try {
            await this.call("butik_save_row", [row.id, { [col]: raw }]);
        } finally {
            delete this.drafts[key];
        }
    }

    async onKeydown(index, col, ev) {
        const row = this.rows[index];
        if (ev.key === "Enter" || ev.key === "ArrowDown" || ev.key === "ArrowUp") {
            if (this.state.suggest && ev.key !== "Enter") {
                return;
            }
            ev.preventDefault();
            await this.commit(row, col, ev);
            let next = index + (ev.key === "ArrowUp" ? -1 : 1);
            if (next < 0) {
                next = 0;
            }
            if (next >= this.rows.length) {
                await this.call("butik_save_row", [false, { after_id: this.rows[this.rows.length - 1]?.id }]);
            }
            this.closeSuggest();
            const nextRow = this.rows[next];
            let nextCol = nextRow && nextRow.kind === "product" ? (col === "qty" ? "product_qty" : "name")
                : (col === "product_qty" ? "qty" : col);
            if (nextCol === "width" && nextRow && !nextRow.is_sheet) {
                nextCol = "length_mm";
            }
            this.focusCell(next, nextCol);
        } else if (ev.key === "Tab" && !ev.shiftKey && col === "name" && row.kind !== "product") {
            // Колонка «Ширина» появляется, когда строка узнана как лист, —
            // после сохранения наименования; туда и переходим.
            ev.preventDefault();
            await this.commit(row, col, ev);
            this.closeSuggest();
            const saved = this.rows[index];
            this.focusCell(index, saved && saved.is_sheet ? "width" : "length_mm");
        } else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "d") {
            ev.preventDefault();
            for (let j = index - 1; j >= 0; j--) {
                const above = this.rows[j];
                if (above.kind === row.kind && this.val(above, col) !== "") {
                    ev.target.value = this.val(above, col);
                    await this.commit(row, col, ev);
                    this.focusCell(index, col);
                    break;
                }
            }
        } else if (ev.key === "Escape") {
            this.closeSuggest();
        }
    }

    async onPaste(index, ev) {
        const text = ev.clipboardData?.getData("text") || "";
        if (!text.includes("\t") && !text.includes("\n")) {
            return;
        }
        ev.preventDefault();
        const rows = text.replace(/\r/g, "").split("\n").filter((line) => line.trim())
            .map((line) => {
                if (!line.includes("\t")) {
                    // Столбик коротких строк «д1 шв10 1200мм 10шт 09г» — сервер расшифрует.
                    return { name: line.trim() };
                }
                const p = line.split("\t");
                return { pos: p[0] || "", name: p[1] || "", length_mm: p[2] || "", qty: p[3] || "", grade: p[4] || "" };
            });
        await this.call("butik_insert_rows", [this.rows[index]?.id || false, rows]);
        this.notification.add(_t("Вставлено строк: %s", rows.length), { type: "success" });
    }

    // ─── подсказки наименования ─────────────────────────────────────────
    onNameInput(index, ev) {
        const query = ev.target.value;
        clearTimeout(this.suggestTimer);
        this.suggestTimer = setTimeout(async () => {
            if (query.trim().length < 2) {
                this.closeSuggest();
                return;
            }
            const items = await this.orm.call("pmk.butik.spec", "butik_suggest", [query]);
            if (this.alive()) {
                this.state.suggest = items.length ? items : null;
                this.state.suggestRow = index;
            }
        }, 250);
    }

    closeSuggest() {
        this.state.suggest = null;
        this.state.suggestRow = null;
    }

    async choose(index, item, ev) {
        ev.preventDefault();
        const input = this.root.el.querySelector(`input[data-index="${index}"][data-col="name"]`);
        const row = this.rows[index];
        if (input && input.value !== row.name) {
            await this.call("butik_save_row", [row.id, { name: input.value }]);
        }
        delete this.drafts[`${row.id}:name`];
        await this.call("butik_set_position", [row.id, item.key]);
        this.closeSuggest();
        this.focusCell(index, "length_mm");
    }

    // ─── кнопки ─────────────────────────────────────────────────────────
    get selRow() {
        return this.rows[this.state.sel.row];
    }

    async addRow() {
        await this.call("butik_save_row", [false, { after_id: this.selRow?.id || false }]);
        this.focusCell(Math.min(this.state.sel.row + 1, this.rows.length - 1), "name");
    }

    async addProduct() {
        await this.call("butik_add_product");
        this.focusCell(this.rows.length - 2, "name");
    }

    async duplicate() {
        if (this.selRow) {
            await this.call("butik_duplicate_row", [this.selRow.id]);
            this.focusCell(this.state.sel.row + 1, this.state.sel.col);
        }
    }

    async remove() {
        if (this.selRow) {
            await this.call("butik_delete_row", [this.selRow.id]);
            this.focusCell(Math.max(0, this.state.sel.row - 1), "name");
        }
    }
}

registry.category("view_widgets").add("pmk_butik_grid", { component: PmkButikGrid });
