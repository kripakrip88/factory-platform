/** @odoo-module **/
// Фильтр документов, как в МоёмСкладе (Антон 13.10.2026: «сейчас только поиск, не
// особо нравится им пользоваться»; «кнопка, которая вызывает окно — может, в нём
// сделаем то, что на прототипе»; вид — первого прототипа: подписи мелко серым над
// полями, сетка в четыре колонки, быстрые периоды кружками).
//
// Где: окно кнопки с ползунками в строке поиска, над «Фильтры / Группировка /
// Избранное» (patch SearchBarMenu). «Найти» добавляет в поиск одну плашку
// «Фильтр: …»; крестик на плашке снимает её и забывает условия. Условия
// запоминаются в браузере у каждого и сами применяются при открытии списка
// (patch SearchBar — он виден всегда, окно ползунков — только открытое).
//
// Списки: «Счета покупателям» (sale.order), «Расчёты» (pmk.metal.spec), «Сделки»
// (crm.lead), «Заказы в работе» (project.task окна планировщика — по ключу
// default_pmk_metal в контексте, чтобы доска «Доработка системы» фильтра не получила).
// Набор полей — CONFIG; поле, которого у модели нет (модуль не стоит), пропускается.

import { Component, onMounted, onWillStart, useState } from "@odoo/owl";
import { Domain } from "@web/core/domain";
import { patch } from "@web/core/utils/patch";
import { useBus, useService } from "@web/core/utils/hooks";
import { useDropdownCloser } from "@web/core/dropdown/dropdown_hooks";
import { MultiRecordSelector } from "@web/core/record_selectors/multi_record_selector";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { SearchBarMenu } from "@web/search/search_bar_menu/search_bar_menu";

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

// Какой набор полей у этого поиска; null — фильтра нет (чужой список, окно выбора).
export function filterKeyFor(env) {
    const sm = env.searchModel;
    if (!sm || env.inDialog) {
        return null;
    }
    if (sm.resModel === "project.task") {
        return "default_pmk_metal" in (sm.globalContext || {}) ? "orders" : null;
    }
    return MODEL_KEY[sm.resModel] || null;
}

function storageKey(key) {
    return `pmk_filter:${key}`;
}

function loadValues(key) {
    try {
        return JSON.parse(window.localStorage.getItem(storageKey(key)) || "{}");
    } catch {
        return {};
    }
}

function saveValues(key, values) {
    try {
        window.localStorage.setItem(storageKey(key), JSON.stringify(values));
    } catch {
        // приватный режим — без запоминания
    }
}

