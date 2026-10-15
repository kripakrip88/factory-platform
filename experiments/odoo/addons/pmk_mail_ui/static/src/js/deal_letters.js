/** @odoo-module **/
/**
 * Вкладка «Письма» в сделке (15.10.2026) — <widget name="pmk_deal_letters"/>.
 *
 * Антон 15.10: из сделки приходилось переключаться в почту, чтобы прочитать
 * письмо и взять файлы. Прототип принят («отлично»): слева письма сделки и
 * «Ещё письма клиента — не привязаны», справа текст и вложения выбранного,
 * кнопки «Ответить», «Открыть в почте», «В отдельном окне».
 *
 * Данные — crm.lead.pmk_deal_letters (models/crm_lead_letters.py), текст и
 * вложения — get_message_detail почты (то же, что окно чтения: права, тело
 * очищено на отдаче), в рамке sandbox без скриптов, высота — followFrame
 * почты. Просмотр вложения — окно просмотра почты (AttachmentPreviewDialog),
 * скачивание — mail.client.attachment.download, как в почте.
 *
 * Сервисы — env.services, не useService: промисы orm не должны зависеть от
 * жизни компонента (грабля шага 31: useService вешал вид), а ответ, пришедший
 * после закрытия вкладки, просто не пишем (alive()).
 */
