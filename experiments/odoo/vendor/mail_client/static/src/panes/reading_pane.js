import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

import { formatMessageDate, formatSize } from "../utils";
import { AttachmentPreviewDialog } from "../attachments/attachment_preview_dialog";

export class ReadingPane extends Component {
    static template = "mail_client.ReadingPane";
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
    };

    setup() {
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.state = useState({
            showMoveMenu: false,
            downloading: null,
            showContact: false,
        });
    }

    // ПРАВКА ПМК: см. комментарий в mail_client_action.js.
    get seenTitle() {
        return this.props.detail?.flag_seen ? _t("Mark as unread") : _t("Mark as read");
    }

    /** Other messages in this conversation, current one excluded. */
    get otherInThread() {
        if (!this.props.thread || !this.props.detail) {
            return [];
        }
        return this.props.thread.filter((message) => message.id !== this.props.detail.id);
    }

    formatDate(value) {
        return formatMessageDate(value);
    }

    formatSize(bytes) {
        return formatSize(bytes);
    }

    /**
     * The body is rendered inside a sandboxed iframe with neither
     * allow-scripts nor allow-same-origin: untrusted HTML gets an opaque
     * origin and no scripting at all. Popups stay
     * allowed so that target="_blank" links still open.
     */
    get sandbox() {
        return "allow-popups allow-popups-to-escape-sandbox";
    }

    async onDownload(attachment) {
        this.state.downloading = attachment.id;
        try {
            const result = await this.props.onDownloadAttachment(attachment.id);
            if (result && result.url) {
                // Fetched on demand, so the URL only exists after this call.
                window.open(result.url, "_blank");
            }
        } finally {
            this.state.downloading = null;
        }
    }

    /**
     * ПРАВКА ПМК: показать вложение, не скачивая его.
     *
     * Окно заводится прямо отсюда, а не через корень почты: просмотр не часть
     * состояния почты и живёт ровно столько, сколько открыт диалог. Кнопка
     * скачивания рядом осталась нетронутой — файл всё равно иногда нужен на
     * диске, и тогда его берут в один клик, как раньше.
     */
    onPreview(attachment) {
        this.dialog.add(AttachmentPreviewDialog, {
            attachmentId: attachment.id,
            name: attachment.name,
            // Скачивание из окна идёт тем же путём, что и по кнопке в письме:
            // колесо на кнопке и разбор отказа остаются в одном месте.
            onDownload: () => this.onDownload(attachment),
        });
    }

    onMoveTo(folderId) {
        this.state.showMoveMenu = false;
        this.props.onMove(folderId);
    }
}
