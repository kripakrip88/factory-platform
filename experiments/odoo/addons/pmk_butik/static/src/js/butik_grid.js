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
import { Component, onMounted, onPatched, status, useEffect, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

const NUMERIC = new Set(["width", "length_mm", "qty", "product_qty", "price"]);

function fmt(value, digits = 1) {
    if (!value) {
        return "";
    }
    return (Math.round(value * 10 ** digits) / 10 ** digits).toLocaleString("ru-RU");
}

export class PmkButikGrid extends Component {
    static template = "pmk_butik.Grid";
    static props = { ...standardWidgetProps };
    // Где живут строки. Наследник «Конструкции» (js/konstr_grid.js) берёт ту же
    // таблицу, но строки — состав расчёта (pmk.metal.spec, методы konstr_*).
    static MODEL = "pmk.butik.spec";

    method(name) {
        return name;
    }

    setup() {
        this.orm = this.env.services.orm;
        this.notification = this.env.services.notification;
        this.root = useRef("root");
        this.state = useState({
            data: null, loading: true, sel: { row: 0, col: "name" }, busy: false,
            suggest: null, suggestRow: null, suggestIdx: -1, savedAt: "",
        });
        this.pendingFocus = null;
        this.suggestTimer = null;
        // Набранное, но ещё не сохранённое: OWL при каждой перерисовке ставит
        // input.value из шаблона (сравнивает с живым значением поля), и без
        // черновика текст стирался, как только появлялись подсказки.
        this.drafts = {};
        // Свёрнутые изделия — только вид, на сервере не храним.
        this.collapsed = useState(new Set());
        useEffect(
            (resId) => {
                this.load(resId);
            },
            () => [this.props.record.resId]
        );
        onMounted(() => this.autosize());
        onPatched(() => {
            this.autosize();
            this.applyFocus();
            this.root.el?.querySelector(".o_pmk_butik__sitem--active")?.scrollIntoView({ block: "nearest" });
        });
    }

    /**
     * Карточка «Общий вес» и счётчики шапки — вычисляемые поля формы: строки
     * таблицы пишутся мимо формы, и шапка показывала 0 (Антон 16.10). Перечитать
     * запись, только если в шапке нет несохранённых правок — их не затираем.
     */
    async refreshHead() {
        const record = this.props.record;
        if (!record.resId || (await record.isDirty()) || !this.alive()) {
            return;
        }
        await record.model.mutex.exec(() => record._load());
    }

    async start() {
        // Новый расчёт: таблице нужен номер записи — сохраняем шапку сами.
        await this.props.record.save();
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
            const data = await this.orm.call(this.constructor.MODEL, this.method(method), [[this.specId], ...args]);
            if (this.alive() && data) {
                this.state.data = data;
                // «Сохранено в 14:32»: ячейка уходит на сервер сразу, отдельной
                // кнопки «Сохранить» у таблицы нет (Антон 16.10 спрашивал, где она).
                this.state.savedAt = new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
                await this.refreshHead();
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
        const data = await this.orm.call(this.constructor.MODEL, this.method("butik_rows"), [[resId]]);
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

    /** Ячейки строки слева направо — для ← →. «Ширина» — только у листа. */
    colsOf(row) {
        if (row.kind === "product") {
            return ["name", "product_qty"];
        }
        return ["pos", "name", ...(row.is_sheet ? ["width"] : []), "length_mm", "qty", "grade"];
    }

    isCollapsed(productId) {
        return Boolean(productId) && this.collapsed.has(productId);
    }

    childCount(productId) {
        return this.rows.filter((r) => r.parent === productId && r.name).length;
    }

    get allOpen() {
        return this.collapsed.size === 0;
    }

    toggle(productId) {
        if (this.collapsed.has(productId)) {
            this.collapsed.delete(productId);
        } else {
            this.collapsed.add(productId);
        }
    }

    toggleAll() {
        if (this.allOpen) {
            for (const row of this.rows) {
                if (row.kind === "product") {
                    this.collapsed.add(row.id);
                }
            }
        } else {
            this.collapsed.clear();
        }
    }

    isSel(index, col) {
        return this.state.sel.row === index && this.state.sel.col === col;
    }

    // ─── фокус ──────────────────────────────────────────────────────────
    focusCell(index, col) {
        // У строки нет такой колонки (цена есть только у изделия) — наименование.
        const row = this.rows[index];
        if (row && !this.colsOf(row).includes(col)) {
            col = "name";
        }
        // Ищем ячейку по ключу строки, а не по номеру: ответ сервера уже в
        // state, а таблица перерисуется позже — по номеру фокус попадал в
        // старую строку на этом месте (20.10.2026: после «+ Строка» текст
        // набирался в соседнее изделие). Нет ещё такой строки — дождёмся onPatched.
        this.pendingFocus = { index, col, key: row ? String(row.id) : null };
        this.state.sel = { row: index, col };
        this.applyFocus();
    }

    applyFocus() {
        const target = this.pendingFocus;
        if (!target || !this.root.el) {
            return;
        }
        const input = target.key
            ? this.root.el.querySelector(`[data-key="${target.key}"][data-col="${target.col}"]`)
            : this.root.el.querySelector(`[data-index="${target.index}"][data-col="${target.col}"]`);
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
    // Высота наименования по тексту: длинное — в несколько строк.
    autosize(el = null) {
        const list = el ? [el] : this.root.el?.querySelectorAll("textarea.o_pmk_butik__ta") || [];
        for (const area of list) {
            area.style.height = "auto";
            area.style.height = `${area.scrollHeight}px`;
        }
    }

    onInput(row, index, col, ev) {
        this.drafts[`${row.id}:${col}`] = ev.target.value;
        if (ev.target.tagName === "TEXTAREA") {
            this.autosize(ev.target);
        }
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
        const suggestOpen = this.state.suggest && this.state.suggestRow === index;
        if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") {
            // Новое изделие с клавиатуры (Антон 16.10).
            ev.preventDefault();
            ev.stopPropagation();
            await this.commit(row, col, ev);
            this.closeSuggest();
            await this.addProduct();
            return;
        }
        if ((ev.key === "ArrowLeft" || ev.key === "ArrowRight") && !ev.shiftKey && !ev.altKey
                && !ev.ctrlKey && !ev.metaKey) {
            // ← → как в Excel (Антон 16.10): у края текста — в соседнюю ячейку,
            // внутри текста — курсор по буквам, как обычно.
            const el = ev.target;
            const len = el.value.length;
            const all = el.selectionStart === 0 && el.selectionEnd === len;
            const left = ev.key === "ArrowLeft";
            const edge = left ? el.selectionStart === 0 && el.selectionEnd === 0
                : el.selectionStart === len && el.selectionEnd === len;
            if (!edge && !all) {
                return;
            }
            const cols = this.colsOf(row);
            const next = cols[cols.indexOf(col) + (left ? -1 : 1)];
            if (!next) {
                return;
            }
            ev.preventDefault();
            await this.commit(row, col, ev);
            this.closeSuggest();
            const fresh = this.rows[index];
            this.focusCell(index, fresh && this.colsOf(fresh).includes(next) ? next
                : this.colsOf(fresh || row)[Math.max(0, cols.indexOf(col) + (left ? -1 : 1))]);
            return;
        }
        if (suggestOpen && (ev.key === "ArrowDown" || ev.key === "ArrowUp")) {
            // Стрелки ходят по подсказкам, Enter берёт выделенную (Антон 16.10).
            ev.preventDefault();
            const count = this.state.suggest.length;
            const step = ev.key === "ArrowDown" ? 1 : -1;
            // Положения: -1 (свой текст, ничего не выделено), 0…count-1 — по кругу.
            const pos = (this.state.suggestIdx + 1 + step + count + 1) % (count + 1);
            this.state.suggestIdx = pos - 1;
            return;
        }
        if (suggestOpen && ev.key === "Enter" && this.state.suggestIdx >= 0) {
            ev.preventDefault();
            await this.choose(index, this.state.suggest[this.state.suggestIdx], ev);
            return;
        }
        if (ev.key === "Enter" || ev.key === "ArrowDown" || ev.key === "ArrowUp") {
            ev.preventDefault();
            await this.commit(row, col, ev);
            const dir = ev.key === "ArrowUp" ? -1 : 1;
            let next = index + dir;
            while (next > 0 && next < this.rows.length && this.isCollapsed(this.rows[next].parent)) {
                next += dir;
            }
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
                this.state.suggestIdx = -1;
            }
        }, 250);
    }

    closeSuggest() {
        clearTimeout(this.suggestTimer);
        this.state.suggest = null;
        this.state.suggestRow = null;
        this.state.suggestIdx = -1;
    }

    async choose(index, item, ev) {
        ev.preventDefault();
        const input = this.root.el.querySelector(`[data-index="${index}"][data-col="name"]`);
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

    /**
     * Кнопки таблицы: курсор сначала уходит из ячейки (её правка сохранится
     * сама), и пока сервер отвечает, набранное никуда не попадает. Иначе на
     * медленном ответе буквы падали в прежнюю ячейку — в изделие над новой
     * строкой (20.10.2026, проверка «Конструкций» на копии).
     */
    releaseFocus() {
        const el = document.activeElement;
        if (el && this.root.el?.contains(el)) {
            el.blur();
        }
    }

    async addRow() {
        this.releaseFocus();
        await this.call("butik_save_row", [false, { after_id: this.selRow?.id || false }]);
        this.focusCell(Math.min(this.state.sel.row + 1, this.rows.length - 1), "name");
    }

    async addProduct() {
        this.releaseFocus();
        await this.call("butik_add_product");
        this.focusCell(this.rows.length - 2, "name");
    }

    async duplicate() {
        this.releaseFocus();
        if (this.selRow) {
            await this.call("butik_duplicate_row", [this.selRow.id]);
            this.focusCell(this.state.sel.row + 1, this.state.sel.col);
        }
    }

    async remove() {
        this.releaseFocus();
        if (this.selRow) {
            await this.call("butik_delete_row", [this.selRow.id]);
            this.focusCell(Math.max(0, this.state.sel.row - 1), "name");
        }
    }
}

registry.category("view_widgets").add("pmk_butik_grid", { component: PmkButikGrid });
