/** @odoo-module **/
// Полоса над списком позиций расчёта (13.10.2026, просьба Антона: «выбор позиций
// сделать так же везде, кнопку переноса объединить в выпадашку — когда появятся
// другие калькуляторы, кнопок станет очень много»).
//
// <widget name="pmk_pick_bar" list="product_ids" source="metal"/>: «☑ N поз.»
// (снять все; «отметить все» — в заголовке колонки, pick_head.js; галочки
// строк — pick_toggle.js), меню «Перенести в ▾» со всеми
// калькуляторами, кроме своего, «Копировать» и «Удалить» отмеченные. Действие
// делает сервер (pmk.metal.spec.pmk_bulk), список перечитывается.
//
// Новый калькулятор — строка в TARGETS и ветки на сервере (spec_move.py).

import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { pickAll } from "@pmk_calc/js/pick_head";

const TARGETS = [
    { key: "metal", label: "Металлоизделия" },
    { key: "dobor", label: "Доборные элементы" },
    { key: "vent", label: "Вентзонты" },
];

export class PmkPickBar extends Component {
    static template = "pmk_calc.PmkPickBar";
    static components = { Dropdown, DropdownItem };
    static props = { ...standardWidgetProps, list: String, source: String };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
    }

    get rows() {
        return this.props.record.data[this.props.list]?.records || [];
    }

    get picked() {
        return this.rows.filter((r) => r.data.pmk_pick);
    }

    get targets() {
        return TARGETS.filter((t) => t.key !== this.props.source);
    }

    async setAll(value) {
        await pickAll(this.rows, "pmk_pick", value);
    }

    async run(action, target = false) {
        const record = this.props.record;
        // Отмеченные — до сохранения: у вкладок калькуляторов список вычисляемый,
        // и после сохранения галочки сбрасываются.
        let ids = this.picked.map((r) => r.resId).filter(Boolean);
        if (!(await record.save())) {
            return;
        }
        if (this.props.source === "metal") {
            ids = this.picked.map((r) => r.resId).filter(Boolean);
        }
        if (!ids.length) {
            this.notification.add(_t("Отметьте строки галочкой."), { type: "warning" });
            return;
        }
        await this.orm.call("pmk.metal.spec", "pmk_bulk", [[record.resId], this.props.source, action, target, ids]);
        await record.load();
    }

    confirmDelete() {
        const n = this.picked.length;
        this.dialog.add(ConfirmationDialog, {
            title: _t("Удалить отмеченные"),
            body: _t("Удалить отмеченные строки: %s?", n),
            confirmLabel: _t("Удалить"),
            confirm: () => this.run("delete"),
            cancel: () => {},
        });
    }
}

registry.category("view_widgets").add("pmk_pick_bar", {
    component: PmkPickBar,
    extractProps: ({ attrs }) => ({ list: attrs.list, source: attrs.source }),
});
