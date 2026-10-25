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
//
// Упрощение 25.10.2026 (Антон: «окно фильтров перегружено»; прототип в чате, «делай
// везде»): поля разложены рядами по виду — период строкой чипов («Свой…» открывает
// даты), выбор записей и суммы — в один ряд, варианты — чипами с группами, «да/нет»
// и «Мои …» — одной строкой «Показать только» (пара «да/нет» — два взаимоисключающих
// чипа). Штатные «Фильтры / Группировка / Избранное» свёрнуты под ссылку внизу;
// «Найдено N» + «Найти» → одна кнопка «Показать N».

import { Component, onMounted, onWillStart, useState } from "@odoo/owl";
import { Domain } from "@web/core/domain";
import { patch } from "@web/core/utils/patch";
import { useBus, useService } from "@web/core/utils/hooks";
import { useDropdownCloser } from "@web/core/dropdown/dropdown_hooks";
import { user } from "@web/core/user";
import { MultiRecordSelector } from "@web/core/record_selectors/multi_record_selector";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { SearchBarMenu } from "@web/search/search_bar_menu/search_bar_menu";

// Статусы МоегоСклада: ключ — как в МС, подпись короче, группа — по жизни счёта.
const MS_STATES = [
    ["Согласование", "Согласование", "оплата"],
    ["Предоплата получена", "Предоплата", "оплата"],
    ["Оплачен", "Оплачен", "оплата"],
    ["Постоплата", "Постоплата", "оплата"],
    ["В производство", "В производстве", "цех"],
    ["Заказ готов", "Готов", "цех"],
    ["Заказ отгружен", "Отгружен", "цех"],
    ["Заказ работника", "Заказ работника", "прочее"],
    ["Не актуальна", "Не актуален", "прочее"],
];

// type: period | many | range | choice | mine | tri | flag
// Ряды окна: period — строка чипов; many и range — один ряд полей; choice — чипы
// (третий элемент варианта — подпись группы); mine, tri, flag — «Показать только».
// tri: yes / no — подписи двух чипов; flag и mine — один чип с подписью label.
const CONFIG = {
    invoices: [
        { name: "date_order", type: "period", label: "Период" },
        { name: "partner_id", type: "many", label: "Контрагент", model: "res.partner" },
        { name: "pmk_org_id", type: "many", label: "Наша организация", model: "pmk.org" },
        { name: "amount_total", type: "range", label: "Сумма, ₽" },
        { name: "pmk_ms_state", type: "choice", label: "Статус в МоёмСкладе", choices: MS_STATES },
        { name: "user_id", type: "mine", label: "Мои счета" },
        { name: "pmk_ms_shipped_date", type: "tri", label: "Отгрузка", yes: "Отгружены", no: "Не отгружены" },
        { name: "pmk_ms_id", type: "tri", label: "Откуда", yes: "Из МоегоСклада", no: "Из расчёта" },
        { name: "pmk_ms_note", type: "flag", label: "Расходятся с МС" },
    ],
    specs: [
        { name: "date", type: "period", label: "Период" },
        { name: "partner_id", type: "many", label: "Клиент", model: "res.partner" },
        { name: "pmk_org_id", type: "many", label: "Наша организация", model: "pmk.org" },
        { name: "opportunity_id", type: "many", label: "Сделка", model: "crm.lead" },
        { name: "price_customer_total", type: "range", label: "Цена клиенту, ₽" },
        { name: "pmk_kind", type: "choice", label: "Вид", choices: [["kp", "Для КП"], ["tech", "Технический"]] },
        // Менеджера у расчёта нет — «мои» по автору.
        { name: "create_uid", type: "mine", label: "Мои расчёты" },
        { name: "cat_dobor", type: "flag", label: "С доборкой" },
        { name: "cat_vent", type: "flag", label: "С вентзонтами" },
    ],
    deals: [
        { name: "create_date", type: "period", label: "Создана" },
        { name: "partner_id", type: "many", label: "Клиент", model: "res.partner" },
        { name: "stage_id", type: "many", label: "Стадия", model: "crm.stage" },
        { name: "user_id", type: "many", label: "Менеджер", model: "res.users" },
        { name: "pmk_org_id", type: "many", label: "Наша организация", model: "pmk.org" },
        { name: "expected_revenue", type: "range", label: "Сумма, ₽" },
        { name: "user_id", type: "mine", label: "Мои сделки", key: "user_id_mine" },
    ],
    orders: [
        { name: "pmk_date_due", type: "period", label: "Срок сдачи" },
        { name: "partner_id", type: "many", label: "Клиент", model: "res.partner" },
        { name: "stage_id", type: "many", label: "Этап", model: "project.task.type",
          domain: (ctx) => (ctx.default_project_id ? [["project_ids", "in", [ctx.default_project_id]]] : []) },
        { name: "user_ids", type: "many", label: "Ответственный", model: "res.users" },
        { name: "pmk_org_id", type: "many", label: "Наша организация", model: "pmk.org" },
        { name: "pmk_amount", type: "range", label: "Сумма, ₽" },
        { name: "user_ids", type: "mine", label: "Мои заказы", key: "user_ids_mine" },
        { name: "pmk_sale_order_id", type: "tri", label: "Счёт", yes: "Со счётом", no: "Без счёта" },
        { name: "pmk_overdue", type: "flag", label: "Просроченные" },
    ],
};

