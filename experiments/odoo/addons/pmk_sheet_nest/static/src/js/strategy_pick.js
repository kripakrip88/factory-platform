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
        list = Object.entries(list).map(([name, row]) => ({ name, ...row }));
    }
    // Строка сводки — по name (контракт sheet_nest.job/1); strategy — у заглушки до 15.10.
    const byKey = Object.fromEntries(list.map((r) => [r.name || r.strategy, r]));
    const cols = STRATEGIES.filter(([k]) => byKey[k]).map(([key, label]) => ({
        key, label, chosen: key === chosen, untested: UNTESTED[key] || "",
        error: byKey[key].error || "",
    }));
    const row = (label, get, opts = {}) => {
        // Лучшее — по показанному (до десятых): 22,17 и 22,2 на экране одинаковы.
        const values = cols.map((c) => {
            const v = get(byKey[c.key] || {});
            return typeof v === "number" ? Math.round(v * 10) / 10 : v;
        });
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
            fmt: (b) => (b ? `${b.groups ?? "—"} / ${b.bridges ?? "—"} / ${b.parts ?? "—"}` : "—"),
        }));
    }
    rows.push(row("опасные переходы", (r) => dangerTotal(r.danger), { better: "min", fmt: (v) => num(v, 0) }));
    const details = [...DANGER_MAIN, ...DANGER_REF].map(([k, label], i) =>
        row(label, (r) => Number((r.danger || {})[k]) || 0,
            { sub: true, better: i < DANGER_MAIN.length ? "min" : null, fmt: (v) => num(v, 0) }));
    rows.push(
        row("листов с узкой полосой", (r) => (r.strip || {}).sheets, { better: "min", fmt: (v) => num(v, 0) }),
        row("худший остаток листа, мм", (r) => ((r.strip || {}).worst || null), {
            fmt: (w) => (w && w.w ? `${num(w.w, 0)} × ${num(w.l, 0)}` : "—"),
        }),
        row("возврат над деталями, м", (r) => (r.ret && typeof r.ret === "object" ? r.ret.over_m : r.ret),
            { better: "min" }),
        row("предупреждений", (r) => (Array.isArray(r.warnings) ? r.warnings.length : r.warnings),
            { better: "min", fmt: (v) => num(v, 0) }),
    );
    // Время на станке — строка на каждый профиль (contract: machine_s {имя: секунды|null},
    // machine_detail {имя: {cut_s, mark_s, travel_s, pierce_s, lift_s, k, total_s, why}},
    // res.machines — эхо профилей с preliminary). Предварительный профиль — «≈ N (предварительно)».
    const prelim = Object.fromEntries((res.machines || []).map((m) => [m.name, Boolean(m.preliminary)]));
    const names = [...new Set(list.flatMap((r) => Object.keys(r.machine_s || {})))];
    if (!names.length) {
        rows.push(row("станок, мин", () => null, { fmt: () => "—" }));
    }
    for (const name of names) {
        const label = `станок ${name.replace(/\s*\(.*\)\s*$/, "")}, мин${prelim[name] ? " (предварительно)" : ""}`;
        const rr = row(label, (r) => {
            const sec = (r.machine_s || {})[name];
            return typeof sec === "number" ? sec / 60 : null;
        }, { better: "min", fmt: (v) => (typeof v === "number" ? (prelim[name] ? "≈ " : "") + num(v, 0) : "—") });
        rr.cells.forEach((cell) => {
            const det = ((byKey[cell.key] || {}).machine_detail || {})[name] || {};
            const parts = [["рез", det.cut_s], ["гравировка", det.mark_s], ["холостой", det.travel_s],
                ["врезки", det.pierce_s], ["подъёмы", det.lift_s]].filter(([, x]) => typeof x === "number" && x > 0)
                .map(([w, x]) => `${w} ${num(x / 60)} мин`);
            cell.title = det.why || (parts.length ? parts.join(" · ") + (det.k && det.k !== 1 ? ` · ×${num(det.k, 2)}` : "") : "");
        });
        rows.push(rr);
    }
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
    if (Object.values(prelim).some(Boolean)) {
        notes.push("Время на станке предварительное — профиль по программам станка, подъёмы головы не учтены: это нижняя граница.");
    }
    if (req.bridge) {
        notes.push("Мост на станке не проверен.");
    }
    if (pick && pick.untested) {
        notes.push(pick.untested + ".");
    }
    for (const c of cols) {
        if (c.error) {
            notes.push(`«${c.label}» с общим резом не строится: ${c.error}`);
        }
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
        // Столбец, который с общим резом не строится (error), не выбирается.
        const c = this.view.cols.find((x) => x.key === col.key);
        if (this.props.readonly || !c || c.error) {
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
