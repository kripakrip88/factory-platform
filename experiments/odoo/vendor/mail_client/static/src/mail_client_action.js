import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { browser } from "@web/core/browser/browser";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { _t } from "@web/core/l10n/translation";

import { FolderTree } from "./panes/folder_tree";
import { MessageList } from "./panes/message_list";
import { ReadingPane } from "./panes/reading_pane";
import { Composer } from "./composer/composer";
import { readPref, writePref } from "./utils";

const PAGE_SIZE = 50;
const SIDEBAR_KEY = "mail_client.sidebar_pinned";
// ПРАВКА ПМК (шаг 18, А2): переписки — режим по умолчанию, как в Mail.ru.
// Ключ новый (было "mail_client.threaded", по умолчанию выключено): прежний
// выбор сбрасывается у всех (решение владельца 30.09.2026), а «выключено»
// дальше запоминается.
const THREADED_KEY = "mail_client.threaded.v2";

/**
 * Quick filters, in menu order. The names must match MESSAGE_FILTERS in
 * mail_client_folder.py, which rejects anything it does not know.
 *
 * Deliberately not remembered across sessions, unlike the sidebar and the
 * threading toggle: those change how mail is shown, this one changes which
 * mail is shown at all. Coming back a week later to a mailbox still pinned to
 * "Unread" looks like lost mail.
 */
export const MESSAGE_FILTERS = [
    { id: "all", label: _t("All"), icon: "fa-inbox" },
    { id: "unread", label: _t("Unread"), icon: "fa-envelope" },
    { id: "read", label: _t("Read"), icon: "fa-envelope-open-o" },
    // ПРАВКА ПМК (шаг 18, Г10): последнее слово за клиентом, ответа нет.
    { id: "awaiting", label: _t("Awaiting reply"), icon: "fa-reply" },
    { id: "flagged", label: _t("Starred"), icon: "fa-star" },
    { id: "attachments", label: _t("Has attachments"), icon: "fa-paperclip" },
    { id: "contact", label: _t("From a contact"), icon: "fa-address-book-o" },
];

/**
 * Root of the three-pane inbox.
 *
 * All state lives here and flows down as props; the panes are presentational.
 * That is what makes a bus notification able to refresh the whole view without
 * any component having to know about any other.
 */
export class MailClientInbox extends Component {
    static template = "mail_client.Inbox";
    static components = { FolderTree, MessageList, ReadingPane, Composer, Dropdown, DropdownItem };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.busService = useService("bus_service");

        this.state = useState({
            accounts: [],
            activeFolderId: null,
            messages: [],
            hasMore: false,
            selectedMessageId: null,
            detail: null,
            search: "",
            loadingList: false,
            loadingDetail: false,
            syncing: false,
            moveTargets: [],
            bulkMoveTargets: [],
            selectedIds: [],
            bulkBusy: false,
            draft: null,
            drafts: [],
            threaded: readPref(THREADED_KEY) !== "false",
            filter: "all",
            unified: false,
            // ПРАВКА ПМК (шаг 18): рассылки одной строкой — с первой страницы
            // списка, при «Загрузить ещё» остаются.
            digests: [],
            thread: [],
            contact: null,
            searchingServer: false,
            // Remembered across sessions: a collapsed sidebar is a layout
            // preference, not something to re-choose on every visit.
            sidebarPinned: browser.localStorage.getItem(SIDEBAR_KEY) !== "false",
        });

        this.busService.subscribe("mail_client.sync", (payload) =>
            this.onSyncNotification(payload)
        );

