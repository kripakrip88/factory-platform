/** @odoo-module **/
/**
 * Чертежи марки справочника опор (27.10.2026) — <widget name="pmk_opora_drawing"/>.
 *
 * «Сделать чертежи» ставит задание чертёжному процессу (models/ref_draw.py), окно опрашивает
 * его раз в 2 с; готово — картинка листа 1, PDF и zip DXF для лазера.
 */
import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

export class PmkOporaDrawing extends Component {
    static template = "pmk_opora.OporaDrawing";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = this.env.services.orm;
        this.state = useState({ info: null, busy: false });
        this.timer = null;
        onWillStart(() => this.call("opora_draw_state"));
        onWillUnmount(() => clearTimeout(this.timer));
    }

    get resId() {
        return this.props.record.resId;
    }

    async call(method) {
        if (!this.resId) return;
        const info = await this.orm.call("pmk.opora.ref", method, [[this.resId]]);
        this.state.info = info;
        clearTimeout(this.timer);
        if (info.state === "queued") {
            this.timer = setTimeout(() => this.call("opora_draw_state"), 2000);
        }
    }

    async draw() {
        this.state.busy = true;
        try {
            await this.call("opora_draw");
        } finally {
            this.state.busy = false;
        }
    }

    url(id, download) {
        return `/web/content/${id}${download ? "?download=true" : ""}`;
    }
}

registry.category("view_widgets").add("pmk_opora_drawing", { component: PmkOporaDrawing });