import { Component, status, useEffect, useRef, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { AttachmentPreviewDialog } from "@mail_client/attachments/attachment_preview_dialog";
import { followFrame } from "@mail_client/panes/frame_fit";
import { formatMessageDate, formatSize, recipientLabel, senderName } from "@mail_client/utils";

export class PmkDealLetters extends Component {
    static template = "pmk_mail_ui.DealLetters";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = this.env.services.orm;
        this.dialog = this.env.services.dialog;
        this.notification = this.env.services.notification;
        this.action = this.env.services.action;
        this.frameRef = useRef("frame");
        this.readerRef = useRef("reader");
        this.state = useState({
            loading: true,
            data: null,
            showAll: false,
            selectedId: null,
            detail: null,
            detailLoading: false,
            busy: null,
        });
        this.loadSeq = 0;
        this.detailSeq = 0;
        useEffect(
            (resId) => {
                this.state.selectedId = null;
                this.state.detail = null;
                this.state.showAll = false;
                this.load(resId, { pickFirst: true });
            },
            () => [this.props.record.resId]
        );
        // Высота рамки — по письму (frame_fit.js почты), прокрутка — окно
        // чтения справа.
        useEffect(
            (body) => {
                const frame = this.frameRef.el;
                if (!frame || !body) {
                    return;
                }
                return followFrame(frame, { getScroller: () => this.readerRef.el });
            },
            () => [this.state.detail?.body]
        );
    }

    alive() {
        return status(this) !== "destroyed";
    }

    get leadId() {
        return this.props.record.resId || false;
    }

    // ------------------------------------------------------------------
    // данные
    // ------------------------------------------------------------------
    async load(resId = this.leadId, { pickFirst = false } = {}) {
        if (!resId) {
            this.state.loading = false;
            this.state.data = null;
            return;
        }
        const seq = ++this.loadSeq;
        this.state.loading = true;
        const data = await this.orm.call("crm.lead", "pmk_deal_letters", [resId], {
            show_all: this.state.showAll,
        });
        if (!this.alive() || seq !== this.loadSeq) {
            return;
        }
        this.state.data = data;
        this.state.loading = false;
        const first = data.letters?.[0] || data.candidates?.[0];
        if (pickFirst && first && !this.state.selectedId) {
            this.select(first.id);
        }
    }

    async select(messageId) {
        if (this.state.selectedId === messageId && this.state.detail) {
            return;
        }
        const seq = ++this.detailSeq;
        this.state.selectedId = messageId;
        this.state.detailLoading = true;
        let detail = null;
        try {
            detail = await this.orm.call("mail.client.message", "get_message_detail", [messageId]);
        } finally {
            if (this.alive() && seq === this.detailSeq) {
                this.state.detailLoading = false;
            }
        }
        if (!this.alive() || seq !== this.detailSeq) {
            return;
        }
        this.state.detail = detail;
    }

    toggleShowAll() {
        this.state.showAll = !this.state.showAll;
        this.load();
    }

    // ------------------------------------------------------------------
    // строки
    // ------------------------------------------------------------------
    get letters() {
        return this.state.data?.letters || [];
    }

    get candidates() {
        return this.state.data?.candidates || [];
    }

    get selectedRow() {
        const id = this.state.selectedId;
        return this.letters.find((row) => row.id === id) || this.candidates.find((row) => row.id === id) || null;
    }

    get selectedLinked() {
        const id = this.state.selectedId;
        return this.letters.some((row) => row.id === id);
    }

    /** Письмо другой сделки (не этой) — серым, перепривязка с подтверждением. */
    otherLead(row) {
        return row.lead && !row.lead.same ? row.lead : null;
    }

    who(row) {
        return row.is_outgoing ? _t("Мы → %s", recipientLabel(row.email_to)) : senderName(row.email_from);
    }

    when(value) {
        return formatMessageDate(value);
    }

    size(bytes) {
        return formatSize(bytes);
    }

    leadLabel(lead) {
        return lead.number || lead.name || _t("другая сделка");
    }

    get keysHint() {
        const data = this.state.data;
        if (!data) {
            return "";
        }
        const parts = [];
        const mails = data.mails || [];
        if (mails.length) {
            const shown = mails.slice(0, 2).join(", ");
            parts.push(mails.length > 2 ? _t("%(shown)s и ещё %(more)s", { shown, more: mails.length - 2 }) : shown);
        }
        if (data.domains?.length) {
            parts.push(data.domains.map((domain) => "@" + domain).join(", "));
        }
        const period = data.show_all ? _t("за всё время") : _t("за 3 месяца");
        return parts.length ? `${parts.join(" · ")} · ${period}` : "";
    }

    onRowKey(ev, row) {
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            this.select(row.id);
        }
    }

    // ------------------------------------------------------------------
    // действия
    // ------------------------------------------------------------------
    async link(row, { force = false } = {}) {
        const other = this.otherLead(row);
        if (other && !force) {
            this.dialog.add(ConfirmationDialog, {
                title: _t("Перепривязать письмо?"),
                body: _t(
                    "Письмо «%(subject)s» сейчас в сделке %(lead)s. Привязать его к этой сделке? В той сделке письмо останется в ленте, но из её вкладки «Письма» уйдёт.",
                    { subject: row.subject, lead: this.leadLabel(other) }
                ),
                confirmLabel: _t("Перепривязать"),
                confirm: () => this.link(row, { force: true }),
                cancel: () => {},
            });
            return;
        }
        this.state.busy = row.id;
        try {
            const result = await this.orm.call("mail.client.message", "pmk_link_lead", [row.id, this.leadId]);
            if (!this.alive()) {
                return;
            }
            this.notification.add(
                result?.posted
                    ? _t("Письмо привязано — текст и файлы в ленте сделки, файлы во вкладке «Файлы».")
                    : _t("Письмо привязано."),
                { type: "success" }
            );
            await this.load();
        } finally {
            if (this.alive()) {
                this.state.busy = null;
            }
        }
    }

    unlink(row) {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Отвязать письмо?"),
            body: _t(
                "Письмо «%s» уйдёт из вкладки «Письма» в «Ещё письма клиента». Копия в ленте сделки и файлы во вкладке «Файлы» останутся.",
                row.subject
            ),
            confirmLabel: _t("Отвязать"),
            confirm: async () => {
                await this.orm.call("mail.client.message", "pmk_unlink_lead", [row.id, this.leadId]);
                if (this.alive()) {
                    await this.load();
                }
            },
            cancel: () => {},
        });
    }

    async openInMail(reply = false) {
        const messageId = this.state.selectedId;
        if (!messageId) {
            return;
        }
        const action = await this.orm.call("mail.client.message", "pmk_letter_mail_action", [messageId], {
            reply,
        });
        if (!this.alive()) {
            return;
        }
        if (!action) {
            this.notification.add(
                _t("Этого письма нет в вашей почте: ящик не ваш или папка не подписана."),
                { type: "warning" }
            );
            return;
        }
        // Сохранить сделку перед уходом — как переход по кнопке формы.
        if (this.props.record.isDirty && !(await this.props.record.save())) {
            return;
        }
        await this.action.doAction(action);
    }

    openWindow() {
        const messageId = this.state.selectedId;
        if (!messageId) {
            return;
        }
        // Отдельное окно браузера рядом со сделкой (не вкладка): размер —
        // половина экрана. noopener — странице письма незачем окно сделки.
        const width = Math.max(720, Math.round(window.screen.availWidth / 2));
        const height = Math.max(600, window.screen.availHeight - 80);
        window.open(
            `/pmk_mail/letter/${messageId}`,
            `pmk_letter_${messageId}`,
            `popup=yes,width=${width},height=${height},noopener`
        );
    }

    preview(attachment) {
        this.dialog.add(AttachmentPreviewDialog, {
            attachmentId: attachment.id,
            name: attachment.name,
            onDownload: () => this.download(attachment),
        });
    }

    async download(attachment) {
        this.state.busy = `a${attachment.id}`;
        try {
            const result = await this.orm.call("mail.client.attachment", "download", [], {
                attachment_id: attachment.id,
            });
            if (result && result.url) {
                window.open(result.url, "_blank");
            }
        } finally {
            if (this.alive()) {
                this.state.busy = null;
            }
        }
    }

    get sandbox() {
        return "allow-same-origin allow-popups allow-popups-to-escape-sandbox";
    }
}

registry.category("view_widgets").add("pmk_deal_letters", { component: PmkDealLetters });
