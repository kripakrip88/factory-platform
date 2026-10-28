/** @odoo-module **/
/**
 * «Проверка» расчёта (28.10.2026) — <widget name="pmk_spec_checks"/> в колонке «Итог».
 *
 * Список того, что система нашла не так (models/spec_checks.py, поле pmk_checks_json); пункт
 * ведёт к месту: вкладка — щелчок по её ярлыку, поле — прокрутка и фокус. Ничего не запрещает.
 */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

export class PmkSpecChecks extends Component {
    static template = "pmk_bridge.SpecChecks";
    static props = { ...standardWidgetProps };

    get items() {
        try {
            return JSON.parse(this.props.record.data.pmk_checks_json || "[]");
        } catch {
            return [];
        }
    }

    go(item) {
        const form = document.querySelector(".o_form_view .o_form_sheet");
        if (!form) {
            return;
        }
        if (item.tab) {
            const link = form.querySelector(`.o_notebook_headers .nav-link[name="${item.tab}"]`);
            if (link) {
                link.click();
                link.scrollIntoView({ block: "nearest", behavior: "smooth" });
            }
        } else if (item.field) {
            const field = form.querySelector(`.o_field_widget[name="${item.field}"]`);
            if (field) {
                field.scrollIntoView({ block: "center", behavior: "smooth" });
                field.querySelector("input, textarea, select")?.focus();
            }
        }
    }
}

registry.category("view_widgets").add("pmk_spec_checks", { component: PmkSpecChecks });
