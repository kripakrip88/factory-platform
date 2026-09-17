/**
 * Чат документа: вниз, в единый поток, свёрнутым по умолчанию.
 *
 * ЗАЧЕМ. Штатно Odoo ставит чат сбоку от формы (режим SIDE_CHATTER), отдавая
 * ему около трети ширины. На приёмке это означало шесть полей и ОДНУ строку
 * товара в рабочей зоне — при том что в накладной главное именно строки.
 *
 * Главная претензия к боковому чату даже не место, а ВТОРАЯ ОБЛАСТЬ ПРОКРУТКИ
 * рядом с первой: колесо мыши работает по-разному в зависимости от того, где
 * курсор. Правило scroll-behavior запрещает конкурирующие области прокрутки.
 * Внизу чат живёт в общем потоке документа: шапка → строки → история, одна
 * прокрутка сверху вниз, как у бумажного документа.
 *
 * ТОЧКА ВМЕШАТЕЛЬСТВА. Ядро само решает раскладку одним методом
 * FormRenderer.mailLayout (mail/chatter/web/form_renderer.js), возвращая
 * SIDE_CHATTER или BOTTOM_CHATTER. Патчим только его — разметку ядра не трогаем,
 * при обновлении Odoo ломаться нечему.
 *
 * СВОРАЧИВАНИЕ. Свёрнутый чат не должен становиться невидимым, иначе никто не
 * узнает, что в заказе поставщику лежит сертификат и висит просроченная задача.
 * Поэтому в свёрнутом виде остаётся полоса со счётчиками: сообщения, вложения
 * и активности, причём просроченные помечены и числом, и значком, а не одним
 * цветом (правило color-not-only).
 *
 * Состояние запоминается ПО ТИПУ ДОКУМЕНТА: развернул историю в сделке — она
 * останется развёрнутой в сделках, но не полезет в складские накладные.
 */

import { patch } from "@web/core/utils/patch";
import { browser } from "@web/core/browser/browser";
import { useState } from "@odoo/owl";
import { FormRenderer } from "@web/views/form/form_renderer";
import { Chatter } from "@mail/chatter/web_portal/chatter";

/**
 * Документы, где переписка и есть работа: там историю показываем сразу.
 * Везде остальном (склад, производство, оплаты) — свёрнуто.
 */
const EXPANDED_BY_DEFAULT = new Set([
    "crm.lead",
    "sale.order",
    "purchase.order",
    "res.partner",
]);

patch(FormRenderer.prototype, {
    mailLayout(hasAttachmentContainer) {
        const layout = super.mailLayout(hasAttachmentContainer);
        // Единственная подмена: сбоку → вниз. Остальные раскладки (вложение
        // в отдельном окне, комбинированная) ядро считает само.
        return layout === "SIDE_CHATTER" ? "BOTTOM_CHATTER" : layout;
    },
});

patch(Chatter.prototype, {
    setup() {
        super.setup();
        this.pmk = useState({ collapsed: this.pmkInitialCollapsed() });
    },

    pmkStorageKey() {
        return `pmk_chatter_collapsed:${this.props.threadModel}`;
    },

    pmkInitialCollapsed() {
        // Выбор пользователя важнее умолчания — но только для этого типа документа.
        try {
            const saved = browser.localStorage.getItem(this.pmkStorageKey());
            if (saved !== null) {
                return saved === "1";
            }
        } catch {
            // Приватный режим или запрет на хранилище — молча берём умолчание.
        }
        return !EXPANDED_BY_DEFAULT.has(this.props.threadModel);
    },

    pmkToggle() {
        this.pmk.collapsed = !this.pmk.collapsed;
        // Состояние проставляем прямо в разметку, а не ждём перерисовки.
        //
        // Почему так: реактивность здесь не срабатывает. Замер показал, что
        // значение меняется и сохраняется, а разметка остаётся прежней до
        // перезагрузки страницы — ни useState, ни явный render() в патче
        // чужого компонента её не обновляют. Разбираться, на каком звене
        // цепочки патчей теряется подписка, дороже, чем поставить атрибут.
        //
        // Поэтому ВСЁ оформление полосы завязано на один этот атрибут
        // (см. forms.scss): и видимость содержимого, и поворот стрелки, и
        // показ счётчиков. Шаблон при этом статичен — ломаться нечему.
        this.pmkApplyState();
        try {
            browser.localStorage.setItem(this.pmkStorageKey(), this.pmk.collapsed ? "1" : "0");
        } catch {
            // Не смогли запомнить — не беда, поведение в этой сессии уже верное.
        }
    },

    /** Единственное место, где состояние попадает в разметку. */
    pmkApplyState() {
        const el = this.rootRef?.el;
        if (!el) {
            return;
        }
        el.dataset.pmkCollapsed = this.pmk.collapsed ? "1" : "0";
        const toggle = el.querySelector(".pmk-chatter-toggle");
        if (toggle) {
            toggle.setAttribute("aria-expanded", this.pmk.collapsed ? "false" : "true");
            toggle.setAttribute("title", this.pmk.collapsed ? "Показать историю" : "Свернуть историю");
        }
    },

    /** Что показать на свёрнутой полосе, чтобы её не приходилось открывать наугад. */
    get pmkCounts() {
        const thread = this.state.thread;
        const activities = thread?.activities ?? [];
        return {
            messages: thread?.messages?.length ?? 0,
            attachments: thread?.attachments?.length ?? 0,
            activities: activities.length,
            overdue: activities.filter((a) => a?.state === "overdue").length,
        };
    },
});
