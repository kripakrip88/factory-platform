import { Component, useEffect, useRef, useState } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";

import { formatMessageDate, pluralForm } from "../utils";
import { Conversation, newestOf } from "./conversation";
import { MessageCard } from "./message_card";

/**
 * ПРАВКА ПМК: форма числа писем по правилам языка («14 писем», «2 письма»,
 * «1 письмо») — pluralForm (utils.js). Строки перевода пишем в _t целиком, а
 * не собираем: сборщик перевода берёт только их. user.lang уже в виде
 * браузера («ru-RU»), не Odoo («ru_RU»).
 */
function threadCountLabel(count) {
    const form = pluralForm(count, user.lang);
    if (form === "one") {
        return _t("%s message in thread", count);
    }
    if (form === "few") {
        return _t("%s messages in thread (2-4)", count);
    }
    return _t("%s messages in thread", count);
}

/**
 * Окно чтения: закреплённая строка над письмом (шаг 17) и окно прокрутки.
 *
 * ПРАВКА ПМК (шаг 20, 30.09.2026): письмо без переписки — карточка
 * MessageCard (разметка шага 17 как была); переписка из двух писем и
 * больше (режим переписок) — лента Conversation, новые сверху. Закреплённая
 * строка и «⋯» по-прежнему действуют на открытое письмо (строку списка).
 * Цепочка «ReadingPane → Conversation → MessageCard» — хрупкое место,
 * см. vendor/README.md.
 */
export class ReadingPane extends Component {
    static template = "mail_client.ReadingPane";
    static components = { Dropdown, DropdownItem, Conversation, MessageCard };
    static props = {
        detail: { optional: true },
        loading: { type: Boolean },
        moveTargets: { type: Array, optional: true },
        // False on a read-only mailbox, where the server refuses move and
        // delete rather than dropping mail from Odoo that is still on IMAP.
        canAct: { type: Boolean, optional: true },
        thread: { type: Array, optional: true },
        contact: { optional: true },
        onSelectMessage: { type: Function },
        onDownloadEml: { type: Function },
        onAllowImages: { type: Function },
        onToggleSeen: { type: Function },
        onToggleFlagged: { type: Function },
        onMove: { type: Function },
        onDelete: { type: Function },
        onReply: { type: Function },
        onDownloadAttachment: { type: Function },
        // ПРАВКА ПМК (разбор шага 20): письмо ленты показано — крючок корня
        // conversationShown (отметку «прочитано» ставит pmk_mail_ui).
        onConversationShown: { type: Function, optional: true },
        // ПРАВКА ПМК (шаг 41, А10): где окно чтения — 'right' (рядом со
        // списком), 'full' (на весь экран: «← К списку», ↑ ↓) или 'phone'
        // (телефон: всегда вместо списка). ⤢ — переключить 'right' / 'full'.
        layout: { type: String, optional: true },
        hasPrev: { type: Boolean, optional: true },
        hasNext: { type: Boolean, optional: true },
        onBack: { type: Function, optional: true },
        onNeighbour: { type: Function, optional: true },
        onToggleLayout: { type: Function, optional: true },
    };

    setup() {
        this.notification = useService("notification");
        this.state = useState({
            showContact: false,
        });

        // ПРАВКА ПМК (шаг 17): одна прокрутка у окна чтения, рамка — ростом
        // с письмо (frame_fit.js; с шага 20 рамкой ведает MessageCard — у
        // каждого развёрнутого письма переписки своя).
        this.scrollerRef = useRef("scroller");
        this.getScroller = () => this.scrollerRef.el;
        // Другое письмо на экране — читаем его с начала. Окно прокрутки то же
        // самое (прежнее письмо на время загрузки не убирается), поэтому само
        // оно наверх не вернётся.
        useEffect(
            () => {
                if (this.scrollerRef.el) {
                    this.scrollerRef.el.scrollTop = 0;
                }
            },
            () => [this.props.detail?.id]
        );
    }

    /**
     * Пока грузится следующее письмо, на экране прежнее — бледное и
     * недоступное (inert): ни щелчком, ни с клавиатуры. Кнопки действуют на
     * выделенную строку, а она уже другая: Tab до флажка и пробел отметили
     * бы новое письмо, «Удалить» из «⋯» удалило бы его.
     */
    get stale() {
        return Boolean(this.props.loading && this.props.detail);
    }

