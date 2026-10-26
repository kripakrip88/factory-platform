/** @odoo-module **/
/**
 * Заявка на металл: «Каталог материалов» над строками (26.10.2026) — позиция справочника
 * новой строкой заявки (purchase.order.pmk_catalog_add). Окно — pmk_bridge catalog_dialog.
 */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { openCatalog } from "@pmk_bridge/catalog/catalog_dialog";

export class PmkCatalogPo extends Component {
    static template = "pmk_tech.CatalogPo";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
    }

    open() {
        const record = this.props.record;
        openCatalog(this.env, {
            onPick: async (key) => {
                if (!(await record.save())) {
                    return;
                }
                await this.orm.call("purchase.order", "pmk_catalog_add", [[record.resId], key]);
                await record.load();
            },
        });
    }
}

registry.category("view_widgets").add("pmk_catalog_po", { component: PmkCatalogPo });
