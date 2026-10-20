/** @odoo-module **/
/**
 * Вкладка «Металлоизделия» — сводка всех изделий расчёта (Антон 20.10.2026).
 *
 * Строки — поле pmk_summary (models/spec_summary.py): конструкции, доборка,
 * вентзонты. Строка раскрывается стрелкой и показывает состав — только
 * смотреть («можно раскрыть, но не редактировать»); правят во вкладке своего
 * калькулятора. Что раскрыто — помнится, пока открыта форма.
 */
import { Component, markup, useState } from "@odoo/owl";
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
        this.sources = SOURCES;
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
