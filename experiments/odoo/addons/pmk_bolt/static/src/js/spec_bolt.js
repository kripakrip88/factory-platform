/** @odoo-module **/
/**
 * Болты в расчёте (21.10.2026): вкладка «Фундаментные болты» — та же таблица, что в
 * калькуляторе (js/bolt_grid.js); вызовы bolt_* уходят расчёту, он передаёт их своему
 * документу болтов (models/spec.py). Сводка «Металлоизделия» — болты строками.
 */
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { SpecSummaryField } from "@pmk_bridge/js/spec_summary";
import { PmkBoltGrid } from "./bolt_grid";

export class PmkSpecBoltGrid extends PmkBoltGrid {
    static MODEL = "pmk.metal.spec";
}

registry.category("view_widgets").add("pmk_spec_bolt_grid", { component: PmkSpecBoltGrid });

patch(SpecSummaryField.prototype, {
    setup() {
        super.setup(...arguments);
        this.sources = { ...this.sources, bolt: { label: "Болты", tab: "Фундаментные болты" } };
    },
});
