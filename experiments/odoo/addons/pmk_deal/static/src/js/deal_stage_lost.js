/** @odoo-module **/
/**
 * «Проиграна…» — последним пунктом списка стадий сделки (Антон 25.10.2026:
 * «зачем нам выпадашка ещё с выиграно проиграно, когда есть статусы
 * документа?»). Выигрыш — стадия «Оплачено / в работе» или «Закрыта»; проигрыш
 * стадией не бывает (сделка уходит в архив с причиной, счёт отменяется), поэтому
 * отдельным пунктом под чертой: то же окно причины, что у штатной кнопки
 * «Проиграно» (crm.crm_lead_lost_action). У лида стадий нет — у него кнопка.
 * Шаблон — xml/deal_stage_lost.xml.
 */
import { patch } from "@web/core/utils/patch";
import { StatusBarField } from "@web/views/fields/statusbar/statusbar_field";

patch(StatusBarField.prototype, {
    /** Сделка в работе: можно отметить проигранной. */
    get pmkLostAvailable() {
        const record = this.props.record;
        if (record.resModel !== "crm.lead" || this.props.name !== "stage_id") {
            return false;
        }
        const data = record.data;
        return data.type === "opportunity" && data.active !== false && data.won_status === "pending";
    },

    async pmkMarkLost() {
        const record = this.props.record;
        if (record.isNew || (await record.isDirty())) {
            const saved = await record.save();
            if (!saved) {
                return;
            }
        }
        await this.env.services.action.doAction("crm.crm_lead_lost_action", {
            additionalContext: {
                active_id: record.resId,
                active_ids: [record.resId],
                active_model: "crm.lead",
            },
            onClose: () => record.load(),
        });
    },
});
