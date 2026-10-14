import { Component, markup, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Wysiwyg } from "@html_editor/wysiwyg";
import { MAIN_PLUGINS } from "@html_editor/plugin_sets";

import { RecipientInput } from "./recipient_input";
import { EditorToolbar } from "./editor_toolbar";
import { formatSize } from "../utils";

// Anything larger and the SMTP submission is likely to be refused anyway.
const MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024;
// ПРАВКА ПМК (шаг 6, разбор Г7): пауза в наборе, после которой черновик
// сохраняется сам — только в Odoo; в «Черновики» ящика — при закрытии.
const AUTOSAVE_DELAY = 2500;

export class Composer extends Component {
    static template = "mail_client.Composer";
    static components = { Wysiwyg, RecipientInput, EditorToolbar };
    static props = {
        draft: { type: Object },
        onClose: { type: Function },
        onSent: { type: Function },
        // ПРАВКА ПМК (шаг 6): ответ под письмом — компактный вид в окне
        // чтения; ⤢ — тот же черновик на всю ширину (onExpand получает его
        // свежую копию с сервера).
        inline: { type: Boolean, optional: true },
        onExpand: { type: Function, optional: true },
        // Сохранил набранное сам, закрываясь без кнопки, — обновить список
        // черновиков.
        onFlushed: { type: Function, optional: true },
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

        // ПРАВКА ПМК (шаг 6, Г7): автосохранение. pristine — ничего не
        // тронуто: только что начатый ответ при закрытии не оставляет
        // черновика (адрес, тема и цитата подставлены сами, «пустым» он не
        // выглядит). Черновик, открытый из списка, не трогаем.
        this.pristine = Boolean(this.props.draft.fresh);
        this.closed = false;
        this.autosaveTimer = null;
        onMounted(() => {
            const failed = this.props.draft.pmk_forward_failed;
            if (failed && failed.length) {
                this.notification.add(
                    _t("Not attached, the mail server did not return: %s", failed.join(", ")),
                    { type: "warning", sticky: true }
                );
            }
        });
        // Окно закрыли не кнопкой (открыли другое письмо, ушли из раздела) —
        // набранное не теряем.
        onWillUnmount(() => {
            clearTimeout(this.autosaveTimer);
            if (!this.closed && !this.pristine) {
                this.saveDraft()
                    .then(() => this.props.onFlushed?.())
                    .catch(() => {});
            } else if (!this.closed && this.props.draft.fresh) {
                // Начатый и не тронутый ответ — следа не оставляет.
                this.orm
                    .call("mail.client.compose", "discard", [], { compose_id: this.props.draft.id })
                    .catch(() => {});
            }
        });
    }

    get modeIcon() {
        switch (this.props.draft.compose_mode) {
            case "reply_all":
                return "fa-reply-all";
            case "forward":
                return "fa-share";
            default:
                return "fa-reply";
        }
    }

    /** Что-то изменили — сохранить, когда набор затихнет. */
    touch() {
        this.pristine = false;
        this.state.savedAt = null;
        clearTimeout(this.autosaveTimer);
        this.autosaveTimer = setTimeout(() => this.autosave(), AUTOSAVE_DELAY);
    }

    async autosave() {
        if (this.closed || this.state.sending) {
            return;
        }
        try {
            await this.saveDraft({ fileOnServer: false });
            if (!this.closed) {
                this.state.savedAt = new Date();
            }
        } catch {
            // Нет связи — сохранится при закрытии или по кнопке.
        }
    }

    async onExpand() {
        clearTimeout(this.autosaveTimer);
        const draft = await this.orm.call("mail.client.compose", "save_draft", [], {
            compose_id: this.props.draft.id,
            values: this.values(),
            file_on_server: false,
        });
        this.closed = true;
        this.props.onExpand({ ...draft, fresh: this.pristine });
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
        this.touch();
    }

    updateField(field, value) {
        this.state[field] = value;
        this.touch();
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
            // ПРАВКА ПМК (шаг 6, Г7): шаг истории редактора — правка текста.
            onChange: () => this.touch(),
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
                this.pristine = false;
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
        this.pristine = false;
    }

    // ------------------------------------------------------------------
    async onSend() {
        if (!this.state.email_to.trim()) {
            this.notification.add(_t("Add at least one recipient."), { type: "warning" });
            return;
        }
        this.state.sending = true;
        clearTimeout(this.autosaveTimer);
        try {
            await this.orm.call("mail.client.compose", "send", [], {
                compose_id: this.props.draft.id,
                values: this.values(),
            });
            this.closed = true;
            this.notification.add(_t("Message sent."), { type: "success" });
            this.props.onSent();
        } finally {
            this.state.sending = false;
        }
    }

    async onDiscard() {
        clearTimeout(this.autosaveTimer);
        this.closed = true;
        await this.orm.call("mail.client.compose", "discard", [], {
            compose_id: this.props.draft.id,
        });
        this.props.onClose();
    }

    async saveDraft({ fileOnServer = true } = {}) {
        await this.orm.call("mail.client.compose", "save_draft", [], {
            compose_id: this.props.draft.id,
            values: this.values(),
            file_on_server: fileOnServer,
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
        clearTimeout(this.autosaveTimer);
        this.closed = true;
        if (this.isEmpty || this.pristine) {
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
