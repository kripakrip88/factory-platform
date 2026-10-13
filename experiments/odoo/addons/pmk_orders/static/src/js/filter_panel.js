/** @odoo-module **/
// Панель «Фильтр» над списком, как в МоёмСкладе (Антон 13.10.2026: «сейчас только
// поиск, не особо нравится им пользоваться»). Свёрнута по умолчанию; «Найти»
// добавляет в поиск одну плашку «Фильтр: …» (снимается крестиком, как любая),
// «Очистить» — убирает. Условия запоминаются в браузере у каждого.
//
// Списки: «Счета покупателям» (sale.order), «Расчёты» (pmk.metal.spec), «Сделки»
// (crm.lead), «Заказы в работе» (project.task окна планировщика — по ключу
// default_pmk_metal в контексте, чтобы доска «Доработка системы» панели не получила).
// Набор полей — CONFIG; поле, которого у модели нет (модуль не стоит), пропускается.

import { Component, onMounted, onWillStart, useState } from "@odoo/owl";
import { Domain } from "@web/core/domain";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { MultiRecordSelector } from "@web/core/record_selectors/multi_record_selector";
import { ListController } from "@web/views/list/list_controller";
import { KanbanController } from "@web/views/kanban/kanban_controller";

const MS_STATES = ["Согласование", "Предоплата получена", "Оплачен", "Постоплата", "В производство",
    "Заказ готов", "Заказ отгружен", "Заказ работника", "Не актуальна"];

// type: period | many | choice | range | tri | flag
const CONFIG = {
    invoices: [
        { name: "date_order", type: "period", label: "Период" },
        { name: "partner_id", type: "many", label: "Контрагент", model: "res.partner" },
        { name: "pmk_org_id", type: "many", label: "Наша организация", model: "pmk.org" },
        { name: "pmk_ms_state", type: "choice", label: "Статус МоегоСклада",
          choices: MS_STATES.map((s) => [s, s]) },
        { name: "amount_total", type: "range", label: "Сумма, ₽" },
        { name: "pmk_ms_shipped_date", type: "tri", label: "Отгрузка", yes: "отгружен", no: "не отгружен" },
        { name: "pmk_ms_id", type: "tri", label: "Откуда", yes: "МойСклад", no: "из расчёта" },
        { name: "pmk_ms_note", type: "flag", label: "Расхождения с МоимСкладом" },
    ],
    specs: [
        { name: "date", type: "period", label: "Период" },
        { name: "partner_id", type: "many", label: "Клиент", model: "res.partner" },
        { name: "pmk_org_id", type: "many", label: "Наша организация", model: "pmk.org" },
        { name: "opportunity_id", type: "many", label: "Сделка", model: "crm.lead" },
        { name: "pmk_kind", type: "choice", label: "Вид", choices: [["kp", "Для КП"], ["tech", "Технический"]] },
        { name: "price_customer_total", type: "range", label: "Цена клиенту, ₽" },
        { name: "cat_dobor", type: "flag", label: "Есть доборка" },
        { name: "cat_vent", type: "flag", label: "Есть вентзонты" },
    ],
    deals: [
        { name: "create_date", type: "period", label: "Создана" },
        { name: "partner_id", type: "many", label: "Клиент", model: "res.partner" },
        { name: "stage_id", type: "many", label: "Стадия", model: "crm.stage" },
        { name: "user_id", type: "many", label: "Менеджер", model: "res.users" },
        { name: "pmk_org_id", type: "many", label: "Наша организация", model: "pmk.org" },
        { name: "expected_revenue", type: "range", label: "Сумма, ₽" },
    ],
    orders: [
        { name: "pmk_date_due", type: "period", label: "Срок сдачи" },
        { name: "partner_id", type: "many", label: "Клиент", model: "res.partner" },
        { name: "stage_id", type: "many", label: "Этап", model: "project.task.type",
          domain: (ctx) => (ctx.default_project_id ? [["project_ids", "in", [ctx.default_project_id]]] : []) },
        { name: "user_ids", type: "many", label: "Ответственный", model: "res.users" },
        { name: "pmk_org_id", type: "many", label: "Наша организация", model: "pmk.org" },
        { name: "pmk_amount", type: "range", label: "Сумма, ₽" },
        { name: "pmk_sale_order_id", type: "tri", label: "Счёт", yes: "привязан", no: "не привязан" },
        { name: "pmk_overdue", type: "flag", label: "Просрочено" },
    ],
};

const MODEL_KEY = { "sale.order": "invoices", "pmk.metal.spec": "specs", "crm.lead": "deals" };

function filterKeyFor(controller) {
    const props = controller.props;
    if (controller.env.inDialog || !props.display?.controlPanel) {
        return null;
    }
    if (props.resModel === "project.task") {
        return "default_pmk_metal" in (props.context || {}) ? "orders" : null;
    }
    return MODEL_KEY[props.resModel] || null;
}

function pad(n) {
    return String(n).padStart(2, "0");
}