const QUICK = [["today", "Сегодня"], ["week", "Неделя"], ["month", "Месяц"],
    ["quarter", "Квартал"], ["year", "Год"]];

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

function loadStd(key) {
    try {
        return window.localStorage.getItem(`${storageKey(key)}:std`) === "1";
    } catch {
        return false;
    }
}

function saveStd(key, open) {
    try {
        window.localStorage.setItem(`${storageKey(key)}:std`, open ? "1" : "0");
    } catch {
        // приватный режим — без запоминания
    }
}

// Поля набора, которые есть у модели, — один запрос на модель за сеанс.
const fieldsCache = new Map();
function fieldsFor(orm, resModel, key) {
    if (!fieldsCache.has(key)) {
        fieldsCache.set(key, orm.call(resModel, "fields_get", [], { attributes: ["type"] }).then((meta) =>
            CONFIG[key].filter((f) => f.name in meta)
                .map((f) => ({ ...f, key: f.key || f.name, ftype: meta[f.name].type }))
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
    const v = values[f.key || f.name] || {};
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
        case "mine":
            return Boolean(v.on);
    }
    return false;
}

// uid — для «Мои …»; по умолчанию — вошедший пользователь.
export function domainAndLabel(fields, values, uid = user.userId) {
    const domain = [];
    const parts = [];
    for (const f of fields) {
        if (!isActive(f, values)) {
            continue;
        }
        const v = values[f.key || f.name];
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
        } else if (f.type === "mine") {
            domain.push(f.ftype === "many2many" ? [f.name, "in", [uid]] : [f.name, "=", uid]);
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

// Условия поиска без нашей плашки: остальные плашки («Мои счета»…), боковая
// панель и условия самого окна. Запрос поиска подменяется на время одного
// синхронного расчёта и сразу возвращается.
function domainWithoutPlate(sm) {
    const groupId = plates.get(sm);
    const query = sm.query;
    if (groupId) {
        sm.query = query.filter((q) => sm.searchItems[q.searchItemId]?.groupId !== groupId);
    }
    try {
        return sm._getDomain({ raw: true });
    } catch {
        return new Domain(sm.globalDomain || []);
    } finally {
        sm.query = query;
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
        this.quickList = QUICK;
        this.state = useState({
            values: loadValues(this.props.configKey),
            fields: [],
            count: null,
            // Штатные «Фильтры / Группировка / Избранное» — свёрнуты; раскрыл —
            // запоминается (кто группирует часто, не раскрывает каждый раз).
            std: loadStd(this.props.configKey),
            // «Свой…» нажат, даты ещё не введены — поля дат уже видны.
            custom: false,
        });
        onWillStart(async () => {
            this.state.fields = await fieldsFor(this.orm, this.sm.resModel, this.props.configKey);
            this.recount();
        });
    }

    get fields() {
        return this.state.fields;
    }

    // ─── Ряды окна ────────────────────────────────────────────────────────
    get periodField() {
        return this.fields.find((f) => f.type === "period");
    }

    get inputFields() {
        return this.fields.filter((f) => f.type === "many" || f.type === "range");
    }

    get choiceFields() {
        return this.fields.filter((f) => f.type === "choice");
    }

    get toggleFields() {
        return this.fields.filter((f) => f.type === "mine" || f.type === "tri" || f.type === "flag");
    }

    get activeCount() {
        return this.fields.filter((f) => isActive(f, this.state.values)).length;
    }

    // Варианты с подписью группы перед первым вариантом группы.
    choiceItems(f) {
        let group = null;
        return f.choices.map((c) => {
            const head = c[2] && c[2] !== group ? c[2] : "";
            group = c[2] || group;
            return { key: c[0], label: c[1], head };
        });
    }

    // Чипы «Показать только»: tri — два взаимоисключающих, flag и mine — один.
    toggleItems() {
        const items = [];
        for (const f of this.toggleFields) {
            const v = this.value(f.key);
            if (f.type === "tri") {
                items.push({ id: `${f.key}:yes`, label: f.yes, on: v.mode === "yes", f, mode: "yes" });
                items.push({ id: `${f.key}:no`, label: f.no, on: v.mode === "no", f, mode: "no" });
            } else {
                items.push({ id: f.key, label: f.label, on: Boolean(v.on), f });
            }
        }
        return items;
    }

    toggle(item) {
        if (item.f.type === "tri") {
            this.set(item.f.key, { mode: item.on ? "" : item.mode });
        } else {
            this.set(item.f.key, { on: !item.on });
        }
    }

    value(key) {
        return this.state.values[key] || {};
    }

    set(key, patchValues) {
        this.state.values[key] = { ...this.value(key), ...patchValues };
        this.recount();
    }

    // «Показать N» — сколько документов покажет список: условия окна плюс
    // остальные плашки поиска.
    recount() {
        clearTimeout(this.timer);
        this.timer = setTimeout(async () => {
            const { domain } = domainAndLabel(this.fields, this.state.values);
            const full = Domain.and([domainWithoutPlate(this.sm), domain]).toList(this.sm.domainEvalContext);
            try {
                this.state.count = await this.orm.searchCount(this.sm.resModel, full);
            } catch {
                this.state.count = null;
            }
        }, 300);
    }

    get countLabel() {
        const n = this.state.count;
        return n === null ? "Показать" : `Показать ${n.toLocaleString("ru-RU")}`;
    }

    // ─── Период ───────────────────────────────────────────────────────────
    // Чип «Всё время» — когда дат нет; «Свой…» — даты введены руками (или
    // нажат и ждёт дат); остальные — по своему ключу.
    get periodValue() {
        const f = this.periodField;
        return f ? this.value(f.key) : {};
    }

    get periodCustom() {
        const v = this.periodValue;
        return this.state.custom || Boolean((v.from || v.to) && !QUICK.some((q) => q[0] === v.quick));
    }

    quickActive(kind) {
        const v = this.periodValue;
        if (kind === "all") {
            return !this.periodCustom && !v.from && !v.to;
        }
        return !this.periodCustom && v.quick === kind;
    }

    quick(kind) {
        const f = this.periodField;
        this.state.custom = false;
        if (kind === "custom") {
            this.state.custom = true;
            return;
        }
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
            this.set(f.key, { from: "", to: "", quick: "" });
        } else {
            this.set(f.key, { from: ymd(from), to: ymd(now), quick: kind });
        }
    }

    toggleChoice(f, key) {
        const keys = new Set(this.value(f.key).keys || []);
        keys.has(key) ? keys.delete(key) : keys.add(key);
        this.set(f.key, { keys: [...keys] });
    }

    toggleStd() {
        this.state.std = !this.state.std;
        saveStd(this.props.configKey, this.state.std);
    }

    onKeydown(ev) {
        // Enter в поле суммы/даты — как «Показать» (в выборе записей Enter
        // выбирает запись — его не трогаем).
        if (ev.key === "Enter" && ev.target.matches("input.pmk-filter__in")) {
            ev.preventDefault();
            ev.target.dispatchEvent(new Event("change", { bubbles: true }));
            this.apply();
        }
    }

    apply() {
        saveValues(this.props.configKey, this.state.values);
        applyFilter(this.sm, this.fields, this.state.values);
        this.closer.close();
    }

    clear() {
        this.state.values = {};
        this.state.custom = false;
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
