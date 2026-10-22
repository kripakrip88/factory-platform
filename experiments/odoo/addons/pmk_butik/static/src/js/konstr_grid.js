/** @odoo-module **/
/**
 * «Конструкции» — таблица Бутика внутри расчёта (шаг 2, Антон 20.10.2026):
 * <widget name="pmk_konstr_grid"/> во вкладке «Конструкции».
 *
 * Та же таблица, что у отдельного Бутика (js/butik_grid.js), но строки — состав
 * расчёта: изделия и детали pmk.metal.spec (методы konstr_*, models/konstr.py).
 * Отличия: у изделия — цена клиенту за шт, у строк — металл ₽ по прайсам.
 *
 * Переключатель «Таблица / Подробно»: «Подробно» — прежний редактор состава
 * (раскладка листа, «на разнос», цена закупки строкой); выбор помнится в
 * браузере. В режиме таблицы прежний редактор спрятан стилем (konstr_grid.scss).
 * Уход в «Подробно» перечитывает форму — редактор видит правки таблицы; возврат
 * в таблицу сначала сохраняет правки редактора.
 */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { PmkButikGrid } from "./butik_grid";
import { clearPending, pendingPrices, savePending, setPending } from "./price_pending";

const METHODS = {
    butik_rows: "konstr_rows",
    butik_save_row: "konstr_save_row",
    butik_insert_rows: "konstr_insert_rows",
    butik_delete_row: "konstr_delete_row",
    butik_duplicate_row: "konstr_duplicate_row",
    butik_add_product: "konstr_add_product",
    butik_set_position: "konstr_set_position",
    butik_move_row: "konstr_move_row",
};
const MODE_KEY = "pmk_konstr_mode";

function readMode() {
    try {
        return window.localStorage.getItem(MODE_KEY) === "detail" ? "detail" : "table";
    } catch {
        return "table";
    }
}

export class PmkKonstrGrid extends PmkButikGrid {
    static template = "pmk_butik.KonstrGrid";
    static MODEL = "pmk.metal.spec";

    setup() {
        super.setup();
        this.view = useState({ mode: readMode() });
        // №314: несохранённые ручные цены (js/price_pending.js) — общие для формы расчёта.
        this.pending = useState(pendingPrices);
    }

    // ─── №314: ручная цена за тонну — кнопкой «Сохранить цены», не сама ──
    get pendingBucket() {
        return (this.specId && this.pending[this.specId]) || {};
    }

    get pendingCount() {
        return Object.keys(this.pendingBucket).length;
    }

    isPending(row) {
        return row.kind === "detail" && Boolean(this.pendingBucket[row.id]);
    }

    val(row, key) {
        if (key === "metal_ton" && this.isPending(row) && this.drafts[`${row.id}:${key}`] === undefined) {
            return this.pendingBucket[row.id].value;
        }
        return super.val(row, key);
    }

    _pendingName(row) {
        return [row.pos, row.name].filter((part) => part).join(" · ");
    }

    async commit(row, col, ev) {
        if (col !== "metal_ton" || row.kind !== "detail") {
            return super.commit(row, col, ev);
        }
        const raw = ev.target.value.trim();
        delete this.drafts[`${row.id}:${col}`];
        setPending(this.specId, row.id, {
            name: this._pendingName(row), old: row.manual ? String(row.metal_ton) : "", value: raw,
        });
    }

    async savePrices() {
        if (this.state.busy) {
            return;
        }
        this.state.busy = true;
        try {
            const data = await savePending(this.orm, this.specId);
            if (data && this.alive()) {
                this.state.data = data;
                this.state.savedAt = new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
                await this.refreshHead();
            }
        } finally {
            if (this.alive()) {
                this.state.busy = false;
            }
        }
    }

    discardPrices() {
        clearPending(this.specId);
    }

    method(name) {
        return METHODS[name] || name;
    }

    colsOf(row) {
        if (row.kind === "product") {
            return ["name", "product_qty", "price_ton", "price"];
        }
        // №314: нет цены в прайсах — «Цена за т» детали вписывается руками.
        return [...super.colsOf(row), "mass", ...(row.can_manual ? ["metal_ton"] : [])];
    }

    /** №314: цена, вписанная вручную в другом расчёте, — в эту деталь по щелчку (до «Сохранить цены»). */
    useManualHint(row) {
        if (row.manual_hint) {
            setPending(this.specId, row.id, {
                name: this._pendingName(row), old: "", value: String(row.manual_hint.price),
            });
        }
    }

    saved(row, key) {
        // Цена — с разрядами («14 560»): так её читают; ввод понимает и без них
        // (сервер убирает пробелы, _to_float).
        if (key === "price" || key === "price_ton" || key === "metal_ton" || key === "mass") {
            // «Вес всего» — только масса по КМ; вес по размерам виден серым (placeholder).
            const value = row[key];
            return value ? value.toLocaleString("ru-RU", { maximumFractionDigits: 2 }) : "";
        }
        return super.saved(row, key);
    }

    money(value) {
        return value ? Math.round(value).toLocaleString("ru-RU") : "";
    }

    async setMode(mode) {
        if (mode === this.view.mode) {
            return;
        }
        const record = this.props.record;
        if (mode === "table" && (await record.isDirty())) {
            // Правки прежнего редактора — сначала в базу, иначе таблица их не увидит.
            const saved = await record.save();
            if (!saved) {
                return;
            }
        }
        this.view.mode = mode;
        try {
            window.localStorage.setItem(MODE_KEY, mode);
        } catch {
            // приватное окно — помним до перезагрузки
        }
        if (mode === "detail") {
            await this.refreshHead();
        } else {
            await this.load();
        }
    }

    async remove() {
        const row = this.selRow;
        if (row && row.kind === "product" && this.childCount(row.id)) {
            this.env.services.dialog.add(ConfirmationDialog, {
                title: _t("Удалить изделие"),
                body: _t("Изделие «%s» удалится вместе с деталями (%s). Продолжить?", row.name, this.childCount(row.id)),
                confirmLabel: _t("Удалить"),
                confirm: () => super.remove(),
                cancel: () => {},
            });
            return;
        }
        return super.remove();
    }
}

registry.category("view_widgets").add("pmk_konstr_grid", { component: PmkKonstrGrid });