// Поля набора, которые есть у модели, — один запрос на модель за сеанс.
const fieldsCache = new Map();
function fieldsFor(orm, resModel, key) {
    if (!fieldsCache.has(key)) {
        fieldsCache.set(key, orm.call(resModel, "fields_get", [], { attributes: ["type"] }).then((meta) =>
            CONFIG[key].filter((f) => f.name in meta).map((f) => ({ ...f, ftype: meta[f.name].type }))
        ));
    }
    return fieldsCache.get(key);
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

function isActive(f, values) {
    const v = values[f.name] || {};
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

export function domainAndLabel(fields, values) {
    const domain = [];
    const parts = [];
    for (const f of fields) {
        if (!isActive(f, values)) {
            continue;
        }
        const v = values[f.name];
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

// Плашка фильтра в поиске: номер её группы — на сам поиск (у каждого списка свой).
const plates = new WeakMap();

function plateActive(sm) {
    const groupId = plates.get(sm);
    return Boolean(groupId) && sm.query.some((q) => sm.searchItems[q.searchItemId]?.groupId === groupId);
}

function applyFilter(sm, fields, values) {
    const old = plates.get(sm);
    plates.delete(sm); // до снятия: слушатель снятия не должен забыть условия
    if (old) {
        sm.deactivateGroup(old);
    }
    const { domain, label } = domainAndLabel(fields, values);
    if (domain.length) {
        plates.set(sm, sm.nextGroupId);
        sm.createNewFilters([{ description: `Фильтр: ${label}`, domain: new Domain(domain).toString() }]);
    }
}

// ─── Окно ползунков: поля фильтра над «Фильтры / Группировка / Избранное» ────

export class PmkFilterPanel extends Component {
    static template = "pmk_orders.FilterPanel";
    static components = { MultiRecordSelector };
    static props = { configKey: String };

    setup() {
        this.orm = useService("orm");
        this.closer = useDropdownCloser();
        this.sm = this.env.searchModel;
        this.state = useState({ values: loadValues(this.props.configKey), fields: [], count: null });
        this.periods = [["today", "Сегодня"], ["week", "Неделя"], ["month", "Месяц"],
            ["quarter", "Квартал"], ["year", "Год"], ["all", "Всё время"]];
        onWillStart(async () => {
            this.state.fields = await fieldsFor(this.orm, this.sm.resModel, this.props.configKey);
            this.recount();
        });
    }

    get fields() {
        return this.state.fields;
    }

    get periodField() {
        return this.fields.find((f) => f.type === "period");
    }

    get activeCount() {
        return this.fields.filter((f) => isActive(f, this.state.values)).length;
    }

    value(name) {
        return this.state.values[name] || {};
    }

    set(name, patchValues) {
        this.state.values[name] = { ...this.value(name), ...patchValues };
        this.recount();
    }

    // «Найдено: N» — сколько документов даст фильтр (с условиями самого окна списка).
    recount() {
        clearTimeout(this.timer);
        this.timer = setTimeout(async () => {
            const { domain } = domainAndLabel(this.fields, this.state.values);
            const full = Domain.and([this.sm.globalDomain || [], domain]).toList();
            try {
                this.state.count = await this.orm.searchCount(this.sm.resModel, full);
            } catch {
                this.state.count = null;
            }
        }, 300);
    }

    quickActive(kind) {
        const f = this.periodField;
        const v = f && this.value(f.name);
        return Boolean(v) && v.quick === kind;
    }

    quick(kind) {
        const f = this.periodField;
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
        }
        if (kind === "all") {
            this.set(f.name, { from: "", to: "", quick: "all" });
        } else {
            this.set(f.name, { from: ymd(from), to: ymd(now), quick: kind });
        }
    }

    toggleChoice(f, key) {
        const keys = new Set(this.value(f.name).keys || []);
        keys.has(key) ? keys.delete(key) : keys.add(key);
        this.set(f.name, { keys: [...keys] });
    }

    apply() {
        saveValues(this.props.configKey, this.state.values);
        applyFilter(this.sm, this.fields, this.state.values);
        this.closer.close();
    }

    clear() {
        this.state.values = {};
        saveValues(this.props.configKey, {});
        applyFilter(this.sm, this.fields, {});
        this.recount();
    }
}

// Компоненты — через t-component и свойство прототипа: у наследников свои
// наборы components, скопированные раньше нас.
patch(SearchBarMenu.prototype, {
    get pmkFilterKey() {
        return filterKeyFor(this.env);
    },
    get pmkFilterPanel() {
        return PmkFilterPanel;
    },
});

// Строка поиска видна всегда: она применяет запомненный фильтр при открытии
// списка и забывает условия, когда плашку сняли крестиком.
patch(SearchBar.prototype, {
    setup() {
        super.setup(...arguments);
        const key = filterKeyFor(this.env);
        if (!key) {
            return;
        }
        const sm = this.env.searchModel;
        const orm = useService("orm");
        onMounted(async () => {
            const values = loadValues(key);
            if (!Object.keys(values).length || plateActive(sm)) {
                return;
            }
            const fields = await fieldsFor(orm, sm.resModel, key);
            if (domainAndLabel(fields, values).domain.length) {
                applyFilter(sm, fields, values);
            }
        });
        useBus(sm, "update", () => {
            if (plates.has(sm) && !plateActive(sm)) {
                plates.delete(sm);
                saveValues(key, {});
            }
        });
    },
});
