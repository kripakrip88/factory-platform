import { Component } from "@odoo/owl";
import { AutoComplete } from "@web/core/autocomplete/autocomplete";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

/**
 * A recipient field that suggests contacts but never gets in the way.
 *
 * Typing a raw address must always work: plenty of recipients are not in the
 * address book, and a picker that only accepts known contacts would make the
 * composer unusable for exactly the messages people need to send in a hurry.
 * So this stays a plain text field, and the dropdown only completes the
 * address currently being typed.
 */
export class RecipientInput extends Component {
    static template = "mail_client.RecipientInput";
    static components = { AutoComplete };
    static props = {
        label: { type: String },
        value: { type: String },
        placeholder: { type: String, optional: true },
        onUpdate: { type: Function },
    };

    setup() {
        this.orm = useService("orm");
        this.sources = [{ options: this.loadSuggestions.bind(this) }];
    }

    /** Everything before the address being typed, kept verbatim. */
    splitTyped(value) {
        const index = value.lastIndexOf(",");
        return index === -1
            ? { prefix: "", current: value.trim() }
            : { prefix: value.slice(0, index + 1), current: value.slice(index + 1).trim() };
    }

    async loadSuggestions(request) {
        const { current } = this.splitTyped(request || "");
        if (current.length < 2) {
            return [];
        }
        const partners = await this.orm.call("mail.client.compose", "search_recipients", [], {
            term: current,
        });
        return partners.map((partner) => ({
            label: partner.company
                ? `${partner.name} (${partner.company}) — ${partner.email}`
                : `${partner.name || partner.email} — ${partner.email}`,
            onSelect: () => this.onPick(partner),
        }));
    }

    onPick(partner) {
        const { prefix } = this.splitTyped(this.props.value || "");
        const separator = prefix && !prefix.endsWith(" ") ? " " : "";
        this.props.onUpdate(`${prefix}${separator}${partner.value}, `);
    }

    onChange({ inputValue }) {
        this.props.onUpdate(inputValue);
    }

    onInput({ inputValue }) {
        this.props.onUpdate(inputValue);
    }
}
