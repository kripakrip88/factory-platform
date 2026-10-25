/** @odoo-module **/
/**
 * Почта, остальное (разбор удобства, шаг 41, 05.10.2026) — связь списка
 * писем с лидами и счётчиком новых.
 *
 * Вид и поведение списка — в модуле почты (наша копия, vendor/README.md);
 * здесь то, что знает о лидах и о правилах завода:
 *   - фильтр «С лидом» в меню фильтров (крючки extraFilters /
 *     extraQuickFilters; с 25.10.2026 кружками только «Непрочитанные» и
 *     «Ждут ответа», остальное — в «Фильтр ▾») — тем, кто видит меню
 *     «В работу» с лидом (env.pmkCrm, reading_pane_lead.js);
 *   - значок сделки у строки (шаблон — xml/step41_mail.xml): щелчок
 *     открывает лид окном поверх почты, не создаёт новый; архивный —
 *     приглушённый, «в архиве» в подсказке;
 *   - значок сделки встаёт сразу после «Лид из письма» в меню «В работу»
 *     (значок «Лид» у строки при наведении убран 25.10.2026 — дубль меню);
 *   - значки при наведении в режиме переписок — как кнопки окна письма:
 *     «прочитано» гасит переписку целиком (pmkMarkThreadsSeen,
 *     thread_seen.js), «не прочитано» — одно письмо (pmkMarkUnseen); снять
 *     звезду — со всех отмеченных писем переписки (иначе звезда строки не
 *     снималась бы); поставить — письму строки;
 *   - правки в почте перечитывают счётчик новых (mail_counter.js).
 *
 * ПОРЯДОК ФАЙЛОВ. Ассеты модуля собираются по алфавиту: этот файл — после
 * reading_pane_lead.js (импорт ниже это закрепляет: патч его метода
 * pmkCreateLead обязан лечь поверх) и до thread_seen.js. Поэтому здесь
 * патчатся только методы модуля почты и reading_pane_lead.js, а методы
 * thread_seen.js (pmkMarkThreadsSeen, pmkMarkUnseen) только вызываются — на
 * момент вызова они уже на месте.
 */
import { useSubEnv } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";

import { MailClientInbox } from "@mail_client/mail_client_action";
import { MessageList } from "@mail_client/panes/message_list";
import { ReadingPane } from "@mail_client/panes/reading_pane";
import "@pmk_mail_ui/js/reading_pane_lead";
import { openFromMail } from "./mail_return";

/** Фильтр «С лидом»: имя — как на сервере (mail_client_step41.py, LEAD_FILTER). */
export const LEAD_FILTER = { id: "pmk_lead", label: "С лидом", icon: "fa-handshake-o" };

/** Подсказка значка сделки: слово, имя, «в архиве» (цвет повторён словом). */
export function dealTitle(lead) {
    if (!lead) {
        return "";
    }
    const word = lead.type === "opportunity" ? "Сделка" : "Лид";
    const archived = lead.active ? "" : " — в архиве";
    return `${word} «${lead.name || ""}»${archived}. Открыть`;
}

patch(MailClientInbox.prototype, {
    setup() {
        super.setup();
        const inbox = this;
        useSubEnv({
            pmkMail: {
                openLead: (lead) => inbox.pmkOpenLead(lead),
                refreshLead: (messageId) => inbox.pmkRefreshLead(messageId),
            },
        });
    },

    extraFilters() {
        const filters = super.extraFilters();
        return this.env?.pmkCrm ? [...filters, LEAD_FILTER] : filters;
    },

    extraQuickFilters() {
        const filters = super.extraQuickFilters();
        return this.env?.pmkCrm ? [...filters, LEAD_FILTER] : filters;
    },

    async rowSeen(message, value) {
        if (!this.state.threaded) {
            return super.rowSeen(message, value);
        }
        if (value) {
            // Как «Прочитано» в окне письма: переписка целиком.
            await this.pmkMarkThreadsSeen([message.id]);
        } else {
            await this.pmkMarkUnseen(message.id);
        }
        this.inboxUnreadChanged();
    },

    async rowFlagged(message, value) {
        if (!this.state.threaded || value) {
            return super.rowFlagged(message, value);
        }
        this.updateRow(message.id, { flag_flagged: false });
        const result = await this.trackListWrite(
            this.orm.call("mail.client.message", "pmk_set_threads_flagged", [], {
                message_ids: [message.id],
                value: false,
                unified: this.state.unified,
            })
        );
        const flagged = new Map(result.threads.map((t) => [t.thread_key, t.flagged]));
        const ids = new Set(result.ids);
        for (const row of this.state.messages) {
            if (row.thread_key && flagged.has(row.thread_key)) {
                row.flag_flagged = flagged.get(row.thread_key);
            }
        }
        for (const item of this.state.thread || []) {
            if (ids.has(item.id)) {
                item.flag_flagged = false;
            }
        }
        if (this.state.detail && ids.has(this.state.detail.id)) {
            this.state.detail.flag_flagged = false;
        }
        this.noteListEdit();
    },

    noteListEdit() {
        super.noteListEdit();
        this.env.services.pmk_mail_counter?.refresh();
    },

    inboxUnreadChanged() {
        super.inboxUnreadChanged();
        this.env?.services?.pmk_mail_counter?.refresh();
    },

    /** Значок сделки у строк письма и его переписки — сразу, без перечитывания. */
    pmkSetLead(messageId, threadKey, lead) {
        if (!lead) {
            return;
        }
        for (const row of this.state.messages) {
            if (row.id === messageId || (threadKey && row.thread_key === threadKey)) {
                row.pmk_lead = lead;
            }
        }
        this.noteListEdit();
    },

    async pmkRefreshLead(messageId) {
        const rows = await this.orm.call("mail.client.message", "pmk_lead_badges", [[messageId]]);
        for (const row of rows) {
            this.pmkSetLead(row.id, row.thread_key, row.lead);
        }
    },

    /** Лид — обычной страницей в этом же окне; «Почта» в строке пути
     *  возвращает на то же письмо (mail_return.js). */
    pmkOpenLead(lead) {
        if (!lead) {
            return;
        }
        openFromMail(this.env, "crm.lead", lead.id, this.state.selectedMessageId);
    },
});

patch(MessageList.prototype, {
    pmkDealTitle(lead) {
        return dealTitle(lead);
    },

    pmkOpenLead(message) {
        return this.env.pmkMail?.openLead(message.pmk_lead);
    },
});

patch(ReadingPane.prototype, {
    /** Кнопка «Лид» в окне письма — и значок сделки у строки списка. */
    async pmkCreateLead() {
        const messageId = this.props.detail?.id;
        await super.pmkCreateLead();
        if (messageId) {
            await this.env.pmkMail?.refreshLead(messageId);
        }
    },
});
