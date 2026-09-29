import { Component, onMounted, onPatched, onWillUnmount, useRef, useState } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";

import {
    dayBucket,
    formatMessageDate,
    pluralForm,
    readPref,
    recipientLabel,
    senderName,
    writePref,
} from "../utils";
import { buildListItems } from "./list_items";

// ПРАВКА ПМК (шаг 18): вид списка — «удобный» (две строки) или «компактный»
// (одна строка, колонка шире). Помнится в браузере; значение по умолчанию —
// удобный. Живёт здесь, а не в корне: это только вид списка.
const LIST_VIEW_KEY = "mail_client.list_view";
const LIST_VIEWS = ["comfortable", "compact"];
// ПРАВКА ПМК (шаг 22): «в начале списка» — прокрутка не дальше этого (px).
const TOP_SLACK = 4;

export class MessageList extends Component {
    static template = "mail_client.MessageList";
    static components = { Dropdown, DropdownItem };
    static props = {
        messages: { type: Array },
        selectedMessageId: { optional: true },
        selectedIds: { type: Array },
        moveTargets: { type: Array, optional: true },
        hasMore: { type: Boolean },
        loading: { type: Boolean },
        busy: { type: Boolean, optional: true },
        // False on a read-only mailbox, where the server refuses move and
        // delete rather than dropping mail from Odoo that is still on IMAP.
        canAct: { type: Boolean, optional: true },
        folderName: { type: String, optional: true },
        // Set only while a quick filter is narrowing the list, so the empty
        // state can name it instead of claiming the folder is empty.
        filterLabel: { type: String, optional: true },
        // ПРАВКА ПМК (шаг 18): рассылки одной строкой (крючок сервера
        // _list_digests) и переход в их папку по щелчку.
        digests: { type: Array, optional: true },
        onOpenFolder: { type: Function, optional: true },
        // ПРАВКА ПМК (шаг 22): новые строки над прокрученным списком
        // (плашка «N новых писем»), подсветка открытой переписки, у которой
        // сменилось письмо строки, и прокрутка для корня (обновление
        // списка без сброса, mail_client_action.js — refreshList).
        pendingNew: { type: Number, optional: true },
        selectedThreadKey: { optional: true },
        onShowNew: { type: Function, optional: true },
        onReachTop: { type: Function, optional: true },
        onListApi: { type: Function, optional: true },
        onClearFilter: { type: Function },
        onSelectMessage: { type: Function },
        onLoadMore: { type: Function },
        onToggleSelected: { type: Function },
        onToggleAll: { type: Function },
        onBulkSeen: { type: Function },
        onBulkFlagged: { type: Function },
        onBulkMove: { type: Function },
        onBulkDelete: { type: Function },
    };

    setup() {
        const view = readPref(LIST_VIEW_KEY, "comfortable");
        this.state = useState({ view: LIST_VIEWS.includes(view) ? view : "comfortable" });

        // ПРАВКА ПМК (шаг 22): прокрутка списка — корню. Он спрашивает, в
        // начале ли пользователь (тогда свежий список ставится целиком), и
        // после такой замены просит удержать начало: вставка строк сверху не
        // должна увести прокрутку. keepTop действует на ближайшую
        // перерисовку и не дольше секунды — позже она прыгнула бы сама.
        this.scrollRef = useRef("scroll");
        this.wasAtTop = true;
        this.keepTopUntil = 0;
        onMounted(() =>
            this.props.onListApi?.({
                isAtTop: () => this.isAtTop(),
                keepTop: () => this.keepTop(),
            })
        );
        onPatched(() => {
            if (this.keepTopUntil && Date.now() < this.keepTopUntil) {
                this.toTop();
            }
            this.keepTopUntil = 0;
        });
        onWillUnmount(() => this.props.onListApi?.(null));
    }

    isAtTop() {
        const el = this.scrollRef.el;
        return !el || el.scrollTop <= TOP_SLACK;
    }

    toTop() {
        const el = this.scrollRef.el;
        if (el && el.scrollTop) {
            el.scrollTop = 0;
        }
        this.wasAtTop = true;
    }

    keepTop() {
        this.toTop();
        this.keepTopUntil = Date.now() + 1000;
    }

