/** @odoo-module **/
/**
 * Почта открывается на нужном ящике и письме (разбор UX, шаг 53,
 * 07.10.2026). Правила — step53_open_rules.js, параметры действий —
 * data/menus.xml.
 *
 *   • «Закупки → Почта» — ящик закупок, «Продажи → Почта» — заявки
 *     (params.pmk_mailbox). Раньше оба пункта открывали первый ящик по
 *     порядку.
 *   • Щелчок по «Письму» на вкладке «Связи» (pmk_flow) — само письмо
 *     (params.pmk_message_id): папка письма встаёт первой, письмо
 *     открывается, как будто по нему щёлкнули в списке. Показывает его
 *     штатное окно почты — тело очищено на отдаче, как всегда.
 *
 * КАК. Модуль почты в onWillStart зовёт loadAccounts(), затем
 * firstFolderId() и открывает эту папку. Папку письма надо знать ДО
 * firstFolderId, поэтому её спрашиваем внутри первого loadAccounts —
 * вместе с ящиками, одним ожиданием. Свой onWillStart не годится: Owl
 * запускает onWillStart компонента одновременно, и ответ мог прийти после
 * выбора папки. loadAccounts зовут и потом (обновления, отметки) —
 * папку спрашиваем только при первом. Письмо открываем после
 * монтирования (selectRow — тот же путь, что щелчок по строке: отметка
 * «прочитано», переписка, thread_seen.js).
 */
import { onMounted } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

import { MailClientInbox } from "@mail_client/mail_client_action";
import { hasFolder, openParams, pickFolder } from "@pmk_mail_ui/js/step53_open_rules";

patch(MailClientInbox.prototype, {
    setup() {
        super.setup();
        this.pmkOpen = openParams(this.props.action?.params);
        onMounted(() => {
            const open = this.pmkOpen;
            if (!open.messageId) {
                return;
            }
            if (open.folderId) {
                this.pmkOpenLetter(open.messageId);
            } else {
                // Сигнал, а не молчание: просили письмо, а открылись
                // «Входящие». Вкладка «Связи» такого письма в почту уже не
                // шлёт (pmk_flow, _letter_action), сюда доходят только
                // гонки: папку отписали, письмо удалили после схемы.
                this.notification.add(
                    _t("Этого письма нет в вашей почте — открыты «Входящие»."),
                    { type: "warning" }
                );
            }
        });
    },

    async loadAccounts() {
        const open = this.pmkOpen;
        if (!open || open.asked || !open.messageId) {
            return super.loadAccounts();
        }
        open.asked = true;
        const [, folderId] = await Promise.all([
            super.loadAccounts(),
            this.pmkFolderOf(open.messageId),
        ]);
        // Папка не в дереве человека (ящик не его, папка не подписана) —
        // письмо не открываем: список показал бы одно, а окно письма —
        // другое. Сервер такую папку и не вернёт (_pmk_tree_folder_id),
        // проверка — на случай старого сервера.
        open.folderId = hasFolder(this.state.accounts, folderId) ? folderId : null;
    },

    /** Папка письма, если человеку можно его читать; иначе null. */
    async pmkFolderOf(messageId) {
        try {
            return (await this.orm.call("mail.client.message", "pmk_folder_of", [messageId])) || null;
        } catch {
            return null;
        }
    },

    firstFolderId() {
        return pickFolder(this.state.accounts, this.pmkOpen) || super.firstFolderId();
    },

    async pmkOpenLetter(messageId) {
        try {
            await this.selectRow(messageId);
        } catch {
            this.notification.add(_t("Письмо не открылось — оно в списке папки."), {
                type: "warning",
            });
        }
    },
});
