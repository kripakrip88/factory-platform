/** @odoo-module **/
/**
 * Главная закупок (18.10.2026) — клиентское действие pmk_purchase_home.
 *
 * Данные — pmk.purchase.home.get_dashboard, щелчок — open_block(key, id). Оформление —
 * общее с главной продаж (pmk_sales_home, классы o_pmk_home__*). Сервисы — env.services
 * (грабля шага 31: useService вешает вид).
 */
import { Component, onWillStart, status, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";

export class PmkPurchaseHome extends Component {
    static template = "pmk_purchase_home.Home";
    static props = ["*"];

    setup() {
        this.orm = this.env.services.orm;
        this.action = this.env.services.action;
        this.notification = this.env.services.notification;
        this.state = useState({ data: null, loading: true });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        const data = await this.orm.call("pmk.purchase.home", "get_dashboard", []);
        if (status(this) !== "destroyed") {
            this.state.data = data;
            this.state.loading = false;
        }
    }

    get d() {
        return this.state.data || {};
    }

    async open(key, resId = false) {
        const action = await this.orm.call("pmk.purchase.home", "open_block", [key, resId]);
        if (!action) {
            this.notification.add("Раздел вам недоступен.", { type: "warning" });
            return;
        }
        await this.action.doAction(action);
    }

    openTodo(item) {
        return this.open(item.kind, item.id);
    }
}

registry.category("actions").add("pmk_purchase_home", PmkPurchaseHome);
