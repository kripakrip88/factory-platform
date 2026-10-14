/** @odoo-module **/
/**
 * Сводка раскроя листа по четырём порядкам резки (вкладка «Раскрой листа» задания
 * лазеру). Столбцы — стратегии, строки — показатели (ERP.md, «Сводка по
 * стратегиям»). Щелчок по столбцу и есть выбор: пишется nest_strategy задания.
 * Лучшее значение в строке — бледной подсветкой (яркий лайм Антон не принимает).
 *
 * Данные — result.json последнего раскроя (поле nest_summary_json), разбор —
 * в summaryView без Odoo.
 */
import { registry } from "@web/core/registry";
import { Component, useState } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export const STRATEGIES = [
    ["short", "Минимум холостого"],
    ["safe", "Безопасный"],
    ["safe0", "Безопасный, конец у нуля"],
    ["hill", "Горкой"],
];
// Не проверены на станке — до слова Антона (подписи проверены 14.10).
const UNTESTED = { hill: "«Горкой» на станке не проверен" };
const DANGER_MAIN = [["tongues", "над язычками"], ["small", "над мелкими деталями"],
    ["parts", "над деталями"], ["holes", "над отверстиями ≥ 10 мм"]];
const DANGER_REF = [["holes_s", "над отверстиями < 10 мм"], ["near", "впритирку"],
    ["short", "короткие"], ["mj", "над деталями с перемычками"]];

function num(v, digits = 1) {
    if (v === undefined || v === null || v === false || Number.isNaN(Number(v))) {
        return "—";
    }
    const s = Number(v).toFixed(digits).replace(".", ",");
    return digits && s.endsWith(",0") ? s.slice(0, -2) : s;
}

function dangerTotal(d) {
    return DANGER_MAIN.reduce((sum, [k]) => sum + (Number((d || {})[k]) || 0), 0);
}

/** Строки сводки: {label, cells: [{key, text, best}], ...}. */
export function summaryView(json, chosen) {
    let res = {};
    try {
        res = JSON.parse(json || "{}") || {};
    } catch {
        res = {};
    }
    let list = res.strategies || [];
    if (!Array.isArray(list)) {
        list = Object.entries(list).map(([strategy, row]) => ({ strategy, ...row }));
    }
    const byKey = Object.fromEntries(list.map((r) => [r.strategy, r]));
    const cols = STRATEGIES.filter(([k]) => byKey[k]).map(([key, label]) => ({
        key, label, chosen: key === chosen, untested: UNTESTED[key] || "",
    }));
    const row = (label, get, opts = {}) => {
        const values = cols.map((c) => get(byKey[c.key] || {}));
        const nums = values.filter((v) => typeof v === "number" && !Number.isNaN(v));
        const best = nums.length && opts.better ? Math[opts.better === "min" ? "min" : "max"](...nums) : null;
        const allSame = nums.length > 1 && nums.every((v) => v === nums[0]);
        return {
            label, sub: opts.sub || false,
            cells: cols.map((c, i) => ({
                key: c.key,
                text: opts.fmt ? opts.fmt(values[i]) : num(values[i]),
                best: best !== null && !allSame && values[i] === best,
            })),
        };
    };
    const rows = [
        row("листов", (r) => r.sheets, { fmt: (v) => num(v, 0) }),
        row("рез, м", (r) => r.cut_m),
        row("холостой, м", (r) => r.idle_m, { better: "min" }),
        row("возврат в ноль, м", (r) => r.return_m, { better: "min" }),
        row("врезок", (r) => r.pierces, { better: "min", fmt: (v) => num(v, 0) }),
    ];
    if (list.some((r) => r.bridges)) {
        rows.push(row("мосты: групп / перемычек / деталей", (r) => r.bridges, {
            fmt: (b) => (b ? `${b.groups ?? "—"} / ${b.joints ?? "—"} / ${b.parts ?? "—"}` : "—"),
        }));
    }
    rows.push(row("опасные переходы", (r) => dangerTotal(r.danger), { better: "min", fmt: (v) => num(v, 0) }));
    const details = [...DANGER_MAIN, ...DANGER_REF].map(([k, label], i) =>
        row(label, (r) => Number((r.danger || {})[k]) || 0,
            { sub: true, better: i < DANGER_MAIN.length ? "min" : null, fmt: (v) => num(v, 0) }));
    rows.push(
        row("конец листа: остаток, мм", (r) => (r.strip || {}).rest_mm, { fmt: (v) => num(v, 0) }),
        row("листов с узкой полосой", (r) => (r.strip || {}).narrow, { better: "min", fmt: (v) => num(v, 0) }),
        row("возврат над деталями, м", (r) => r.ret, { better: "min" }),
        row("предупреждений", (r) => r.warnings, { better: "min", fmt: (v) => num(v, 0) }),
        row("станок, мин", (r) => r.machine_s, {
            fmt: (v) => (v && typeof v === "object"
                ? Object.entries(v).map(([m, s]) => `${m}: ${num(s / 60)}`).join(", ")
                : (typeof v === "number" ? num(v / 60) : "—")),
        }),
    );
    const pick = cols.find((c) => c.chosen);
    const r = pick && byKey[pick.key];
    let decision = "";
    if (r) {
        decision = `Решение: «${pick.label}» — холостой ${num(r.idle_m)} м, опасных переходов ` +
            `${num(dangerTotal(r.danger), 0)}, возврат в ноль ${num(r.return_m)} м.`;
    }
    const notes = [];
    const req = res.requested || {};
    const app = res.applied || {};
    if (req.coedge && app.coedge === false) {
        notes.push("Общий рез запрошен, но не применён — детали разложены с зазором.");
    }
    if (req.bridge) {
        notes.push("Мост на станке не проверен.");
    }
    if (pick && pick.untested) {
        notes.push(pick.untested + ".");
    }
    return { cols, rows, details, decision, notes, empty: !cols.length };
}

export class SheetNestStrategyField extends Component {
    static template = "pmk_sheet_nest.StrategyPick";
    static props = { ...standardFieldProps };

    setup() {
        this.state = useState({ details: false });
    }

    get view() {
        const data = this.props.record.data;
        return summaryView(data.nest_summary_json, data[this.props.name]);
    }

    async pick(col) {
        if (this.props.readonly) {
            return;
        }
        await this.props.record.update({ [this.props.name]: col.key });
    }

    toggleDetails() {
        this.state.details = !this.state.details;
    }
}

registry.category("fields").add("pmk_sheet_nest_strategy", {
    component: SheetNestStrategyField,
    supportedTypes: ["selection"],
    fieldDependencies: [{ name: "nest_summary_json", type: "text" }],
});
