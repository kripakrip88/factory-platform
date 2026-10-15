/** @odoo-module **/
/**
 * «Заказы в работе»: тон этапа на кнопке стадии и точки в её списке — по смыслу этапа
 * (pmk_order_stage), как плашки колонки «Статус» в списке (views/project_task_views.xml):
 * очередь и отгружено — серые, чертежи и в работе — голубые, металл — жёлтая, пауза —
 * красная, готово — зелёная (Антон 15.10.2026: «добавь цветовые индикаторы для статусов»).
 * Остальные стадии (сделка, счёт…) — по-прежнему тоном пути (pmk_theme, statusbar_compact.js).
 * Смыслы этапов — один запрос на вкладку через env.services.orm.
 */
import { onWillStart } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { StatusBarField } from "@web/views/fields/statusbar/statusbar_field";

const TONE = {
    queue: "grey", shipped: "grey", drawings: "blue", work: "blue",
    metal: "yellow", pause: "red", ready: "green",
};
let codesPromise = null;

patch(StatusBarField.prototype, {
    setup() {
        super.setup(...arguments);
        this.pmkOrderCodes = null;
        const field = this.props.record.fields[this.props.name];
        if (field && field.relation === "project.task.type") {
            onWillStart(async () => {
                codesPromise = codesPromise || this.env.services.orm
                    .searchRead("project.task.type", [["pmk_order_stage", "!=", false]], ["pmk_order_stage"])
                    .then((rows) => Object.fromEntries(rows.map((r) => [r.id, r.pmk_order_stage])))
                    .catch(() => ({}));
                this.pmkOrderCodes = await codesPromise;
            });
        }
    },

    pmkTone(item) {
        const codes = this.pmkOrderCodes;
        if (codes && this.props.record.data[this.props.name]) {
            if (codes[item.value]) {
                return TONE[codes[item.value]] || "grey";
            }
            // Этап планировщика без смысла («Разобрать: прошлые месяцы») — серый, как плашка
            // в таблице; доски без смыслов этапов («Доработка») — тоном пути.
            const own = this.props.record.data[this.props.name].id;
            if (codes[own] || Object.keys(codes).some((id) => this.getAllItems().some((i) => i.value === Number(id)))) {
                return "grey";
            }
        }
        return super.pmkTone(...arguments);
    },
});
