import { Component, useState } from "@odoo/owl";
import { formatMessageDate, senderName } from "../utils";

export class MessageList extends Component {
    static template = "mail_client.MessageList";
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
        this.state = useState({ showMoveMenu: false });
    }

    formatDate(value) {
        return formatMessageDate(value);
    }

    sender(message) {
        return senderName(message.email_from);
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

    get anyUnread() {
        return this.props.messages.some(
            (message) => this.isTicked(message.id) && !message.flag_seen
        );
    }

    onRowClick(ev, messageId) {
        // A click on the checkbox is a selection, not a request to open.
        if (ev.target.closest(".o_mail_client_tick")) {
            return;
        }
        this.props.onSelectMessage(messageId);
    }

    onMoveTo(folderId) {
        this.state.showMoveMenu = false;
        this.props.onBulkMove(folderId);
    }
}