    // ПРАВКА ПМК: см. комментарий в mail_client_action.js.
    get seenTitle() {
        return this.props.detail?.flag_seen ? _t("Mark as unread") : _t("Mark as read");
    }

    // ПРАВКА ПМК: подписи для строки над письмом и меню «⋯».
    get contactTitle() {
        return this.state.showContact ? _t("Hide contact") : _t("Show contact");
    }

    /** Писем в переписке, считая открытое; 0 — не показывать. С шага 20
     *  от этого же числа зависит, показывать ли ленту переписки. */
    get threadCount() {
        const count = this.props.thread ? this.props.thread.length : 0;
        return count > 1 ? count : 0;
    }

    get threadCountLabel() {
        return threadCountLabel(this.threadCount);
    }

    get threadCountTitle() {
        return _t("%s messages", this.threadCount);
    }

    // ПРАВКА ПМК (шаг 41, А10): «на весь экран», «← К списку», ↑ ↓.
    get showBack() {
        return Boolean(this.props.onBack && this.props.layout && this.props.layout !== "right");
    }

    get showNeighbours() {
        return Boolean(this.props.onNeighbour && this.props.layout === "full");
    }

    get showLayoutToggle() {
        return Boolean(this.props.onToggleLayout && this.props.layout && this.props.layout !== "phone");
    }

    get backTitle() {
        return _t("Back to the list (Esc)");
    }

    get prevTitle() {
        return _t("Previous message (↑)");
    }

    get nextTitle() {
        return _t("Next message (↓)");
    }

    get layoutTitle() {
        return this.props.layout === "full"
            ? _t("Show the message next to the list")
            : _t("Open the message on full screen");
    }

    /**
     * ПРАВКА ПМК (разбор шага 20, 30.09.2026): на какое письмо отвечают
     * «Ответить / Всем» закреплённой строки. null — на открытое (строку), как
     * было.
     *
     * Строка — НАШЕ письмо (открыли в «Отправленных»), а лента показывает
     * сверху, прямо под строкой, более поздний ответ клиента. Ответ на
     * письмо строки ушёл бы нам же (Г3, mail_client_compose.py) с нашим
     * текстом в цитате. Тогда отвечаем на самое новое НЕ наше письмо
     * переписки — последнее, что написал клиент. «Переслать» — по-прежнему
     * письмо строки. Без ленты, когда строка не наша или в переписке только
     * наши письма — письмо строки.
     */
    get replyTargetId() {
        const thread = this.threadCount ? this.props.thread : [];
        const row = thread.find((item) => item.id === this.props.detail.id);
        if (!row || !row.is_outgoing) {
            return null;
        }
        const theirs = newestOf(thread.filter((item) => !item.is_outgoing));
        return theirs ? theirs.id : null;
    }

    toggleContact() {
        this.state.showContact = !this.state.showContact;
        // Карточка встаёт над письмом — показать её, даже если письмо уже
        // прокручено вниз.
        if (this.state.showContact && this.scrollerRef.el) {
            this.scrollerRef.el.scrollTop = 0;
        }
    }

    /**
     * Колесо над закреплённой строкой крутит письмо: прокрутка у окна чтения
     * одна, «где бы ни стоял курсор». Сама строка крутится только вбок (на
     * узком окне), поэтому отдаём ей горизонтальное колесо и Ctrl+колесо
     * (масштаб страницы).
     */
    onToolbarWheel(ev) {
        const scroller = this.scrollerRef.el;
        if (!scroller || ev.ctrlKey || Math.abs(ev.deltaY) <= Math.abs(ev.deltaX)) {
            return;
        }
        const unit = ev.deltaMode === 1 ? 16 : ev.deltaMode === 2 ? scroller.clientHeight : 1;
        scroller.scrollTop += ev.deltaY * unit;
    }

    formatDate(value) {
        return formatMessageDate(value);
    }

    onMoveTo(folderId) {
        this.props.onMove(folderId);
    }
}
