import { Component, markup, useRef, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Wysiwyg } from "@html_editor/wysiwyg";
import { MAIN_PLUGINS } from "@html_editor/plugin_sets";

import { RecipientInput } from "./recipient_input";
import { EditorToolbar } from "./editor_toolbar";
import { formatSize } from "../utils";

// Anything larger and the SMTP submission is likely to be refused anyway.
const MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024;

export class Composer extends Component {
    static template = "mail_client.Composer";
    static components = { Wysiwyg, RecipientInput, EditorToolbar };
    static props = {
        draft: { type: Object },
        onClose: { type: Function },
        onSent: { type: Function },
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.fileInput = useRef("fileInput");

        this.state = useState({
            email_to: this.props.draft.email_to,
            email_cc: this.props.draft.email_cc,
            email_bcc: this.props.draft.email_bcc,
            subject: this.props.draft.subject,
            attachments: this.props.draft.attachments || [],
            showCc: Boolean(this.props.draft.email_cc || this.props.draft.email_bcc),
            sending: false,
            uploading: false,
            saving: false,
            savedAt: null,
            showCode: false,
        });
        this.body = this.props.draft.body_html || "";
    }

    /**
     * Switch between the rich editor and raw HTML.
     *
     * Same approach as Odoo's own html_field: the editor stays mounted and
     * merely hidden, so its history and plugins survive the round trip. On the
     * way back the edited source is written straight into the editable and
     * recorded as a history step, otherwise the change would be invisible to
     * undo and could be clobbered by the next edit.
     */
    toggleCodeView() {
        if (!this.state.showCode) {
            this.body = this.currentBody();
            this.state.showCode = true;
            return;
        }
        this.state.showCode = false;
        if (this.editor) {
            this.editor.editable.innerHTML = this.body;
            this.editor.shared.history.addStep();
        }
    }

    onCodeChange(ev) {
        this.body = ev.target.value;
        this.state.savedAt = null;
    }

    updateField(field, value) {
        this.state[field] = value;
        this.state.savedAt = null;
    }

    get title() {
        switch (this.props.draft.compose_mode) {
            case "reply":
                return _t("Reply");
            case "reply_all":
                return _t("Reply to all");
            case "forward":
                return _t("Forward");
            default:
                return _t("New message");
        }
    }

    formatSize(bytes) {
        return formatSize(bytes);
    }

    get editorConfig() {
        return {
            // setElementContent() falls back to textContent for anything not
            // flagged as markup, which renders a reply as visible HTML source.
            // Our body arrives over a plain RPC, so it never carries the flag
            // an ORM read would have given it. It is sanitised server-side in
            // mail.client.compose._to_payload().
            content: markup(this.body),
            Plugins: MAIN_PLUGINS,
        };
    }

    onEditorLoad(editor) {
        this.editor = editor;
    }

    getEditor() {
        return this.editor;
    }

    currentBody() {
        // While the source view is open it, not the editor, holds the truth.
        if (this.state.showCode) {
            return this.body;
        }
        return this.editor ? this.editor.getContent() : this.body;
    }

    values() {
        return {
            email_to: this.state.email_to,
            email_cc: this.state.email_cc,
            email_bcc: this.state.email_bcc,
            subject: this.state.subject,
            body_html: this.currentBody(),
        };
    }

    // ------------------------------------------------------------------
    async onAttachClick() {
        this.fileInput.el.click();
    }

    async onFilesSelected(ev) {
        const files = Array.from(ev.target.files || []);
        ev.target.value = "";
        if (!files.length) {
            return;
        }
        this.state.uploading = true;
        try {
            for (const file of files) {
                if (file.size > MAX_ATTACHMENT_BYTES) {
                    this.notification.add(
                        _t("%(name)s is larger than %(limit)s and was skipped.", {
                            name: file.name,
                            limit: formatSize(MAX_ATTACHMENT_BYTES),
                        }),
                        { type: "warning" }
                    );
                    continue;
                }
                const datas = await this.readAsBase64(file);
                const draft = await this.orm.call("mail.client.compose", "attach", [], {
                    compose_id: this.props.draft.id,
                    name: file.name,
                    datas,
                    mimetype: file.type || "application/octet-stream",
                });
                this.state.attachments = draft.attachments;
            }
        } finally {
            this.state.uploading = false;
        }
    }

    readAsBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            // result is "data:<mime>;base64,<payload>" - the server wants the payload.
            reader.onload = () => resolve(reader.result.split(",")[1]);
            reader.onerror = () => reject(reader.error);
            reader.readAsDataURL(file);
        });
    }

    async onRemoveAttachment(attachmentId) {
        const draft = await this.orm.call("mail.client.compose", "detach", [], {
            compose_id: this.props.draft.id,
            attachment_id: attachmentId,
        });
        this.state.attachments = draft.attachments;
    }

    // ------------------------------------------------------------------
    async onSend() {
        if (!this.state.email_to.trim()) {
            this.notification.add(_t("Add at least one recipient."), { type: "warning" });
            return;
        }
        this.state.sending = true;
        try {
            await this.orm.call("mail.client.compose", "send", [], {
                compose_id: this.props.draft.id,
                values: this.values(),
            });
            this.notification.add(_t("Message sent."), { type: "success" });
            this.props.onSent();
        } finally {
            this.state.sending = false;
        }
    }

    async onDiscard() {
        await this.orm.call("mail.client.compose", "discard", [], {
            compose_id: this.props.draft.id,
        });
        this.props.onClose();
    }

    async saveDraft() {
        await this.orm.call("mail.client.compose", "save_draft", [], {
            compose_id: this.props.draft.id,
            values: this.values(),
        });
    }

    /** Keep the composer open so writing can continue after saving. */
    async onSaveDraft() {
        this.state.saving = true;
        try {
            await this.saveDraft();
            this.state.savedAt = new Date();
            this.notification.add(_t("Draft saved."), { type: "success" });
        } finally {
            this.state.saving = false;
        }
    }

    /** True when nothing worth keeping has been typed. */
    get isEmpty() {
        const values = this.values();
        const body = (values.body_html || "").replace(/<[^>]*>/g, "").trim();
        return (
            !values.email_to.trim() &&
            !values.email_cc.trim() &&
            !values.email_bcc.trim() &&
            !values.subject.trim() &&
            !body &&
            !this.state.attachments.length
        );
    }

    async onSaveAndClose() {
        if (this.isEmpty) {
            // Opening the composer and closing it again should leave no trace;
            // otherwise the drafts list fills up with "(no subject)" entries.
            await this.orm.call("mail.client.compose", "discard", [], {
                compose_id: this.props.draft.id,
            });
        } else {
            await this.saveDraft();
        }
        this.props.onClose();
    }
}
