/** @odoo-module **/
/**
 * Решение инженера по раскрою (вкладка «Раскрой» заказа вентзонтов).
 *
 * По каждому материалу — таблица «свес × склад/бухта». Щелчок по ячейке и есть решение:
 * в строку материала пишутся вариант (choice) и свес (sves). Лучшая ячейка подсвечена
 * (подсказка), выбранная — в рамке; под таблицей — «Решение: …» с экономией против
 * стандарта. Антон 12.10.2026: «как принимать решение? выбора ведь нет» — прежняя
 * редактируемая таблица ниже рекомендаций выглядела как отчёт.
 *
 * Строки материалов грузятся полями relatedFields (без вложенного списка в виде):
 * choice и sves — изменяемые, остальное — только чтение.
 */
import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const SVES = [150, 145, 140, 135, 130, 125];
const SOURCES = [["stock", "Склад 2500"], ["coil", "Бухта"]];
const SRC_WORD = { stock: "склад", coil: "бухта" };

export function fmtKg(v) {
    if (v === undefined || v === null || v === false) {
        return "—";
    }
    const s = (Math.round(v * 10) / 10).toFixed(1).replace(".", ",");
    return s.endsWith(",0") ? s.slice(0, -2) : s;
}

function fmtMm(v) {
    return String(v).replace(".", ",");
}

function fmtRub(v) {
    return Math.round(v).toLocaleString("ru-RU").replace(/,/g, " ");
}

/** Модель одного материала для шаблона — без Odoo, проверяется отдельно. */
export function materialView(d) {
    let rows = [];
    try {
        rows = JSON.parse(d.sves_json || "[]");
    } catch {
        rows = [];
    }
    const cell = (sv, src) => {
        const r = rows.find((x) => Math.round(Number(x.sves)) === sv && x.source === src);
        if (r) {
            return r;
        }
        if (sv === 150) {
            return src === "stock"
                ? { kg: d.stock_kg, lengths: d.stock_lengths, error: d.stock_error }
                : { kg: d.coil_kg, lengths: d.coil_lengths, error: d.coil_error };
        }
        return {};
    };
    const ok = rows.filter((x) => x.kg && !x.error);
    const best = ok.length
        ? ok.reduce((a, b) => (b.kg < a.kg || (b.kg === a.kg && Number(b.sves) > Number(a.sves)) ? b : a))
        : null;
    const base = cell(150, "stock");
    const ref = base.kg && !base.error
        ? { kg: base.kg, name: "150 + склад" }
        : { kg: cell(150, "coil").kg, name: "150 + бухта" };
    const sves = Number(d.sves || 150);
    const chosen = cell(sves, d.choice);
    const saving = (kg) => {
        if (!ref.kg || !kg || ref.kg - kg <= 0.05) {
            return "";
        }
        const diff = ref.kg - kg;
        let t = `экономия ${fmtKg(diff)} кг (${fmtKg((100 * diff) / ref.kg)} %) против ${ref.name}`;
        if (d.price_kg) {
            t += ` ≈ ${fmtRub(diff * d.price_kg)} ₽`;
        }
        return t;
    };
    let decision = "";
    if (chosen.error) {
        decision = `Свес ${sves} + ${SRC_WORD[d.choice]} — невозможно: ${chosen.error}`;
    } else if (chosen.kg) {
        decision = `Решение: свес ${sves} + ${SRC_WORD[d.choice]} — ${fmtKg(chosen.kg)} кг`;
        const s = saving(chosen.kg);
        decision += s ? `, ${s}.` : ".";
        if (chosen.lengths) {
            decision += ` Листы: ${chosen.lengths}.`;
        }
    }
    let hint = "";
    if (best && !(Math.round(Number(best.sves)) === sves && best.source === d.choice)) {
        hint = `Выгоднее всего: свес ${Math.round(Number(best.sves))} + ${SRC_WORD[best.source]} — ` +
            `${fmtKg(best.kg)} кг` + (saving(best.kg) ? `, ${saving(best.kg)}` : "") + ".";
    }
    return {
        title: `${d.color} · ${fmtMm(d.thickness)} мм`,
        rows: SVES.map((sv) => ({
            sv,
            cells: SOURCES.map(([src]) => {
                const c = cell(sv, src);
                return {
                    src, sv,
                    kg: c.kg ? fmtKg(c.kg) : "",
                    lengths: c.lengths || "",
                    error: c.error || "",
                    pickable: Boolean(c.kg) && !c.error,
                    best: Boolean(best) && Math.round(Number(best.sves)) === sv && best.source === src,
                    chosen: sves === sv && d.choice === src,
                };
            }),
        })),
        decision,
        decisionError: Boolean(chosen.error),
        hint,
        lowSves: sves < 150,
        noPrice: !d.price_kg,
        priceSheet: d.price_sheet || "листа",
    };
}

export class NestChoiceField extends Component {
    static template = "pmk_vent_nest.NestChoice";
    static props = { ...standardFieldProps };

    get materials() {
        return this.props.record.data[this.props.name].records.map((rec) => ({
            id: rec.id, rec, ...materialView(rec.data),
        }));
    }

    get sources() {
        return SOURCES;
    }

    async pick(material, cell) {
        if (this.props.readonly || !cell.pickable) {
            return;
        }
        await material.rec.update({ choice: cell.src, sves: String(cell.sv) });
    }
}

registry.category("fields").add("pmk_nest_choice", {
    component: NestChoiceField,
    supportedTypes: ["one2many"],
    relatedFields: [
        { name: "color", type: "char" },
        { name: "thickness", type: "float" },
        { name: "key", type: "char" },
        { name: "stock_kg", type: "float" },
        { name: "stock_lengths", type: "char" },
        { name: "stock_error", type: "char" },
        { name: "coil_kg", type: "float" },
        { name: "coil_lengths", type: "char" },
        { name: "coil_error", type: "char" },
        { name: "sves_json", type: "text" },
        { name: "price_kg", type: "float" },
        { name: "price_sheet", type: "char" },
        { name: "choice", type: "selection", readonly: false,
          selection: [["stock", "Склад 2500"], ["coil", "Бухта"]] },
        { name: "sves", type: "selection", readonly: false,
          selection: SVES.map((s) => [String(s), String(s)]) },
    ],
});
