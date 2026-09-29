import { Component, useState } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { _t } from "@web/core/l10n/translation";

import { dayBucket, formatMessageDate, readPref, recipientLabel, senderName, writePref } from "../utils";
import { buildListItems } from "./list_items";

// ПРАВКА ПМК (шаг 18): вид списка — «удобный» (две строки) или «компактный»
// (одна строка, колонка шире). Помнится в браузере; значение по умолчанию —
// удобный. Живёт здесь, а не в корне: это только вид списка.
const LIST_VIEW_KEY = "mail_client.list_view";
const LIST_VIEWS = ["comfortable", "compact"];

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

    isSelected(messageId) {
        return this.props.selectedMessageId === messageId;
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
