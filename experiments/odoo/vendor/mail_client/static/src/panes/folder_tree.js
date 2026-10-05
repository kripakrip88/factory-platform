import { Component, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";

import { layoutFolders, railCount, railFolders } from "./folder_layout";

const ROLE_ICONS = {
    inbox: "fa-inbox",
    sent: "fa-paper-plane-o",
    drafts: "fa-file-text-o",
    trash: "fa-trash-o",
    spam: "fa-ban",
    archive: "fa-archive",
    other: "fa-folder-o",
};

const COLLAPSED_KEY = "mail_client.collapsed_accounts";

/**
 * ПРАВКА ПМК (шаг 41 разбора удобства, А8, 05.10.2026): какие ящики
 * показывают «Ещё папки» раскрытыми — у человека в этом браузере.
 */
function moreFoldersKey() {
    return `mail_client.more_folders.u${user.userId || 0}`;
}

function readIds(key) {
    try {
        const stored = JSON.parse(browser.localStorage.getItem(key) || "[]");
        return Array.isArray(stored) ? stored : [];
    } catch {
        // A corrupt entry must not take the whole sidebar down with it.
        return [];
    }
}

function writeIds(key, ids) {
    try {
        browser.localStorage.setItem(key, JSON.stringify(ids));
    } catch {
        // Не запомнили — в следующий раз как по умолчанию.
    }
}

/**
 * Колонка папок.
 *
 * ПРАВКА ПМК (шаг 41, А8): дерево как в Mail.ru — подпапки с отступом под
 * родителем, пустые прочие папки под раскрывающимся «Ещё папки»
 * (folder_layout.js), и узкая полоса значков (rail): служебные папки
 * ящиков, число непрочитанных — только у не тихих. На телефоне колонка —
 * шторка поверх списка (drawer; закрывает её корень почты при выборе папки).
 */
export class FolderTree extends Component {
    static template = "mail_client.FolderTree";
    static props = {
        accounts: { type: Array },
        activeFolderId: { optional: true },
        unified: { type: Boolean, optional: true },
        drafts: { type: Array, optional: true },
        // ПРАВКА ПМК (шаг 41): полоса значков и шторка на телефоне.
        rail: { type: Boolean, optional: true },
        drawer: { type: Boolean, optional: true },
        onSelectFolder: { type: Function },
        onSelectUnified: { type: Function },
        onResumeDraft: { type: Function },
    };

    setup() {
        this.state = useState({
            collapsed: readIds(COLLAPSED_KEY),
            moreOpen: readIds(moreFoldersKey()),
        });
    }

    isCollapsed(accountId) {
        return this.state.collapsed.includes(accountId);
    }

    toggleAccount(accountId) {
        const collapsed = this.state.collapsed;
        const index = collapsed.indexOf(accountId);
        if (index === -1) {
            collapsed.push(accountId);
        } else {
            collapsed.splice(index, 1);
        }
        writeIds(COLLAPSED_KEY, collapsed);
    }

    /**
     * Unread total for a mailbox, shown on the header while it is folded.
     * Without it, collapsing an account would quietly hide the fact that new
     * mail has arrived in it.
     *
     * ПРАВКА ПМК (шаг 18): без тихих папок (folder.quiet — Спам, Корзина,
     * у pmk_mail_ui ещё рассылки mail.ru). Иначе у свёрнутого pmkpark@ в
     * итоге стояло «3391», из них 3374 — спам, и настоящих новых писем за
     * этим числом не видно.
     */
    unreadFor(account) {
        return account.folders.reduce(
            (total, folder) => total + (folder.quiet ? 0 : folder.unread || 0),
            0
        );
    }

    /** True when the folder currently being read belongs to this account. */
    holdsActiveFolder(account) {
        return account.folders.some((folder) => folder.id === this.props.activeFolderId);
    }

    iconFor(role) {
        return ROLE_ICONS[role] || ROLE_ICONS.other;
    }

    /** Unread across every inbox, shown on the unified entry. */
    get totalInboxUnread() {
        return this.props.accounts.reduce(
            (total, account) =>
                total +
                account.folders
                    .filter((folder) => folder.role === "inbox")
                    .reduce((sum, folder) => sum + (folder.unread || 0), 0),
            0
        );
    }

    isActive(folderId) {
        return this.props.activeFolderId === folderId;
    }

    // ------------------------------------------------------------------
    // ПРАВКА ПМК (шаг 41, А8)
    // ------------------------------------------------------------------
    /** Раскладка папок ящика: основные с отступом и «Ещё папки». */
    layoutFor(account) {
        return layoutFolders(account.folders);
    }

    /** «Ещё папки» раскрыты: выбрал человек или в них открытая папка. */
    moreOpen(account, layout) {
        return (
            this.state.moreOpen.includes(account.id) ||
            layout.more.some((entry) => entry.folder.id === this.props.activeFolderId)
        );
    }

    toggleMore(accountId) {
        const open = this.state.moreOpen;
        const index = open.indexOf(accountId);
        if (index === -1) {
            open.push(accountId);
        } else {
            open.splice(index, 1);
        }
        writeIds(moreFoldersKey(), open);
    }

    moreLabel(count) {
        return _t("More folders (%s)", count);
    }

    moreTitle() {
        return _t("Folders with no messages in the sync window");
    }

    /** Отступ подпапки — CSS-переменной (mail_client.scss). */
    depthStyle(depth) {
        return depth ? `--mc-depth: ${depth}` : "";
    }

    folderTitle(entry) {
        return entry.parentName ? `${entry.parentName} / ${entry.folder.name}` : entry.folder.name;
    }

    /**
     * Полоса значков: служебные папки ящика и открытая, если она не
     * служебная (иначе на полосе не видно, где ты).
     */
    railFor(account) {
        const folders = railFolders(account.folders);
        const active = account.folders.find((folder) => folder.id === this.props.activeFolderId);
        if (active && !folders.includes(active)) {
            folders.push(active);
        }
        return folders;
    }

    railCount(count) {
        return railCount(count);
    }

    railTitle(folder, account) {
        const unread = folder.unread && !folder.quiet ? folder.unread : 0;
        const title = this.props.accounts.length > 1 ? `${folder.name} — ${account.email}` : folder.name;
        return unread ? _t("%(title)s: %(count)s unread", { title, count: unread }) : title;
    }

    get unifiedTitle() {
        return _t("All Inboxes");
    }

    get foldersLabel() {
        return _t("Mail folders");
    }
}
