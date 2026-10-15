/** @odoo-module **/
/**
 * «Заказы в работе»: статусы в панели фильтров слева — такими же плашками, как в
 * колонке «Статус» таблицы (Антон 15.10.2026: «для статусов добавить визуальный
 * индикатор как в основной таблице»). Цвет — по смыслу этапа (pmk_order_stage),
 * как decoration-* у поля stage_id в списке (views/project_task_views.xml):
 * очередь и отгружено — серые, чертежи и в работе — синие, металл — жёлтая,
 * пауза — красная, готово — зелёная. Этап без смысла — серый.
 *
 * Смыслы этапов — один запрос на вкладку через env.services.orm (useService в
 * патче вида вешает вид — грабли Odoo 19).
 */
import { onWillStart, useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { SearchPanel } from "@web/search/search_panel/search_panel";

const BADGE = {
    queue: "text-bg-300", shipped: "text-bg-300",
    drawings: "text-bg-info", work: "text-bg-info",
    metal: "text-bg-warning", pause: "text-bg-danger", ready: "text-bg-success",
};

let codesPromise = null;

export function stageBadgeClass(codes, id) {
    if (!codes) {
        return "";
    }
    return `badge rounded-pill pmk-sp-stage ${BADGE[codes[id]] || "text-bg-300"}`;
}

patch(SearchPanel.prototype, {
    setup() {
        super.setup(...arguments);
        this.pmkStage = useState({ codes: null });
        onWillStart(async () => {
            const sm = this.env.searchModel;
            if (sm.resModel !== "project.task" || !(sm.globalContext || {}).default_pmk_metal) {
                return;  // только планировщик «Заказы в работе» (как фильтр в окне ползунков)
            }
            codesPromise = codesPromise || this.env.services.orm
                .searchRead("project.task.type", [["pmk_order_stage", "!=", false]], ["pmk_order_stage"])
                .then((rows) => Object.fromEntries(rows.map((r) => [r.id, r.pmk_order_stage])))
                .catch(() => ({}));
            this.pmkStage.codes = await codesPromise;
        });
    },

    pmkStageClass(section, valueId) {
        if (!this.pmkStage.codes || section.fieldName !== "stage_id") {
            return "";
        }
        return stageBadgeClass(this.pmkStage.codes, valueId);
    },
});
