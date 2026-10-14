/**
 * Карточка контрагента справа от письма (редизайн почты, шаг 7, 14.10.2026).
 *
 * Кто пишет и что с ним сейчас: ИНН, город, менеджер, писем за год, открытые
 * сделки и последние счета; «Лид из письма», «Привязать к сделке», «Открыть
 * контрагента». Данные — pmk_partner_card (models/mail_partner_card.py).
 *
 * Сворачивается вправо в узкую полосу (решение Антона: «только с
 * возможностью свернуть вправо»); положение запоминается в браузере. На
 * телефоне карточки нет — там письмо на весь экран.
 *
 * Карточки и сделки открываются окном (target new), как лид из кнопки «Лид»:
 * у почтового модуля нет сохранения состояния, возврат по хлебным крошкам
 * пересоздал бы его — человек потерял бы открытое письмо.
 *
 * Запросы — через env.services.orm, а не useService: общий запрос вида
 * (память проекта, «useService вешает вид»).
 */
import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useBus } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { SelectCreateDialog } from "@web/views/view_dialogs/select_create_dialog";

import { MailClientInbox } from "@mail_client/mail_client_action";

const PREF = "pmk_mail.partner_card";
// Кнопка «Лид» над письмом (reading_pane_lead.js) шлёт это же событие —
// карточка узнаёт о новом лиде.
const CARD_RELOAD = "PMK_MAIL_CARD:RELOAD";

function readOpen() {
    try {
        const value = window.localStorage.getItem(PREF);
        if (value) {
            return value === "open";
        }
    } catch {
        // Хранилище недоступно (приватное окно) — по ширине экрана.
    }
    return window.innerWidth >= 1280;
}

function writeOpen(open) {
    try {
        window.localStorage.setItem(PREF, open ? "open" : "closed");
    } catch {
        // Не запомнили — не беда.
    }
}

export class PmkPartnerCard extends Component {
    static template = "pmk_mail_ui.PartnerCard";
    static props = {
        messageId: { type: Number },
    };

    setup() {
        this.orm = this.env.services.orm;
        this.action = this.env.services.action;
        this.dialog = this.env.services.dialog;
        this.notification = this.env.services.notification;
        this.state = useState({ open: readOpen(), card: null, loading: false, busy: false });
        this.token = 0;
        onWillStart(() => this.load(this.props.messageId));
        onWillUpdateProps((next) => {
            if (next.messageId !== this.props.messageId) {
                this.load(next.messageId);
            }
        });
        useBus(this.env.bus, CARD_RELOAD, () => this.load(this.props.messageId));
    }

    async load(messageId) {
        const token = ++this.token;
        this.state.loading = true;
        try {
            const card = await this.orm.call("mail.client.message", "pmk_partner_card", [messageId]);
            if (token === this.token) {
                this.state.card = card;
            }
        } catch {
            if (token === this.token) {
                this.state.card = null;
            }
        } finally {
            if (token === this.token) {
                this.state.loading = false;
            }
        }
    }

    toggle() {
        this.state.open = !this.state.open;
        writeOpen(this.state.open);
    }

    get howLabel() {
        switch (this.state.card?.how) {
            case "inn":
                return _t("найден по ИНН из письма");
            case "domain":
                return _t("найден по домену адреса");
            case "lead":
                return _t("по сделке письма");
            default:
                return "";
        }
    }

    get dealsMore() {
        const card = this.state.card;
        return card ? card.deals_total - card.deals.length : 0;
    }

    get invoicesMore() {
        const card = this.state.card;
        return card ? card.invoices_total - card.invoices.length : 0;
    }

    openRecord(resModel, resId) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: resModel,
            res_id: resId,
            views: [[false, "form"]],
            target: "new",
        });
    }

    openList(resModel, name, domain) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: resModel,
            domain,
            views: [
                [false, "list"],
                [false, "form"],
            ],
            target: "new",
        });
    }

    openDeals() {
        const partner = this.state.card.partner;
        this.openList("crm.lead", _t("Сделки: %s", partner.name), [
            ["partner_id", "child_of", partner.id],
            ["type", "=", "opportunity"],
        ]);
    }

    openInvoices() {
        const partner = this.state.card.partner;
        this.openList("sale.order", _t("Счета: %s", partner.name), [
            ["partner_id", "child_of", partner.id],
        ]);
    }

    /**
     * «Создать контрагента» (14.10.2026): реквизиты и контакт из письма и его
     * вложений правилами (models/mail_partner_card.py, tools/requisites.py),
     * по ИНН — справочник. Окно карточки заполнено, но не сохранено:
     * сохраняет человек, проверив. Что и откуда взято — уведомлением.
     */
    async createPartner() {
        if (this.state.busy) {
            return;
        }
        this.state.busy = true;
        try {
            const result = await this.orm.call("mail.client.message", "pmk_partner_from_letter", [
                this.props.messageId,
            ]);
            if (result.found.length) {
                this.notification.add(result.found.join(" · "), {
                    title: _t("Найдено в письме"),
                    type: "info",
                });
            }
            for (const warning of result.warnings) {
                this.notification.add(warning, { type: "warning", sticky: true });
            }
            await this.action.doAction(result.action, {
                onClose: () => this.load(this.props.messageId),
            });
        } finally {
            this.state.busy = false;
        }
    }

    async createLead() {
        if (this.state.busy) {
            return;
        }
        this.state.busy = true;
        try {
            const result = await this.orm.call("mail.client.message", "action_pmk_create_lead", [
                [this.props.messageId],
            ]);
            this.notification.add(result.created ? _t("Лид создан") : _t("Из этого письма лид уже есть"), {
                type: result.created ? "success" : "info",
            });
            await this.action.doAction(result.action, {
                onClose: () => this.load(this.props.messageId),
            });
        } finally {
            this.state.busy = false;
        }
    }

    linkDeal() {
        const partner = this.state.card.partner;
        this.dialog.add(SelectCreateDialog, {
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
                const result = await this.orm.call("mail.client.message", "pmk_link_lead", [
                    this.props.messageId,
                    leadId,
                ]);
                this.notification.add(
                    result.posted
                        ? _t("Письмо добавлено в сделку «%s»", result.name)
                        : _t("Письмо уже было в сделке «%s» — отмечено", result.name),
                    { type: "success" }
                );
                await this.load(this.props.messageId);
            },
        });
    }
}

patch(MailClientInbox, {
    components: { ...MailClientInbox.components, PmkPartnerCard },
});
