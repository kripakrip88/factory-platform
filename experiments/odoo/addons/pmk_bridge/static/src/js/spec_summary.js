/** @odoo-module **/
/**
 * Вкладка «Металлоизделия» — сводка всех изделий расчёта (Антон 20.10.2026).
 *
 * Строки — поле pmk_summary (models/spec_summary.py): конструкции, доборка,
 * вентзонты. Строка раскрывается стрелкой и показывает состав — только
 * смотреть («можно раскрыть, но не редактировать»); правят во вкладке своего
 * калькулятора. Что раскрыто — помнится, пока открыта форма.
 *
 * Ввод строк (Антон 22.10.2026: «забиваем общий список, а потом разносим по
 * категориям»): строка внизу таблицы, как в Бутике — Enter заводит строку,
 * Ctrl+V — столбик из Excel или письма. Сервер (models/spec_entry.py) сам
 * раскладывает по категориям: «дэ …» — доборка, «зонт …» — вентзонты, «бф …» —
 * болты, остальное — «Конструкции». Ошиблась категория — «Перенести в…».
 */
import { Component, markup, status, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const SOURCES = {
    metal: { label: "Конструкции", tab: "Конструкции" },
    manual: { label: "Вручную", tab: "Конструкции" },
    dobor: { label: "Доборка", tab: "Доборные элементы" },
    vent: { label: "Вентзонты", tab: "Вентзонты" },
};

const NUM = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });
const NUM1 = new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const MONEY = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });

export class SpecSummaryField extends Component {
    static template = "pmk_bridge.SpecSummaryField";
    static props = { ...standardFieldProps };

    setup() {
        this.open = useState({});
        this.entry = useState({ text: "", busy: false, over: null });
        this.dragArmed = false;
        this.dragKey = null;
        this.sources = SOURCES;
        this.notification = this.env.services.notification;
        this.orm = this.env.services.orm;
    }

    /** Форма открыта на правку (у кого нет прав — только смотреть). */
    get canEdit() {
        return this.props.record.isInEdition;
    }

    /** Строка ещё ничья: у изделия нет деталей, у доборки — нарисованного профиля. */
    canMove(row) {
        if (row.source === "metal") {
            return false;
        }
        return !(row.source === "dobor" && row.dobor && row.dobor.developed);
    }

    get targets() {
        return Object.entries(this.sources)
            .filter(([key]) => key !== "manual")
            .map(([key, src]) => ({ key, label: src.label }));
    }

    /** Новый или правленный расчёт — сначала сохранить: серверу нужен номер и шапка. */
    async _ready() {
        const record = this.props.record;
        if (!record.resId || (await record.isDirty())) {
            if (!(await record.save())) {
                return false;
            }
        }
        return record.resId;
    }

    async _reload() {
        const record = this.props.record;
        if (status(this) !== "destroyed") {
            await record.model.mutex.exec(() => record._load());
        }
    }

    async add(texts) {
        texts = texts.map((t) => t.trim()).filter((t) => t);
        if (!texts.length || this.entry.busy) {
            return;
        }
        this.entry.busy = true;
        try {
            const resId = await this._ready();
            if (!resId) {
                return;
            }
            const res = await this.orm.call("pmk.metal.spec", "pmk_summary_add", [[resId], texts]);
            const added = Object.entries(res.added || {}).map(([cat, n]) => `${cat} — ${n}`);
            if (added.length) {
                this.entry.text = "";
                this.notification.add(_t("Добавлено: %s", added.join(", ")), { type: "success" });
            }
            for (const error of res.errors || []) {
                this.notification.add(error, { type: "warning", sticky: true });
            }
            await this._reload();
        } finally {
            if (status(this) !== "destroyed") {
                this.entry.busy = false;
            }
        }
    }

    onEntryInput(ev) {
        this.entry.text = ev.target.value;
    }

    onEntryKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.add([this.entry.text]);
        }
    }

    onEntryPaste(ev) {
        const text = ev.clipboardData?.getData("text") || "";
        if (!text.includes("\n") && !text.includes("\t")) {
            return;
        }
        ev.preventDefault();
        // Столбик строк; колонки Excel — через пробел в одну запись.
        const lines = text.replace(/\r/g, "").split("\n")
            .map((line) => line.split("\t").map((c) => c.trim()).filter((c) => c).join(" "));
        this.add(lines);
    }

    // ─── №312: перетащить, копировать, удалить (Голубенко, Антон 23.10.2026) ──
    // Порядок строк сводки — сквозной, он же порядок в КП и счёте.
    armDrag() {
        this.dragArmed = true;
    }

    onDragStart(row, ev) {
        if (!this.dragArmed || !this.canEdit) {
            ev.preventDefault();
            return;
        }
        this.dragKey = row.key;
        ev.dataTransfer.effectAllowed = "move";
        ev.dataTransfer.setData("text/plain", row.key);
        ev.currentTarget.classList.add("o_pmk_summary__dragging");
    }

    onDragEnd(ev) {
        this.dragArmed = false;
        this.dragKey = null;
        ev.currentTarget.classList.remove("o_pmk_summary__dragging");
        this.entry.over = null;
    }

    onDragOver(row, ev) {
        if (this.dragKey && this.dragKey !== row.key) {
            ev.preventDefault();
            this.entry.over = row.key;
        }
    }

    async onDrop(row, ev) {
        ev.preventDefault();
        const from = this.dragKey;
        this.entry.over = null;
        if (!from || from === row.key) {
            return;
        }
        const keys = this.summary.rows.map((r) => r.key).filter((k) => k !== from);
        keys.splice(keys.indexOf(row.key) + (this._below(row.key, from) ? 1 : 0), 0, from);
        await this._rowCall("pmk_summary_order", [keys], _t("Порядок изменён"));
    }

    /** Тащили сверху вниз — встаёт под строкой, снизу вверх — над ней. */
    _below(target, from) {
        const keys = this.summary.rows.map((r) => r.key);
        return keys.indexOf(from) < keys.indexOf(target);
    }

    async copyRow(row) {
        await this._rowCall("pmk_summary_copy", [row.key], _t("Скопировано: %s", row.name));
    }

    async deleteRow(row) {
        const ok = await new Promise((resolve) => {
            this.env.services.dialog.add(ConfirmationDialog, {
                title: _t("Удалить строку"),
                body: _t("Удалить «%s» из расчёта? В историю расчёта ляжет запись.", row.name),
                confirmLabel: _t("Удалить"),
                confirm: () => resolve(true),
                cancel: () => resolve(false),
            }, { onClose: () => resolve(false) });
        });
        if (ok) {
            await this._rowCall("pmk_summary_delete", [row.key], _t("Удалено: %s", row.name));
        }
    }

    async _rowCall(method, args, done) {
        const resId = await this._ready();
        if (!resId) {
            return;
        }
        await this.orm.call("pmk.metal.spec", method, [[resId], ...args]);
        this.notification.add(done, { type: "success" });
        await this._reload();
    }

    async move(row, ev) {
        const target = ev.target.value;
        ev.target.value = "";
        if (!target) {
            return;
        }
        const resId = await this._ready();
        if (!resId) {
            return;
        }
        const res = await this.orm.call("pmk.metal.spec", "pmk_summary_move", [[resId], row.key, target]);
        if (res.error) {
            this.notification.add(_t("Не перенесено: %s", res.error), { type: "warning", sticky: true });
        } else {
            this.notification.add(_t("Перенесено в «%s»", res.moved), { type: "success" });
        }
        await this._reload();
    }

    get summary() {
        return this.props.record.data[this.props.name] || { rows: [] };
    }

    canOpen(row) {
        return row.source !== "manual";
    }

    toggle(row) {
        if (this.canOpen(row)) {
            this.open[row.key] = !this.open[row.key];
        }
    }

    num(value) {
        return value ? NUM.format(value) : "—";
    }

    kg(value) {
        return value ? NUM1.format(value) : "—";
    }

    money(value) {
        return value ? MONEY.format(value) : "—";
    }

    material(dobor) {
        return [dobor.sheet, dobor.coating].filter((part) => part).join(" · ") || "—";
    }

    sketch(html) {
        return markup(html || "");
    }
}

registry.category("fields").add("pmk_spec_summary", {
    component: SpecSummaryField,
    supportedTypes: ["json"],
});
