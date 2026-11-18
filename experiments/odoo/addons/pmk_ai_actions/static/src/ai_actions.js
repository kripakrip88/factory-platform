/** @odoo-module **/
/**
 * Карточки действий под ответом ассистента (19.11.2026, прототип принят Антоном).
 * Сервер: pmk.ai.chat.execute_proposal / cancel_proposal (pmk_ai_actions/models/proposal.py).
 * Ответ пришёл — диалог перечитывается (thread_messages отдаёт карточки у ответов).
 */
import { patch } from "@web/core/utils/patch";
import { PmkAiPanel } from "@pmk_ai/ai_panel";

patch(PmkAiPanel.prototype, {
    async wait(requestId, threadId) {
        await super.wait(requestId, threadId);
        if (this.state.threadId === threadId) {
            const item = this.state.items[this.state.items.length - 1];
            if (item && item.role === "assistant" && !item.error) {
                await this.openThread(threadId);
            }
        }
    },

    async runProposal(card) {
        if (card.state !== "proposed" || card.busy) return;
        card.busy = true;
        try {
            const res = await this.orm.call("pmk.ai.chat", "execute_proposal", [card.id]);
            Object.assign(card, res, { busy: false });
        } catch (e) {
            Object.assign(card, { busy: false, state: "failed", error: "Ошибка сервера — повторите." });
        }
    },

    async cancelProposal(card) {
        if (card.state !== "proposed" || card.busy) return;
        const res = await this.orm.call("pmk.ai.chat", "cancel_proposal", [card.id]);
        Object.assign(card, res);
    },

    openResult(card) {
        if (!card.result) return;
        this.action.doAction({ type: "ir.actions.act_window", res_model: card.result.model,
                               res_id: card.result.id, views: [[false, "form"]], target: "current" });
    },
});
