/**
 * Окно «Новый лид из письма» (14.10.2026, Антон: «по аналогии с кнопкой
 * создать контрагента»). Вместо мгновенного лида и его формы в окошке —
 * что ляжет в лид и откуда взято, с правкой: название, клиент, контакт.
 * Клиента нет — «Создать контрагента…» (окно partner_dialog.js), новый
 * контрагент сразу встаёт клиентом лида.
 *
 * Все три входа — кнопка «Лид» над письмом, «Лид» у строки списка и кнопка
 * карточки справа — зовут openLeadDialog. Создаёт по-прежнему
 * action_pmk_create_lead (поправленное — overrides); лид уже есть —
 * открываем его. Лид и контрагент открываются обычной страницей в этом же
 * окне с возвратом на письмо (mail_return.js).
 */
import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

import { openFromMail } from "./mail_return";
import { PmkNewPartnerDialog } from "./partner_dialog";

/**
 * Открыть окно лида для письма. onDone(result) — после создания: значок
 * сделки у строки, карточка справа.
 */
export async function openLeadDialog(env, messageId, { onDone } = {}) {
    const draft = await env.services.orm.call("mail.client.message", "pmk_lead_draft", [messageId]);
    if (draft.denied) {
        env.services.notification.add(
            _t("Лид из письма заводит менеджер по продажам — у вас нет прав на лиды."),
            { type: "warning" }
        );
        return;
    }
    if (draft.existing) {
        env.services.notification.add(_t("У этого письма лид уже есть: %s", draft.existing.name), {
            type: "info",
            buttons: [{
                name: _t("Открыть лид"),
                primary: true,
                onClick: () => openFromMail(env, "crm.lead", draft.existing.id, messageId),
            }],
        });
        return;
    }
    env.services.dialog.add(PmkNewLeadDialog, { messageId, draft, onDone });
}

export class PmkNewLeadDialog extends Component {
    static template = "pmk_mail_ui.NewLeadDialog";
    static components = { Dialog };
    static props = {
        messageId: Number,
        draft: Object,
        onDone: { type: Function, optional: true },
        close: Function,
    };

    setup() {
        this.orm = this.env.services.orm;
        this.notification = this.env.services.notification;
        this.dialog = this.env.services.dialog;
        const draft = this.props.draft;
        this.state = useState({
            name: draft.lead.name,
            nameSource: draft.lead_sources.name,
            client: draft.client ? { ...draft.client } : null,
            candidates: draft.candidates || [],
            contact: { ...draft.contact },
            contactSources: { ...draft.contact_sources },
            busy: false,
            error: "",
        });
    }

    get draft() {
        return this.props.draft;
    }

    chooseClient(item) {
        this.state.client = item ? { ...item, how: this.draft.candidates_how || "" } : null;
    }

    setContact(key, value) {
        this.state.contact[key] = value;
        this.state.contactSources[key] = "";
    }

    setName(value) {
        this.state.name = value;
        this.state.nameSource = "";
    }

    /** Клиента нет — завести контрагента тем же окном, что в карточке справа. */
    async newPartner() {
        const data = await this.orm.call("mail.client.message", "pmk_partner_from_letter", [
            this.props.messageId,
        ]);
        this.dialog.add(PmkNewPartnerDialog, {
            messageId: this.props.messageId,
            data,
            onDone: async (partnerId) => {
                if (!partnerId) {
                    return;
                }
                const [partner] = await this.orm.read("res.partner", [partnerId], ["display_name"]);
                this.state.client = { id: partnerId, name: partner.display_name, how: _t("из окна контрагента") };
            },
        });
    }

    async create() {
        if (this.state.busy) {
            return;
        }
        if (!(this.state.name || "").trim()) {
            this.state.error = _t("Укажите название лида");
            return;
        }
        this.state.busy = true;
        try {
            const overrides = {
                name: this.state.name,
                partner_id: this.state.client ? this.state.client.id : false,
                contact_name: this.state.contact.contact_name || "",
                phone: this.state.contact.phone || "",
                email_from: this.state.contact.email_from || "",
            };
            const result = await this.orm.call(
                "mail.client.message", "action_pmk_create_lead", [[this.props.messageId], overrides]);
            const leadId = result.action?.res_id;
            this.notification.add(
                result.created ? _t("Лид создан: %s", this.state.name) : _t("У этого письма лид уже есть"),
                {
                    type: result.created ? "success" : "info",
                    buttons: leadId ? [{
                        name: _t("Открыть лид"),
                        primary: true,
                        onClick: () => openFromMail(this.env, "crm.lead", leadId, this.props.messageId),
                    }] : [],
                }
            );
            this.props.close();
            this.props.onDone?.(result);
        } finally {
            this.state.busy = false;
        }
    }
}