        onWillStart(async () => {
            await this.loadAccounts();
            const first = this.firstFolderId();
            if (first) {
                await this.selectFolder(first);
            }
        });
    }

    // ------------------------------------------------------------------
    // loading
    // ------------------------------------------------------------------
    async loadAccounts() {
        const result = await this.orm.call("mail.client.account", "get_inbox_state", []);
        this.state.accounts = result.accounts;
    }

    firstFolderId() {
        for (const account of this.state.accounts) {
            const inbox = account.folders.find((f) => f.role === "inbox");
            if (inbox) {
                return inbox.id;
            }
            if (account.folders.length) {
                return account.folders[0].id;
            }
        }
        return null;
    }

    // ПРАВКА ПМК: подписи вынесены из шаблона в геттеры. Извлекатель
    // переводов Odoo берёт только статические title=/placeholder=/alt=, а
    // литералы внутри выражений t-att-* не видит вовсе — из-за этого подсказки
    // кнопок оставались английскими при полностью переведённом модуле.
    get sidebarTitle() {
        return this.state.sidebarPinned ? _t("Hide folders") : _t("Show folders");
    }

    get activeFolder() {
        for (const account of this.state.accounts) {
            const folder = account.folders.find((f) => f.id === this.state.activeFolderId);
            if (folder) {
                return folder;
            }
        }
        return null;
    }

    get activeAccount() {
        return this.state.accounts.find((a) =>
            a.folders.some((f) => f.id === this.state.activeFolderId)
        );
    }

    /**
     * Whether move and delete may be offered for what is on screen.
     *
     * Both are refused server-side on a read-only mailbox, because carrying
     * them out locally would drop mail from Odoo that is still on the server.
     * The unified inbox spans several mailboxes, so it takes the strictest
     * answer among them rather than acting on a mix.
     */
    get canAct() {
        if (this.state.unified) {
            return (
                this.state.accounts.length > 0 &&
                this.state.accounts.every((account) => account.can_act)
            );
        }
        const account = this.activeAccount;
        return Boolean(account && account.can_act);
    }

    toggleSidebar() {
        this.state.sidebarPinned = !this.state.sidebarPinned;
        browser.localStorage.setItem(SIDEBAR_KEY, String(this.state.sidebarPinned));
    }

    async selectFolder(folderId) {
        this.state.activeFolderId = folderId;
        this.state.unified = false;
        this.clearSelection();
        await this.loadMessages({ reset: true });
        await this.loadDrafts();
    }

    async selectUnified() {
        this.state.unified = true;
        this.state.activeFolderId = null;
        this.clearSelection();
        await this.loadMessages({ reset: true });
    }

    clearSelection() {
        this.state.selectedMessageId = null;
        this.state.detail = null;
        this.state.selectedIds = [];
        this.state.thread = [];
        this.state.contact = null;
    }

    get filters() {
        return MESSAGE_FILTERS;
    }

    get activeFilter() {
        return MESSAGE_FILTERS.find((f) => f.id === this.state.filter) || MESSAGE_FILTERS[0];
    }

    /**
     * Empty while unfiltered, so the list can tell "no mail" from "no match".
     *
     * Resolved with String(): the labels are built at module load, when _t()
     * still returns a lazy translation rather than text, and the receiving
     * prop is declared as a String.
     */
    get filterLabel() {
        return this.state.filter === "all" ? "" : String(this.activeFilter.label);
    }

    async setFilter(filterId) {
        if (filterId === this.state.filter) {
            return;
        }
        this.state.filter = filterId;
        // The rows about to arrive are a different set, so anything ticked or
        // open refers to a message that may no longer be listed.
        this.clearSelection();
        await this.loadMessages({ reset: true });
    }

    async toggleThreaded() {
        this.state.threaded = !this.state.threaded;
        writePref(THREADED_KEY, this.state.threaded);
        this.clearSelection();
        await this.loadMessages({ reset: true });
    }

    /**
     * Ask the mail server to search.
     *
     * Odoo can only match what it stores, and this client stores headers by
     * design - so anything older than the sync window, or a word that appears
     * only in a body, is invisible locally but not to the server.
     */
    async searchOnServer() {
        if (!this.state.activeFolderId || !this.state.search) {
            return;
        }
        this.state.searchingServer = true;
        try {
            const result = await this.orm.call("mail.client.folder", "search_server", [], {
                folder_id: this.state.activeFolderId,
                term: this.state.search,
            });
            this.notification.add(
                result.fetched
                    ? _t("%s more message(s) found on the server.", result.fetched)
                    : _t("Nothing further found on the server."),
                { type: result.fetched ? "success" : "info" }
            );
            await this.loadMessages({ reset: true });
        } finally {
            this.state.searchingServer = false;
        }
    }

    async loadDrafts() {
        const account = this.activeAccount;
        this.state.drafts = account
            ? await this.orm.call("mail.client.compose", "list_drafts", [], {
                  account_id: account.id,
              })
            : [];
    }

    // ------------------------------------------------------------------
    // multi-selection
    // ------------------------------------------------------------------
    toggleSelected(messageId) {
        const selected = this.state.selectedIds;
        const index = selected.indexOf(messageId);
        if (index === -1) {
            selected.push(messageId);
        } else {
            selected.splice(index, 1);
        }
        this.refreshBulkTargets();
    }

    toggleAll() {
        this.state.selectedIds =
            this.state.selectedIds.length === this.state.messages.length
                ? []
                : this.state.messages.map((message) => message.id);
        this.refreshBulkTargets();
    }

    async refreshBulkTargets() {
        if (!this.state.selectedIds.length) {
            this.state.bulkMoveTargets = [];
            return;
        }
        this.state.bulkMoveTargets = await this.orm.call(
            "mail.client.message",
            "get_bulk_move_targets",
            [],
            { message_ids: this.state.selectedIds }
        );
    }

    async runBulk(method, params, { removesRows = false } = {}) {
        const ids = this.state.selectedIds.slice();
        if (!ids.length) {
            return;
        }
        this.state.bulkBusy = true;
        try {
            await this.orm.call("mail.client.message", method, [], {
                message_ids: ids,
                ...params,
            });
            if (removesRows) {
                this.state.messages = this.state.messages.filter((m) => !ids.includes(m.id));
                if (ids.includes(this.state.selectedMessageId)) {
                    this.state.selectedMessageId = null;
                    this.state.detail = null;
                }
            }
            this.state.selectedIds = [];
            this.state.bulkMoveTargets = [];
            await this.loadAccounts();
        } finally {
            this.state.bulkBusy = false;
        }
    }

    async bulkSeen(value) {
        const ids = this.state.selectedIds;
        for (const message of this.state.messages) {
            if (ids.includes(message.id)) {
                message.flag_seen = value;
            }
        }
        await this.runBulk("set_seen_bulk", { value });
    }

    async bulkFlagged(value) {
        const ids = this.state.selectedIds;
        for (const message of this.state.messages) {
            if (ids.includes(message.id)) {
                message.flag_flagged = value;
            }
        }
        await this.runBulk("set_flagged_bulk", { value });
    }

    async bulkMove(folderId) {
        await this.runBulk("move_bulk", { folder_id: folderId }, { removesRows: true });
    }

    async bulkDelete() {
        await this.runBulk("delete_bulk", {}, { removesRows: true });
    }

    async loadMessages({ reset = false } = {}) {
        if (!this.state.activeFolderId && !this.state.unified) {
            return;
        }
        this.state.loadingList = true;
        try {
            // Keyset paging: ask for what is older than the last row we hold,
            // rather than an OFFSET that Postgres has to walk past.
            const before =
                !reset && this.state.messages.length
                    ? this.state.messages[this.state.messages.length - 1].date
                    : null;
            const result = await this.orm.call("mail.client.folder", "get_messages", [], {
                folder_id: this.state.activeFolderId,
                limit: PAGE_SIZE,
                before,
                search: this.state.search || null,
                threaded: this.state.threaded,
                unified: this.state.unified,
                message_filter: this.state.filter,
            });
            this.state.messages = reset
                ? result.messages
                : this.state.messages.concat(result.messages);
            if (reset) {
                this.state.digests = result.digests || [];
            }
            this.state.hasMore = result.has_more;
        } finally {
            this.state.loadingList = false;
        }
    }

    async loadMore() {
        await this.loadMessages({ reset: false });
    }

    async onSearch(value) {
        this.state.search = value;
        await this.loadMessages({ reset: true });
    }

    // ------------------------------------------------------------------
    // reading
    // ------------------------------------------------------------------
    /**
     * ПРАВКА ПМК: письмо открывается без мигания и без гонки («Почта как в
     * Mail.ru», шаг 2, А11; шаг 17 плана, 29.09.2026).
     *
     * Четыре запроса идут разом, а не по очереди: было четыре круга до
     * сервера подряд, стало время самого долгого. Ответ пишется в state
     * одним куском, когда пришли все четыре, — до этого на экране остаётся
     * прежнее письмо (окно чтения показывает его бледным, пока loadingDetail).
     *
     * Гонка автора: при быстрых щелчках ответ прошлого открытия приходил
     * позже и записывался поверх — на экране письмо X при выделенной строке
     * S2, а setSeen(true) после него помечал S2 (setSeen берёт выделенную
     * строку) и сбивал счётчик папки. Теперь у каждого открытия свой знак:
     * после await ответ пишется, только если это всё ещё последнее открытие
     * и строка всё ещё выделена (выделение сбрасывают смена папки, фильтра,
     * перенос, удаление). Опоздавший ответ молча выбрасывается, его ошибка —
     * тоже: письмо, которого уже нет на экране, не должно открывать окно
     * ошибки.
     *
     * pmk_mail_ui/static/src/js/thread_seen.js держится на том, что
     * setSeen(true) зовётся синхронно после записи ответа — так и осталось.
     *
     * Возвращает, чем кончилось открытие (крючок для thread_seen.js):
     * "shown" — письмо на экране; "superseded" — ответ пришёл, но уже
     * открыли другое, ответ выброшен; "failed" — не открылось, а на экране
     * уже другое письмо, ошибка выброшена молча. Отказ ТЕКУЩЕГО открытия —
     * исключение, как у автора.
     */
    async selectMessage(messageId) {
        const token = {};
        this.openToken = token;
        const isCurrent = () =>
            this.openToken === token && this.state.selectedMessageId === messageId;
        this.state.selectedMessageId = messageId;
        this.state.loadingDetail = true;
        try {
            // The body is fetched from IMAP on this call when it is not stored
            // yet, so the round trip can be slower than a normal read.
            const [detail, moveTargets, contact, thread] = await Promise.all([
                this.orm.call("mail.client.message", "get_message_detail", [messageId]),
                this.orm.call("mail.client.message", "get_move_targets", [messageId]),
                this.orm.call("mail.client.message", "get_contact_context", [messageId]),
                this.state.threaded
                    ? this.orm.call("mail.client.message", "get_thread", [messageId])
                    : [],
            ]);
            if (!isCurrent()) {
                return "superseded";
            }
            Object.assign(this.state, { detail, moveTargets, contact, thread });
            // Opening a message marks it read, the way every mail client does.
            if (!this.state.detail.flag_seen) {
                this.setSeen(true);
            }
            return "shown";
        } catch (error) {
            if (!isCurrent()) {
                return "failed";
            }
            this.state.detail = null;
            throw error;
        } finally {
            if (this.openToken === token) {
                this.state.loadingDetail = false;
            }
        }
    }

    /**
     * ПРАВКА ПМК (разбор шага 20, 30.09.2026): письмо ленты переписки
     * показано — развёрнуто, и его тело пришло с сервера
     * (panes/conversation.js, props.onShown). Крючок для pmk_mail_ui:
     * thread_seen.js гасит переписку до этого письма. Модуль почты сам
     * ничего не помечает: разворот письма — только просмотр.
     */
    conversationShown() {
        // Отметки «прочитано» у модуля почты — только открытие строки.
    }

    // ------------------------------------------------------------------
    // message actions - optimistic, then queued to the server
    // ------------------------------------------------------------------
    updateRow(messageId, values) {
        const row = this.state.messages.find((m) => m.id === messageId);
        if (row) {
            Object.assign(row, values);
        }
        // ПРАВКА ПМК (шаг 18): то же письмо в окне переписки и в истории
        // контакта — его могли открыть оттуда, и значок там должен совпадать.
        for (const item of this.state.thread || []) {
            if (item.id === messageId) {
                Object.assign(item, values);
            }
        }
        for (const item of this.state.contact?.history || []) {
            if (item.id === messageId) {
                Object.assign(item, values);
            }
        }
        if (this.state.detail && this.state.detail.id === messageId) {
            Object.assign(this.state.detail, values);
        }
    }

    adjustUnread(folderId, delta) {
        for (const account of this.state.accounts) {
            const folder = account.folders.find((f) => f.id === folderId);
            if (folder) {
                folder.unread = Math.max(0, (folder.unread || 0) + delta);
            }
        }
    }

    /**
     * ПРАВКА ПМК (шаг 18): счётчик — у папки письма, а не у открытой папки.
     * Письмо из «Отправленных», открытое из окна переписки во «Входящих»,
     * прибавляло «Входящим», а в «Все входящие» (activeFolderId пуст)
     * счётчики не менялись вовсе. Папку знает detail (get_message_detail
     * отдаёт folder_id); selectMessage зовёт setSeen(true) сразу после записи
     * detail, так что detail — это выделенное письмо.
     */
    async setSeen(value) {
        const messageId = this.state.selectedMessageId;
        if (!messageId) {
            return;
        }
        const detail = this.state.detail;
        const folderId =
            detail && detail.id === messageId && detail.folder_id
                ? detail.folder_id
                : this.state.activeFolderId;
        this.updateRow(messageId, { flag_seen: value });
        this.adjustUnread(folderId, value ? -1 : 1);
        await this.orm.call("mail.client.message", "set_seen", [], {
            message_id: messageId,
            value,
        });
    }

    async toggleSeen() {
        await this.setSeen(!this.state.detail.flag_seen);
    }

    async toggleFlagged() {
        const messageId = this.state.selectedMessageId;
        const value = !this.state.detail.flag_flagged;
        this.updateRow(messageId, { flag_flagged: value });
        await this.orm.call("mail.client.message", "set_flagged", [], {
            message_id: messageId,
            value,
        });
    }

    dropSelected() {
        const messageId = this.state.selectedMessageId;
        this.state.messages = this.state.messages.filter((m) => m.id !== messageId);
        this.state.selectedMessageId = null;
        this.state.detail = null;
    }

    async moveMessage(folderId) {
        const messageId = this.state.selectedMessageId;
        this.dropSelected();
        await this.orm.call("mail.client.message", "move_to_folder", [], {
            message_id: messageId,
            folder_id: folderId,
        });
        await this.loadAccounts();
    }

    async deleteMessage() {
        const messageId = this.state.selectedMessageId;
        this.dropSelected();
        await this.orm.call("mail.client.message", "delete_message", [], {
            message_id: messageId,
        });
        await this.loadAccounts();
    }

    downloadEml() {
        if (this.state.selectedMessageId) {
            browser.location.href = `/mail_client/message/${this.state.selectedMessageId}/eml`;
        }
    }

    async downloadAttachment(attachmentId) {
        return this.orm.call("mail.client.attachment", "download", [], {
            attachment_id: attachmentId,
        });
    }

    // ------------------------------------------------------------------
    // composing
    // ------------------------------------------------------------------
    /**
     * ПРАВКА ПМК (шаг 20): ответить или переслать можно конкретное письмо
     * переписки (кнопки у развёрнутого письма в ленте), а не только
     * открытое: messageId. Без него — открытое, как было (закреплённая
     * строка над письмом). Prop onReply окна чтения — этот метод.
     */
    async compose(mode = "new", messageId = null) {
        const account = this.activeAccount;
        if (!account) {
            return;
        }
        this.state.draft = await this.orm.call("mail.client.compose", "start", [], {
            account_id: account.id,
            mode,
            message_id: mode === "new" ? null : messageId ?? this.state.selectedMessageId,
        });
    }

    async resumeDraft(composeId) {
        this.state.draft = await this.orm.call("mail.client.compose", "open_draft", [], {
            compose_id: composeId,
        });
    }

    async closeComposer() {
        this.state.draft = null;
        await this.loadDrafts();
    }

    async onSent() {
        this.state.draft = null;
        await this.loadDrafts();
        // The sent copy is APPENDed to the server's Sent folder, so Odoo only
        // learns about it by syncing. Reloading the list alone would leave the
        // message you just sent invisible until the next cron run.
        await this.syncNow();
    }

    async allowImages() {
        const messageId = this.state.selectedMessageId;
        if (!messageId) {
            return;
        }
        const detail = await this.orm.call("mail.client.message", "allow_images", [messageId]);
        // ПРАВКА ПМК: та же гонка, что в selectMessage, — пока сервер отвечал,
        // могли открыть другое письмо; ответ по прежнему на него не пишем.
        if (this.state.selectedMessageId === messageId && this.state.detail?.id === messageId) {
            this.state.detail = detail;
        }
    }

    // ------------------------------------------------------------------
    // sync
    // ------------------------------------------------------------------
    async syncNow() {
        const account = this.activeAccount;
        if (!account || this.state.syncing) {
            return;
        }
        this.state.syncing = true;
        try {
            const result = await this.orm.call("mail.client.account", "sync_account", [], {
                account_id: account.id,
            });
            if (result.state === "error") {
                this.notification.add(result.error_message || _t("Synchronisation failed."), {
                    type: "danger",
                    title: _t("Mail sync"),
                });
            }
            await this.refresh();
        } finally {
            this.state.syncing = false;
        }
    }

    async refresh() {
        await this.loadAccounts();
        if (this.state.activeFolderId) {
            await this.loadMessages({ reset: true });
        }
    }

    onSyncNotification(payload) {
        const account = this.state.accounts.find((a) => a.id === payload.account_id);
        if (!account) {
            return;
        }
        account.state = payload.state;
        account.last_sync_date = payload.last_sync_date;
        // Only reload the list when the user is looking at this mailbox;
        // a background sync of another account should not move anything.
        if (this.activeAccount && this.activeAccount.id === payload.account_id) {
            this.loadMessages({ reset: true });
            this.loadAccounts();
        }
    }
}

registry.category("actions").add("mail_client.inbox", MailClientInbox);
