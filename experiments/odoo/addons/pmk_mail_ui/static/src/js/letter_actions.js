/**
 * Действия «письмо → система» для меню «В работу ▾» над письмом и карточки
 * контрагента справа (почта проще, 25.10.2026: Антон — «очень много кнопок, в
 * которых путаешься»; прототип в чате, «делай везде»).
 *
 * Раньше «Лид» был в трёх местах (кнопка над письмом, карточка справа, значок
 * в строке списка), «Привязать к сделке» и «Создать контрагента» — только в
 * карточке. Теперь всё, что делает из письма запись в системе, — одно меню над
 * письмом; карточка справа — только сведения о контрагенте.
 *
 * cardStore — данные карточки (pmk_partner_card), которые карточка уже
 * загрузила для открытого письма: меню читает их, а не просит сервер второй
 * раз (правило «доработка не замедляет систему»). Карточки нет (телефон) —
 * меню показывает действия без уточнений, сервер проверяет сам.
 */
import { reactive } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { SelectCreateDialog } from "@web/views/view_dialogs/select_create_dialog";

import { PmkNewPartnerDialog } from "./partner_dialog";

// Карточка справа перечитывает данные по этому событию (partner_card.js).
export const CARD_RELOAD = "PMK_MAIL_CARD:RELOAD";

export const cardStore = reactive({ messageId: 0, card: null });

/** Данные карточки — только если они про это письмо (не про прежнее). */
export function cardFor(messageId) {
    return cardStore.messageId === messageId ? cardStore.card : null;
}

/** «Привязать к сделке»: выбор сделки, сначала — сделки этого контрагента. */
export function linkDealDialog(env, messageId, partner) {
    env.services.dialog.add(SelectCreateDialog, {
        resModel: "crm.lead",
        title: _t("Привязать письмо к сделке"),
        domain: [["type", "=", "opportunity"]],
        dynamicFilters: partner
            ? [
                  {
                      description: partner.name,
                      domain: [["partner_id", "child_of", partner.id]],
                  },
              ]
            : [],
        multiSelect: false,
        noCreate: true,
        onSelected: async ([leadId]) => {
            if (!leadId) {
                return;
            }
            const result = await env.services.orm.call("mail.client.message", "pmk_link_lead", [
                messageId,
                leadId,
            ]);
            env.services.notification.add(
                result.posted
                    ? _t("Письмо добавлено в сделку «%s»", result.name)
                    : _t("Письмо уже было в сделке «%s» — отмечено", result.name),
                { type: "success" }
            );
            env.bus.trigger(CARD_RELOAD);
        },
    });
}

/**
 * «Создать контрагента» (14.10.2026): окно «Новый контрагент из письма»
 * (partner_dialog.js) — найденное в письме, вложениях и справочнике, с
 * источниками. ИНН из письма уже есть в базе — окно откроет ту карточку.
 */
export async function createPartnerDialog(env, messageId) {
    const data = await env.services.orm.call("mail.client.message", "pmk_partner_from_letter", [
        messageId,
    ]);
    env.services.dialog.add(PmkNewPartnerDialog, {
        messageId,
        data,
        onDone: () => env.bus.trigger(CARD_RELOAD),
    });
}
