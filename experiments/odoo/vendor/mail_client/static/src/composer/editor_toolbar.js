import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";

/**
 * A docked formatting bar for the message body.
 *
 * Odoo 19's editor shows its own toolbar only while text is selected - see
 * ToolbarPlugin.isToolbarVisible(), which returns false for a collapsed
 * selection. That suits documents, but a mail composer is expected to show
 * its formatting controls up front, before anything is typed.
 *
 * Rather than fight the floating toolbar, this renders a small fixed bar that
 * drives the same user commands the editor already registers, through the
 * public userCommand shared API. The floating toolbar still appears on
 * selection; the two do not conflict.
 */
const BUTTONS = [
    { command: "formatBold", icon: "fa-bold", title: _t("Bold") },
    { command: "formatItalic", icon: "fa-italic", title: _t("Italic") },
    { command: "formatUnderline", icon: "fa-underline", title: _t("Underline") },
    { command: "formatStrikethrough", icon: "fa-strikethrough", title: _t("Strikethrough") },
    { separator: true },
    { command: "toggleListUL", icon: "fa-list-ul", title: _t("Bulleted list") },
    { command: "toggleListOL", icon: "fa-list-ol", title: _t("Numbered list") },
    { command: "toggleListCL", icon: "fa-check-square-o", title: _t("Checklist") },
    { separator: true },
    { command: "openLinkTools", icon: "fa-link", title: _t("Insert link") },
    { command: "removeFormat", icon: "fa-eraser", title: _t("Clear formatting") },
];

export class EditorToolbar extends Component {
    static template = "mail_client.EditorToolbar";
    static props = {
        getEditor: { type: Function },
    };

    get buttons() {
        return BUTTONS;
    }

    /**
     * Commands act on the current selection, so the editable has to regain
     * focus first: clicking a toolbar button moves focus to the button and
     * would otherwise apply the command to nothing.
     */
    run(commandId) {
        const editor = this.props.getEditor();
        if (!editor) {
            return;
        }
        editor.shared.selection.focusEditable();
        try {
            editor.shared.userCommand.getCommand(commandId).run();
        } catch {
            // An unknown command means the plugin set in use does not provide
            // it; silently skipping beats breaking the whole composer.
        }
    }
}
