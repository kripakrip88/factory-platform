/**
 * Карточка контрагента справа от письма (редизайн почты, шаг 7, 14.10.2026).
 *
 * Кто пишет и что с ним сейчас: ИНН, город, менеджер, писем за год, открытые
 * сделки и последние счета. Данные — pmk_partner_card (models/mail_partner_card.py).
 *
 * 25.10.2026 (почта проще): кнопки действий («Лид из письма», «Привязать к
 * сделке», «Создать / Открыть контрагента») переехали в меню «В работу ▾» над
 * письмом (letter_actions.js) — карточка только показывает сведения и отдаёт
 * загруженное меню через cardStore (второго запроса нет).
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

import { MailClientInbox } from "@mail_client/mail_client_action";
import { CARD_RELOAD, cardStore } from "./letter_actions";
import { openFromMail } from "./mail_return";

const PREF = "pmk_mail.partner_card";
// Меню «В работу ▾» над письмом (reading_pane_lead.js, letter_actions.js) шлёт
// CARD_RELOAD — карточка узнаёт о новом лиде, сделке, контрагенте.

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
        this.state = useState({ open: readOpen(), card: null, loading: false });
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
                Object.assign(cardStore, { messageId, card });
            }
        } catch {
            if (token === this.token) {
                this.state.card = null;
                Object.assign(cardStore, { messageId, card: null });
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

    /** Сделка, лид, счёт — обычной страницей в новой вкладке, как контрагент. */
    openRecord(resModel, resId) {
        openFromMail(this.env, resModel, resId, this.props.messageId);
    }

    /**
     * Карточка контрагента — обычной страницей в новой вкладке браузера
     * (Антон 14.10.2026: форма контрагента в окошке — «недоразумение»).
     * Почта с открытым письмом остаётся как была.
     */
    openPartner(partnerId) {
        openFromMail(this.env, "res.partner", partnerId, this.props.messageId);
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
}

patch(MailClientInbox, {
    components: { ...MailClientInbox.components, PmkPartnerCard },
});
