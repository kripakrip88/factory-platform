/** @odoo-module **/
/**
 * Каталог материалов (26.10.2026): найти позицию справочника глазами, когда запись не попала
 * в номенклатуру. Разделы слева, поиск и фильтры сверху, в таблице — масса, цена из прайса,
 * поставщик. «Выбрать» (или двойной щелчок) — props.onPick("profile:ID" | "sheet:ID" |
 * "fastener:ID"). «Нет в справочнике — завести» — та же короткая форма «на разнос», что в
 * расчёте (pmk_calc pending_create.js), новая позиция сразу выбрана.
 *
 * Открыть: openCatalog(env, { text, sections: ["fastener"], onPick: async (key) => {...} }).
 * Сервер — pmk.metal.catalog (models/catalog.py).
 */
import { Component, onMounted, onWillStart, useRef, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { useService } from "@web/core/utils/hooks";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";
import { _t } from "@web/core/l10n/translation";

const MODEL = { profile: "pmk.metal.profile", sheet: "pmk.metal.sheet", fastener: "pmk.metal.fastener" };
const PENDING_FORM = {
    profile: "pmk_calc.view_metal_profile_pending_form",
    sheet: "pmk_calc.view_metal_sheet_pending_form",
    fastener: "pmk_calc.view_metal_fastener_pending_form",
};

export class PmkCatalogDialog extends Component {
    static template = "pmk_bridge.CatalogDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        onPick: Function,
        text: { type: String, optional: true },
        sections: { type: Array, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.state = useState({
            tree: [], section: null, kind: null, query: "", strength_class: "", coating: "",
            priced: false, rows: [], more: false, sel: null, loading: false, busy: false,
        });
        onWillStart(async () => {
            const sections = this.props.sections || null;
            const [tree, guess] = await Promise.all([
                this.orm.call("pmk.metal.catalog", "catalog_tree", [sections]),
                this.orm.call("pmk.metal.catalog", "catalog_guess", [this.props.text || "", sections]),
            ]);
            this.state.tree = tree;
            this.state.section = guess.section;
            this.state.kind = guess.kind;
            this.state.query = guess.query || "";
            await this.search();
        });
        // Раздел, с которого открыли (метизы — внизу дерева), — в видимую часть.
        this.treeRef = useRef("tree");
        onMounted(() => {
            this.treeRef.el?.querySelector(".o_pmk_catalog__kind--on")?.scrollIntoView({ block: "center" });
        });
    }

    get isFastener() {
        return this.state.section === "fastener";
    }

    async search() {
        const s = this.state;
        s.loading = true;
        const res = await this.orm.call("pmk.metal.catalog", "catalog_search", [
            s.section, s.kind, s.query, this.isFastener ? s.strength_class : "",
            this.isFastener ? s.coating : "", s.priced,
        ]);
        s.rows = res.rows;
        s.more = res.more;
        s.sel = res.rows.length === 1 ? res.rows[0].key : null;
        s.loading = false;
    }

    selectKind(section, kind) {
        Object.assign(this.state, { section, kind, strength_class: "", coating: "" });
        this.search();
    }

    onQuery(ev) {
        this.state.query = ev.target.value;
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.search(), 300);
    }

    onFilter(field, ev) {
        this.state[field] = ev.target.type === "checkbox" ? ev.target.checked : ev.target.value;
        this.search();
    }

    priceText(row) {
        if (!row.price) {
            return "";
        }
        return row.price.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    async pick(key) {
        key = key || this.state.sel;
        if (!key || this.state.busy) {
            return;
        }
        this.state.busy = true;
        try {
            await this.props.onPick(key);
            this.props.close();
        } finally {
            this.state.busy = false;
        }
    }

    /** Название позиции «на разнос»: текст строки, иначе вид раздела + поиск («Болт м20х60 нерж»). */
    pendingName() {
        if (this.props.text) {
            return this.props.text;
        }
        const sec = this.state.tree.find((t) => t.key === this.state.section);
        const kind = sec && sec.kinds.find((k) => k.key === this.state.kind);
        const query = this.state.query.trim();
        if (!kind || query.toLowerCase().startsWith(kind.label.toLowerCase().slice(0, 4))) {
            return query;
        }
        return `${kind.label} ${query}`.trim();
    }

    createPending() {
        if (this.state.section === "all") {
            this.dialog.add(AlertDialog, {
                body: _t("Выберите слева, что заводите: прокат, лист или метиз — у них разные поля."),
            });
            return;
        }
        const section = this.state.section;
        const context = {
            form_view_ref: PENDING_FORM[section],
            default_pmk_pending: true,
            default_pmk_pending_name: this.pendingName(),
        };
        if (section === "fastener" && this.state.kind) {
            context.default_fastener_type = this.state.kind;
        }
        if (section === "profile" && this.state.kind) {
            context.default_type_id = this.state.kind;
        }
        this.dialog.add(FormViewDialog, {
            resModel: MODEL[section],
            context,
            title: _t("Новая позиция на разнос"),
            onRecordSaved: async (record) => {
                await this.pick(`${section}:${record.resId}`);
            },
        });
    }
}

export function openCatalog(env, { text = "", sections = null, onPick }) {
    env.services.dialog.add(PmkCatalogDialog, { text, sections: sections || undefined, onPick });
}
