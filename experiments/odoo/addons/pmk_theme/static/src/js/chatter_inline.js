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
 *
 * ШИРОКИЙ ЭКРАН (шаг 49Б, 10.10.2026). От 2200 px (ASIDE_MIN_WIDTH,
 * js/chatter_aside_rules.js) лента — СПРАВА от листа: штатный боковой режим
 * ядра (SIDE_CHATTER — класс o-aside, своя прокрутка ленты), не своя
 * раскладка. Лист шага 49 упирается в 1800 px, и на экране 2560 справа
 * оставалось ~760 px пустоты. Две области прокрутки — осознанно: решение
 * Антона 10.10 «давай попробуем, я проверю, если не понравится вернём».
 * Сбоку история всегда развёрнута (свёрнутая полоса справа — пустая колонка),
 * выбор «свёрнуто» действует, когда лента снова под листом. Уже 2200 — всё
 * как было. Ширины ленты и листа — forms_nexus.scss, раздел «Шаг 49Б».
 * Откат: ASIDE_MIN_WIDTH = Infinity (или удалить раздел и вернуть подмену
 * SIDE → BOTTOM без условия).
 */

import { patch } from "@web/core/utils/patch";
import { browser } from "@web/core/browser/browser";
import { onMounted, onWillUnmount, useEffect, useState } from "@odoo/owl";
import { FormRenderer } from "@web/views/form/form_renderer";
import { Chatter } from "@mail/chatter/web_portal/chatter";
import {
    ASIDE_MEDIA,
    ASIDE_MIN_WIDTH,
    chatterLayout,
    collapsedNow,
    isWideViewport,
    shouldApplyOnWidth,
} from "@pmk_theme/js/chatter_aside_rules";

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

/**
 * Окно не уже порога шага 49Б. matchMedia — та же мера, что у @media в SCSS
 * (с полосой прокрутки и масштабом страницы); нет его — ширина окна.
 */
function pmkWide() {
    const query = browser.matchMedia?.(ASIDE_MEDIA);
    if (query) {
        return Boolean(query.matches);
    }
    return isWideViewport(browser.innerWidth, ASIDE_MIN_WIDTH);
}

patch(FormRenderer.prototype, {
    mailLayout(hasAttachmentContainer) {
        // Единственная подмена: сбоку → вниз, если окно уже порога шага 49Б.
        // Остальные раскладки (вложение в отдельном окне, комбинированная)
        // ядро считает само. Смену ширины ядро ловит само: рендерер ленты
        // перерисовывается по resize (mail/chatter/web/form_renderer.js).
        return chatterLayout(super.mailLayout(hasAttachmentContainer), pmkWide());
    },
});

patch(Chatter.prototype, {
    setup() {
        super.setup();
        this.pmk = useState({ collapsed: this.pmkInitialCollapsed() });
        // Лента переехала вбок или вниз (смена ширины окна) — атрибут
        // состояния ставим заново: кнопка пишет его прямо в разметку, и
        // перерисовка с тем же значением в шаблоне его не поправит.
        useEffect(() => this.pmkApplyState(), () => [this.props.isChatterAside]);
        // Порог 2200 перешли, а раскладка ленты от этого не поменялась
        // (вложение в отдельном окне — EXTERNAL_COMBO_XXL): тоже пересчитать.
        // Только при РАСШИРЕНИИ окна (shouldApplyOnWidth). При сужении через
        // 2200 рендерер ядра перекладывает ленту вниз лишь через 200 мс после
        // конца перетаскивания (useDebounced(render, 200)), а @media раздела
        // 49Б гаснет сразу: свернуть ленту в этот миг — значит показать
        // справа пустую полосу шириной ядра. Без пересчёта лента эти 200 мс
        // стоит развёрнутой, потом уходит вниз, и useEffect выше ставит
        // выбор «свёрнуто». Цена: в EXTERNAL_COMBO_XXL после сужения лента
        // остаётся развёрнутой до следующего открытия — история видна, а
        // кнопка «История» уже под рукой.
        const query = browser.matchMedia?.(ASIDE_MEDIA);
        const onWidth = (ev) => {
            if (shouldApplyOnWidth(ev?.matches ?? query?.matches)) {
                this.pmkApplyState();
            }
        };
        onMounted(() => query?.addEventListener?.("change", onWidth));
        onWillUnmount(() => query?.removeEventListener?.("change", onWidth));
    },

    /** Лента сейчас сбоку от листа на широком экране (шаг 49Б). */
    get pmkAsideNow() {
        return Boolean(this.props.isChatterAside) && pmkWide();
    },

    /** Свёрнута ли история сейчас: сбоку на широком экране — никогда. */
    get pmkCollapsedNow() {
        return collapsedNow(this.pmk.collapsed, this.pmkAsideNow);
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
        const collapsed = this.pmkCollapsedNow;
        el.dataset.pmkCollapsed = collapsed ? "1" : "0";
        const toggle = el.querySelector(".pmk-chatter-toggle");
        if (toggle) {
            toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
            toggle.setAttribute("title", collapsed ? "Показать историю" : "Свернуть историю");
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
