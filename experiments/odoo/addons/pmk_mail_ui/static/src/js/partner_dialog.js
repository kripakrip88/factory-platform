/**
 * Окно «Новый контрагент из письма» (14.10.2026, прототип одобрен Антоном).
 *
 * Только найденное и откуда взято («справочник», «подпись», «вложение»…),
 * вместо полной карточки контрагента с пустыми полями. Нет ИНН в письме —
 * похожие организации из справочника по названию, выбор щелчком; поиск
 * можно повторить своим названием. «Создать контрагента» сохраняет сразу,
 * «Открыть полную карточку» — обычная форма с теми же данными.
 *
 * Данные — pmk_partner_from_letter / pmk_partner_suggest /
 * pmk_partner_create_from_letter / pmk_partner_full_card
 * (models/mail_partner_card.py).
 */
import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

export class PmkNewPartnerDialog extends Component {
    static template = "pmk_mail_ui.NewPartnerDialog";
    static components = { Dialog };
    static props = {
        messageId: Number,
        data: Object,
        onDone: { type: Function, optional: true },
        close: Function,
    };

    setup() {
        this.orm = this.env.services.orm;
        this.action = this.env.services.action;
        this.notification = this.env.services.notification;
        const data = this.props.data;
        this.state = useState({
            company: { ...data.company },
            sources: { ...data.company_sources },
            contact: { ...data.contact },
            contactSources: { ...data.contact_sources },
            candidates: data.candidates || [],
            chosen: -1,
            query: data.query || data.company.name || "",
            searching: false,
            busy: false,
            error: "",
        });
        if (!data.company.vat && this.state.candidates.length === 1) {
            this.choose(0);
        }
    }

    get data() {
        return this.props.data;
    }

    get needsChoice() {
        return !this.data.company.vat;
    }

    get addressLine() {
        const company = this.state.company;
        return company.pmk_legal_address || [company.city, company.street].filter(Boolean).join(", ");
    }

    get innLine() {
        const company = this.state.company;
        return [company.vat, company.kpp].filter(Boolean).join(" / ");
    }

    choose(index) {
        const item = this.state.candidates[index];
        this.state.chosen = index;
        this.state.error = "";
        const company = { ...item };
        delete company.source;
        this.state.company = company;
        const sources = {};
        for (const key of Object.keys(company)) {
            sources[key] = _t("справочник");
        }
        this.state.sources = sources;
    }

    async search() {
        const query = (this.state.query || "").trim();
        if (query.length < 3) {
            this.state.error = _t("Введите хотя бы три буквы названия");
            return;
        }
        this.state.searching = true;
        this.state.error = "";
        try {
            this.state.candidates = await this.orm.call(
                "mail.client.message", "pmk_partner_suggest", [query]);
            this.state.chosen = -1;
            if (!this.state.candidates.length) {
                this.state.error = _t("В справочнике ничего не нашлось — проверьте название");
            }
        } finally {
            this.state.searching = false;
        }
    }

    onQueryKey(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.search();
        }
    }

    setCompany(key, value) {
        this.state.company[key] = value;
        this.state.sources[key] = "";
    }

    setContact(key, value) {
        this.state.contact[key] = value;
        this.state.contactSources[key] = "";
    }

    payload() {
        return [this.props.messageId, this.state.company, this.state.contact, this.data.bank || {}];
    }

    validate() {
        if (!(this.state.company.name || "").trim()) {
            this.state.error = _t("Укажите название организации или выберите её из справочника");
            return false;
        }
        return true;
    }

    async create() {
        if (this.state.busy || !this.validate()) {
            return;
        }
        this.state.busy = true;
        try {
            const result = await this.orm.call(
                "mail.client.message", "pmk_partner_create_from_letter", this.payload());
            this.notification.add(
                result.created
                    ? _t("Контрагент создан: %s", result.name)
                    : _t("Такой ИНН уже есть: %s — новый не создавали", result.name),
                { type: result.created ? "success" : "info" }
            );
            this.props.close();
            this.props.onDone?.(result.id);
        } finally {
            this.state.busy = false;
        }
    }

    async openFull() {
        if (this.state.busy || !this.validate()) {
            return;
        }
        this.state.busy = true;
        try {
            const action = await this.orm.call(
                "mail.client.message", "pmk_partner_full_card", this.payload());
            this.props.close();
            await this.action.doAction(action, { onClose: () => this.props.onDone?.() });
        } finally {
            this.state.busy = false;
        }
    }
}
