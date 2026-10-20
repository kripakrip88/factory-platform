/** @odoo-module **/
/**
 * «Создать ▾» и «Печать ▾» в шапке сделки — как в МойСкладе (20.10.2026).
 *
 * Антон: «давай уходить от отдельных кнопок на создание каждого документа.
 * сделаем как в мой склад. выпадашка создать документ и выпадашка печатных
 * форм». Пункты отдаёт сервер (crm.lead.pmk_doc_menu, models/deal_flow.py):
 * модули дописывают свои (почта — «Письмо», счёт — этапом 5), меню их не
 * знает. Список читается при каждом открытии (beforeOpen): после нового
 * расчёта «КП (PDF)» в «Печати» появляется без перезагрузки.
 *
 * Пункт: несохранённую сделку сначала сохраняем, потом вызываем метод пункта
 * и выполняем его действие; после окна (задача, письмо) запись перечитываем.
 * Сервисы — через this.env.services (useService вешал вид, project_odoo_useservice_hang).
 */
import { Component, useState } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

export class DealDocMenu extends Component {
    static template = "pmk_deal.DealDocMenu";
    static components = { Dropdown, DropdownItem };
    static props = { ...standardWidgetProps };

    setup() {
        this.state = useState({ create: [], print: [], loaded: false });
        this.load = this.load.bind(this);
    }

    async load() {
        const id = this.props.record.resId;
        // Модель — из записи: то же меню у сделки и у счёта (pmk_orders, 20.10.2026).
        const model = this.props.record.resModel;
        const menu = await this.env.services.orm.call(model, "pmk_doc_menu", [id ? [id] : []]);
        this.state.create = menu.create || [];
        this.state.print = menu.print || [];
        this.state.loaded = true;
    }

    async run(item) {
        const record = this.props.record;
        if (record.isNew || (await record.isDirty())) {
            const saved = await record.save();
            if (!saved) {
                return;
            }
        }
        const action = await this.env.services.orm.call(record.resModel, item.method, [[record.resId]]);
        if (action) {
            await this.env.services.action.doAction(action, {
                onClose: () => record.load(),
            });
        } else {
            await record.load();
        }
    }
}

registry.category("view_widgets").add("pmk_deal_doc_menu", { component: DealDocMenu });