function ymd(d) {
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function ru(dateStr) {
    const [y, m, d] = (dateStr || "").split("-");
    return d ? `${d}.${m}.${y.slice(2)}` : "";
}

export class PmkFilterPanel extends Component {
    static template = "pmk_orders.FilterPanel";
    static components = { MultiRecordSelector };
    static props = { configKey: String, resModel: String, context: { type: Object, optional: true } };

    setup() {
        this.orm = useService("orm");
        this.storageKey = `pmk_filter:${this.props.configKey}`;
        this.state = useState({ open: false, values: this.load(), groupId: null, ready: false });
        this.fields = [];
        onWillStart(async () => {
            const meta = await this.orm.call(this.props.resModel, "fields_get", [], { attributes: ["type"] });
            this.fields = CONFIG[this.props.configKey].filter((f) => f.name in meta)
                .map((f) => ({ ...f, ftype: meta[f.name].type }));
            this.state.ready = true;
        });
        // Запомненный фильтр — в поиск, когда список уже показан: во время загрузки
        // вида поиск ещё собирается, и добавленная плашка терялась.
        onMounted(() => {
            if (this.activeCount) {
                this.apply(false);
            }
        });
    }

    load() {
        try {
            return JSON.parse(window.localStorage.getItem(this.storageKey) || "{}");
        } catch {
            return {};
        }
    }

    save() {
        try {
            window.localStorage.setItem(this.storageKey, JSON.stringify(this.state.values));
        } catch {
            // приватный режим — без запоминания
        }
    }

    value(name) {
        return this.state.values[name] || {};
    }

    set(name, patchValues) {
        this.state.values[name] = { ...this.value(name), ...patchValues };
    }

    get activeCount() {
        return this.fields.filter((f) => this.isActive(f)).length;
    }

    isActive(f) {
        const v = this.value(f.name);
        switch (f.type) {
            case "period":
            case "range":
                return Boolean(v.from || v.to);
            case "many":
                return Boolean(v.ids?.length);
            case "choice":
                return Boolean(v.keys?.length);
            case "tri":
                return v.mode === "yes" || v.mode === "no";
            case "flag":
                return Boolean(v.on);
        }
        return false;
    }

    quick(f, kind) {
        const now = new Date();
        let from = new Date(now);
        if (kind === "week") {
            from.setDate(now.getDate() - ((now.getDay() + 6) % 7));
        } else if (kind === "month") {
            from = new Date(now.getFullYear(), now.getMonth(), 1);
        } else if (kind === "quarter") {
            from = new Date(now.getFullYear(), Math.floor(now.getMonth() / 3) * 3, 1);
        } else if (kind === "year") {
            from = new Date(now.getFullYear(), 0, 1);
        } else if (kind === "all") {
            this.set(f.name, { from: "", to: "" });
            return;
        }
        this.set(f.name, { from: ymd(from), to: ymd(now) });
    }

    toggleChoice(f, key) {
        const keys = new Set(this.value(f.name).keys || []);
        keys.has(key) ? keys.delete(key) : keys.add(key);
        this.set(f.name, { keys: [...keys] });
    }

    domainAndLabel() {
        const domain = [];
        const parts = [];
        for (const f of this.fields) {
            if (!this.isActive(f)) {
                continue;
            }
            const v = this.value(f.name);
            if (f.type === "period") {
                const dt = f.ftype === "datetime";
                if (v.from) {
                    domain.push([f.name, ">=", dt ? `${v.from} 00:00:00` : v.from]);
                }
                if (v.to) {
                    domain.push([f.name, "<=", dt ? `${v.to} 23:59:59` : v.to]);
                }
                parts.push(`${f.label} ${ru(v.from) || "…"}–${ru(v.to) || "…"}`);
            } else if (f.type === "range") {
                if (v.from) {
                    domain.push([f.name, ">=", Number(v.from)]);
                }
                if (v.to) {
                    domain.push([f.name, "<=", Number(v.to)]);
                }
                parts.push(`${f.label} ${v.from || "…"}–${v.to || "…"}`);
            } else if (f.type === "many") {
                domain.push([f.name, "in", v.ids]);
                parts.push(`${f.label}: ${v.ids.length}`);
            } else if (f.type === "choice") {
                domain.push([f.name, "in", v.keys]);
                const labels = f.choices.filter((c) => v.keys.includes(c[0])).map((c) => c[1]);
                parts.push(`${f.label}: ${labels.join(", ")}`);
            } else if (f.type === "tri") {
                domain.push([f.name, v.mode === "yes" ? "!=" : "=", false]);
                parts.push(`${f.label}: ${v.mode === "yes" ? f.yes : f.no}`);
            } else if (f.type === "flag") {
                domain.push(f.ftype === "boolean" ? [f.name, "=", true] : [f.name, "!=", false]);
                parts.push(f.label);
            }
        }
        return { domain, label: parts.join("; ") };
    }

    apply(close = true) {
        const searchModel = this.env.searchModel;
        if (this.state.groupId !== null) {
            searchModel.deactivateGroup(this.state.groupId);
            this.state.groupId = null;
        }
        const { domain, label } = this.domainAndLabel();
        this.save();
        if (domain.length) {
            this.state.groupId = searchModel.nextGroupId;
            searchModel.createNewFilters([{ description: `Фильтр: ${label}`, domain: new Domain(domain).toString() }]);
        }
        if (close) {
            this.state.open = false;
        }
    }

    clear() {
        this.state.values = {};
        this.apply(false);
    }
}

// Компонент — через t-component и свойство прототипа, а не через static components:
// у наследников списка (например, SaleFileUploadListController счетов) свой набор
// components, скопированный раньше нас, — имя PmkFilterPanel там не найдётся и
// список упадёт. Свойство прототипа наследники получают по цепочке.
for (const Controller of [ListController, KanbanController]) {
    patch(Controller.prototype, {
        get pmkFilterKey() {
            return filterKeyFor(this);
        },
        get pmkFilterPanel() {
            return PmkFilterPanel;
        },
    });
}
