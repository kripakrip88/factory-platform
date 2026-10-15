/** @odoo-module **/
/**
 * Вкладка «Металл» одной таблицей с раскрытием и схемой (15.10.2026) —
 * <widget name="pmk_metal_overview"/>.
 *
 * Антон 15.10: «почему листы по раскладке и детали — две разные таблицы? Лист
 * раскрывается как спецификация… То же — прокат. Иметь возможность открыть
 * посмотреть, как входят детали — менеджер оценит, насколько неудобные
 * размеры листа может скинуть заказчик». Прототип принят; правка: на схеме
 * проката одинаковые отрезки — одним блоком «100 мм × 100 шт».
 *
 * Данные — pmk.metal.spec.pmk_metal_overview (pmk_calc/models/
 * spec_metal_view.py; прокат дописывает pmk_cut). Схема — отдельным вызовом
 * при открытии окна: координаты той же раскладки, в базе ничего не меняется.
 * «Разложить листы / прокат», габарит детали, «Листов по факту» — сначала
 * сохранить форму, потом вызов, потом перечитать запись (иначе правки шапки
 * пропали бы при load()).
 *
 * Сервисы — env.services (грабля шага 31: useService вешал вид), ответ после
 * закрытия вкладки не пишем (alive()).
 */
import { Component, status, useEffect, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

const fmtKg = (value) =>
    (Math.round((value || 0) * 10) / 10).toLocaleString("ru-RU", { maximumFractionDigits: 1 });
const fmtM = (value) =>
    (Math.round((value || 0) * 100) / 100).toLocaleString("ru-RU", { maximumFractionDigits: 2 });
const fmtMm = (value) => (Math.round((value || 0) * 10) / 10).toLocaleString("ru-RU");

function plural(n, one, few, many) {
    const m10 = n % 10;
    const m100 = n % 100;
    if (m10 === 1 && m100 !== 11) {
        return one;
    }
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) {
        return few;
    }
    return many;
}

// Бледные тона деталей на схеме листа: деталь узнаётся по цвету в легенде.
const PART_TONES = 8;

export class PmkMetalSchemeDialog extends Component {
    static template = "pmk_calc.MetalSchemeDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        kind: String,
        data: Object,
        openPlan: { type: Function, optional: true },
    };

    get title() {
        return this.props.data.title || _t("Схема");
    }

    // ── лист ─────────────────────────────────────────────────────────────
    get sheetKeys() {
        return Object.keys(this.props.data.parts || {});
    }

    tone(key) {
        return `o_pmk_mtone_${this.sheetKeys.indexOf(String(key)) % PART_TONES}`;
    }

    partOf(key) {
        return (this.props.data.parts || {})[key] || {};
    }

    /** Лист лежит длиной вдоль экрана: y раскладки → x рисунка. */
    sheetView() {
        const d = this.props.data;
        return `0 0 ${d.length} ${d.width}`;
    }

    sheetCountLabel(count) {
        return `× ${count} ${plural(count, "лист", "листа", "листов")}`;
    }

    legend(drawing) {
        const counts = {};
        for (const rect of drawing.rects) {
            counts[rect[0]] = (counts[rect[0]] || 0) + 1;
        }
        return Object.entries(counts).map(([key, qty]) => ({ key, qty, part: this.partOf(key) }));
    }

    // ── прокат ───────────────────────────────────────────────────────────
    barCountLabel(count) {
        return `× ${count} ${plural(count, "хлыст", "хлыста", "хлыстов")}`;
    }

    barPct(pattern, length) {
        return `${(100 * length) / (pattern.stock || 1)}%`;
    }

    blockLabel(block) {
        return block.qty > 1 ? `${fmtMm(block.length)} мм × ${block.qty}` : `${fmtMm(block.length)} мм`;
    }

    leftoverLabel(pattern) {
        return `${pattern.useful ? _t("годный остаток") : _t("лом")} ${fmtMm(pattern.leftover)} мм`;
    }
}