    onScroll() {
        const atTop = this.isAtTop();
        if (!atTop) {
            this.keepTopUntil = 0; // пользователь прокручивает сам
        } else if (!this.wasAtTop) {
            this.props.onReachTop?.();
        }
        this.wasAtTop = atTop;
    }

    /** Плашка «N новых писем»: наверх, и список встаёт целиком. */
    onShowNew() {
        this.toTop();
        this.props.onShowNew?.();
    }

    get newLabel() {
        const count = this.props.pendingNew || 0;
        const form = pluralForm(count, user.lang);
        if (form === "one") {
            return _t("%s new message", count);
        }
        if (form === "few") {
            return _t("%s new messages (2-4)", count);
        }
        return _t("%s new messages", count);
    }

    formatDate(value) {
        return formatMessageDate(value);
    }

    sender(message) {
        return senderName(message.email_from);
    }

    // ПРАВКА ПМК (шаг 18): у нашего письма в строке — кому, а не от кого.
    recipient(message) {
        return recipientLabel(message.email_to);
    }

    // ПРАВКА ПМК (шаг 22): и строка открытой переписки, которую после
    // обновления списка представляет новое письмо (пришёл ответ).
    isSelected(message) {
        return (
            this.props.selectedMessageId === message.id ||
            Boolean(
                this.props.selectedThreadKey &&
                    message.thread_key === this.props.selectedThreadKey
            )
        );
    }

    isTicked(messageId) {
        return this.props.selectedIds.includes(messageId);
    }

    get allTicked() {
        return (
            this.props.messages.length > 0 &&
            this.props.selectedIds.length === this.props.messages.length
        );
    }

    /** True when some but not all rows are ticked. */
    get someTicked() {
        return this.props.selectedIds.length > 0 && !this.allTicked;
    }

    /**
     * ПРАВКА ПМК (шаг 18): строки, заголовки групп «Сегодня / Вчера /
     * Раньше» и строки рассылок — см. list_items.js. Группы пересчитываются
     * при каждой перерисовке списка: письмо, пришедшее вчера до полуночи,
     * после полуночи переедет во «Вчера» со следующей загрузкой.
     */
    get items() {
        return buildListItems(this.props.messages, this.props.digests || [], {
            hasMore: this.props.hasMore,
            bucketOf: (value) => dayBucket(value),
        });
    }

    get isCompact() {
        return this.state.view === "compact";
    }

    setView(view) {
        this.state.view = view;
        writePref(LIST_VIEW_KEY, view);
    }

    // ПРАВКА ПМК: см. комментарий в mail_client_action.js — литералы из
    // выражений в шаблоне вынесены сюда, иначе они не переводятся.
    get bulkSeenTitle() {
        return this.anyUnread ? _t("Mark as read") : _t("Mark as unread");
    }

    get noMatchLabel() {
        return _t("No message matches %s.", this.props.filterLabel);
    }

    threadTitle(count) {
        return _t("%s messages", count);
    }

    groupLabel(bucket) {
        if (bucket === "today") {
            return _t("Today");
        }
        if (bucket === "yesterday") {
            return _t("Yesterday");
        }
        return _t("Earlier");
    }

    // ПРАВКА ПМК (шаг 18, Г10): плашка строки-переписки.
    awaitLabel(value) {
        return value === "us" ? _t("awaiting reply") : _t("awaiting client");
    }

    awaitTitle(value) {
        return value === "us"
            ? _t("The client wrote last and has no answer from us yet")
            : _t("We wrote last and are waiting for the client");
    }

    digestUnreadLabel(count) {
        return _t("%s new", count);
    }

    get anyUnread() {
        return this.props.messages.some(
            (message) => this.isTicked(message.id) && !message.flag_seen
        );
    }

    onRowClick(ev, messageId) {
        // A click on the checkbox is a selection, not a request to open.
        // ПРАВКА ПМК (шаг 18): и щелчок по месту галочки в начале строки —
        // там же точка непрочитанного, галочка видна при наведении.
        if (ev.target.closest(".o_mail_client_tick, .o_mail_client_lead")) {
            return;
        }
        this.props.onSelectMessage(messageId);
    }

    onOpenDigest(digest) {
        this.props.onOpenFolder?.(digest.folder_id);
    }

    onMoveTo(folderId) {
        this.props.onBulkMove(folderId);
    }
}
