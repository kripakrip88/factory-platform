import { Component, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";

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

export class FolderTree extends Component {
    static template = "mail_client.FolderTree";
    static props = {
        accounts: { type: Array },
        activeFolderId: { optional: true },
        unified: { type: Boolean, optional: true },
        drafts: { type: Array, optional: true },
        onSelectFolder: { type: Function },
        onSelectUnified: { type: Function },
        onResumeDraft: { type: Function },
    };

    setup() {
        this.state = useState({ collapsed: this.readCollapsed() });
    }

    readCollapsed() {
        try {
            const stored = JSON.parse(browser.localStorage.getItem(COLLAPSED_KEY) || "[]");
            return Array.isArray(stored) ? stored : [];
        } catch {
            // A corrupt entry must not take the whole sidebar down with it.
            return [];
        }
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
        browser.localStorage.setItem(COLLAPSED_KEY, JSON.stringify(collapsed));
    }

    /**
     * Unread total for a mailbox, shown on the header while it is folded.
     * Without it, collapsing an account would quietly hide the fact that new
     * mail has arrived in it.
     */
    unreadFor(account) {
        return account.folders.reduce((total, folder) => total + (folder.unread || 0), 0);
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
}