export class PmkMetalOverview extends Component {
    static template = "pmk_calc.MetalOverview";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = this.env.services.orm;
        this.dialog = this.env.services.dialog;
        this.notification = this.env.services.notification;
        this.action = this.env.services.action;
        this.state = useState({ data: null, loading: true, open: {}, busy: false });
        this.seq = 0;
        useEffect(
            () => {
                this.load();
            },
            () => [this.props.record.resId, this.signature]
        );
    }

    /** Перечитать сводку, когда сменилась раскладка или раскрой (после
     * сохранения формы ядро обновляет эти наборы). */
    get signature() {
        const data = this.props.record.data;
        const ids = (name) => (data[name]?.currentIds || data[name]?.records?.map((r) => r.resId) || []).join(",");
        return [ids("layout_group_ids"), ids("cut_plan_ids"), data.layout_stale ? 1 : 0].join("|");
    }

    alive() {
        return status(this) !== "destroyed";
    }

    get specId() {
        return this.props.record.resId || false;
    }

    async load() {
        if (!this.specId) {
            this.state.loading = false;
            this.state.data = null;
            return;
        }
        const seq = ++this.seq;
        this.state.loading = true;
        const data = await this.orm.call("pmk.metal.spec", "pmk_metal_overview", [[this.specId]]);
        if (!this.alive() || seq !== this.seq) {
            return;
        }
        this.state.data = data;
        this.state.loading = false;
    }

    // ── строки ───────────────────────────────────────────────────────────
    get sheets() {
        return this.state.data?.sheets || [];
    }

    get bars() {
        return this.state.data?.bars?.rows || [];
    }

    get showBars() {
        const bars = this.state.data?.bars;
        return Boolean(bars && bars.has_linear);
    }

    get isTech() {
        return this.state.data?.kind === "tech";
    }

    get totalBuy() {
        return (
            this.sheets.reduce((sum, row) => sum + (row.buy_kg || 0), 0) +
            this.bars.reduce((sum, row) => sum + (row.buy_kg || 0), 0)
        );
    }

    toggle(key) {
        this.state.open[key] = !this.state.open[key];
    }

    isOpen(key) {
        return Boolean(this.state.open[key]);
    }

    sheetsLabel(row) {
        if (!row.sheets) {
            return _t("не разложено");
        }
        const n = row.sheets_buy;
        return `${n} ${plural(n, "лист", "листа", "листов")}`;
    }

    barsLabel(row) {
        if (!row.bars) {
            return "—";
        }
        return `${row.bars} ${plural(row.bars, "хлыст", "хлыста", "хлыстов")} · ${fmtM(row.stock_m)} м`;
    }

    kg(value) {
        return fmtKg(value);
    }

    m(value) {
        return fmtM(value);
    }

    mm(value) {
        return fmtMm(value);
    }

    useClass(row) {
        return row.use_level === "bad" ? "o_pmk_mo__use--bad" : row.use_level === "low" ? "o_pmk_mo__use--low" : "";
    }

    // ── действия ─────────────────────────────────────────────────────────
    /** Сохранить форму, вызвать метод расчёта, перечитать запись и сводку. */
    async run(method, args = []) {
        if (this.state.busy) {
            return;
        }
        const record = this.props.record;
        this.state.busy = true;
        try {
            if (record.isDirty && !(await record.save())) {
                return;
            }
            await this.orm.call("pmk.metal.spec", method, [[record.resId], ...args]);
            if (!this.alive()) {
                return;
            }
            await record.load();
            await this.load();
        } finally {
            if (this.alive()) {
                this.state.busy = false;
            }
        }
    }

    layoutSheets() {
        return this.run("action_draft_layout");
    }

    layoutBars() {
        return this.run("action_pmk_cut_linear");
    }

    setSheetSize(part, ev) {
        return this.run("pmk_metal_set_sheet_size", [part.id, ev.target.value]);
    }

    /** Длины хлыста для докупки (6 / 9 / 11,7 / 12 м): отмеченные — в
     * раскрой, пересчёт сразу. Хотя бы одна длина остаётся отмеченной. */
    toggleLength(row, length) {
        const current = new Set(row.lengths || []);
        if (current.has(length)) {
            if (current.size === 1) {
                this.notification.add(_t("Нужна хотя бы одна длина хлыста."), { type: "warning" });
                return;
            }
            current.delete(length);
        } else {
            current.add(length);
        }
        return this.run("pmk_metal_set_bar_lengths", [row.profile_id, [...current]]);
    }

    setFact(row, ev) {
        const value = parseInt(ev.target.value || "0", 10) || 0;
        if (value === (row.fact || 0)) {
            return;
        }
        return this.run("pmk_metal_set_sheets_fact", [row.id, value]);
    }

    async sheetScheme(row) {
        const data = await this.orm.call("pmk.metal.spec", "pmk_metal_sheet_scheme", [[this.specId], row.id]);
        if (this.alive()) {
            this.dialog.add(PmkMetalSchemeDialog, { kind: "sheet", data });
        }
    }

    async barScheme(row) {
        const data = await this.orm.call("pmk.metal.spec", "pmk_metal_bar_scheme", [[this.specId], row.id]);
        if (!this.alive()) {
            return;
        }
        this.dialog.add(PmkMetalSchemeDialog, {
            kind: "bar",
            data,
            openPlan: () => this.openPlan(data.plan_id),
        });
    }

    async openPlan(planId) {
        const record = this.props.record;
        if (record.isDirty && !(await record.save())) {
            return;
        }
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "pmk.cut.plan",
            res_id: planId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("view_widgets").add("pmk_metal_overview", { component: PmkMetalOverview });
