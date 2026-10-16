/** @odoo-module **/
/**
 * Главная продаж (16.10.2026) — клиентское действие pmk_sales_home.
 *
 * Прототип принят Антоном 16.10. Данные — pmk.sales.home.get_dashboard (одним
 * вызовом, от имени человека), щелчок по блоку — open_block(key, id) → действие.
 * Сервисы — env.services (грабля шага 31: useService вешал вид).
 */
import { Component, onWillStart, status, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";

export class PmkSalesHome extends Component {
    static template = "pmk_sales_home.Home";
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
        const data = await this.orm.call("pmk.sales.home", "get_dashboard", []);
        if (status(this) !== "destroyed") {
            this.state.data = data;
            this.state.loading = false;
        }
    }

    get d() {
        return this.state.data || {};
    }

    async open(key, resId = false) {
        const action = await this.orm.call("pmk.sales.home", "open_block", [key, resId]);
        if (!action) {
            this.notification.add("Раздел вам недоступен.", { type: "warning" });
            return;
        }
        await this.action.doAction(action);
    }

    /** Полоса этапа: доля суммы, но заметная, если в этапе есть сделки без цены. */
    barWidth(stage) {
        return stage.count ? Math.max(stage.pct, 4) : 0;
    }

    /** Столбец поступлений: до 90 px, над ним — сумма дня. */
    colHeight(day) {
        return Math.round((day.pct || 0) * 0.9);
    }

    openTodo(item) {
        if (item.kind === "mail") {
            return this.open("mail");
        }
        return this.open("deal", item.id);
    }
}

registry.category("actions").add("pmk_sales_home", PmkSalesHome);
