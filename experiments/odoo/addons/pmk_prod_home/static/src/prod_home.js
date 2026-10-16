/** @odoo-module **/
/**
 * Главная производства (16.10.2026) — клиентское действие pmk_prod_home.
 *
 * Прототип принят Антоном 16.10. Данные — pmk.prod.home.get_dashboard, щелчок —
 * open_block(key, id). Оформление — общее с главной продаж (pmk_sales_home, классы
 * o_pmk_home__*). Сервисы — env.services (грабля шага 31).
 */
import { Component, onWillStart, status, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";

export class PmkProdHome extends Component {
    static template = "pmk_prod_home.Home";
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
        const data = await this.orm.call("pmk.prod.home", "get_dashboard", []);
        if (status(this) !== "destroyed") {
            this.state.data = data;
            this.state.loading = false;
        }
    }

    get d() {
        return this.state.data || {};
    }

    async open(key, resId = false) {
        const action = await this.orm.call("pmk.prod.home", "open_block", [key, resId]);
        if (!action) {
            this.notification.add("Раздел вам недоступен.", { type: "warning" });
            return;
        }
        await this.action.doAction(action);
    }

    openTodo(item) {
        const key = { order: "order", metal: "metal_po", spec: "spec", laser: "laser_task" }[item.kind];
        return this.open(key, item.id);
    }

    pctWidth(row) {
        return Math.max(0, Math.min(100, row.pct || 0));
    }
}

registry.category("actions").add("pmk_prod_home", PmkProdHome);
