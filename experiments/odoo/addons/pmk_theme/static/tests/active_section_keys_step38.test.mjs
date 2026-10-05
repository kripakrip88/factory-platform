// Шаг 38 разбора UX: подсветка «где я» на новых и перенесённых пунктах меню.
//
// Запуск из корня репозитория (нужен только node, без браузера и Odoo):
//   node experiments/odoo/addons/pmk_theme/static/tests/active_section_keys_step38.test.mjs
// Проверяется модуль ключей рядом — ../src/js/active_section_keys.js (чистые
// функции без импортов Odoo, шаг 23). Другой файл — переменная PMK_KEYS:
//   PMK_KEYS=/путь/к/active_section_keys.js node <этот файл>
//
// Меню — как их отдаст load_web_menus после шага 38: номера действий — с
// боевой базы на 05.10.2026, номера новых пунктов условные (9001, 9002).
// Файл не попадает ни в один бандл Odoo: в манифесте pmk_theme ассеты
// перечислены поимённо, а .mjs сборщик ассетов не берёт.
import assert from "node:assert/strict";

const KEYS = process.env.PMK_KEYS
    || new URL("../src/js/active_section_keys.js", import.meta.url).href;
const { controllerKeys, isMenuActive } = await import(KEYS);

let n = 0;
function t(name, fn) { fn(); n++; console.log("ok -", name); }

const item = (id, name, actionID, actionPath = false) =>
    ({ id, name, actionID, actionPath, childrenTree: [] });

// Продажи: Воронка · Почта · Расчёты и КП · Клиенты · Лиды
const sales = [
    item(466, "Воронка сделок", 348),
    item(515, "Почта", 781),
    item(9001, "Расчёты и КП", 755),
    item(470, "Клиенты", 321, "customers"),
    item(467, "Лиды", 345),
];
// Калькуляторы: «Расчёт металлопроката» остаётся (то же действие 755)
const calc = [
    item(501, "Расчёт металлопроката", 755),
    item(502, "Доборные элементы", 756),
    item(506, "Раскрой сортамента", 768),
    { id: 496, name: "Справочники", actionID: false, actionPath: false, childrenTree: [
        item(497, "Линейный прокат", 751), item(498, "Лист", 752)] },
];
// Закупки: Поставщики · Цены поставщиков · Номенклатура · Рассылка прайсов ·
// Заказы поставщикам · Группы поставки
const purchase = [
    item(517, "Поставщики", 783),
    item(529, "Цены поставщиков", 800, "supplier-prices"),
    item(9002, "Номенклатура", 517),
    item(519, "Рассылка прайсов", 785, "price-mailing"),
    item(477, "Заказы поставщикам", 624, "purchase"),
    item(518, "Группы поставки", 782),
];
// С «Убранным» к ним добавляются: Все поставщики (322), Почта (780),
// Подтверждённые заказы (625).
const purchaseRemoved = [
    ...purchase,
    item(479, "Все поставщики", 322, "vendors"),
    item(516, "Почта", 780),
    item(478, "Подтверждённые заказы", 625, "purchase-orders"),
];
// Склад (с «Склад (показать)»): своя «Номенклатура» — то же действие 517.
const stock = [
    item(480, "Обзор операций", 511),
    item(484, "Номенклатура", 517),
];

const lit = (sections, action) =>
    sections.filter((s) => isMenuActive(s, controllerKeys(action))).map((s) => s.name);

t("Продажи → «Расчёты и КП» (755) горит один", () => {
    assert.deepEqual(lit(sales, { id: 755 }), ["Расчёты и КП"]);
});

t("Калькуляторы → то же действие 755 горит своим пунктом", () => {
    assert.deepEqual(lit(calc, { id: 755 }), ["Расчёт металлопроката"]);
});

t("Расчёт, открытый со сделки (окно без номера и path) — ничего не горит, как и до шага", () => {
    assert.deepEqual(lit(sales, { type: "ir.actions.act_window", res_model: "pmk.metal.spec" }), []);
});

t("Закупки → «Поставщики» (783) — не «Все поставщики» (322)", () => {
    assert.deepEqual(lit(purchaseRemoved, { id: 783 }), ["Поставщики"]);
    assert.deepEqual(lit(purchaseRemoved, { id: 322, path: "vendors" }), ["Все поставщики"]);
});

t("Закупки → «Номенклатура» (517) горит в Закупках", () => {
    assert.deepEqual(lit(purchase, { id: 517 }), ["Номенклатура"]);
});

t("Номенклатура и в Складе — горит только пункт текущего раздела", () => {
    assert.deepEqual(lit(stock, { id: 517 }), ["Номенклатура"]);
    assert.deepEqual(lit(purchase, { id: 517 }), ["Номенклатура"]);
});

t("«Заказы поставщикам» = действие запросов КП (624, path purchase)", () => {
    assert.deepEqual(lit(purchase, { id: 624, path: "purchase" }), ["Заказы поставщикам"]);
    // Восстановлено из адреса /odoo/purchase — id приходит строкой-path.
    assert.deepEqual(lit(purchase, { id: "purchase" }), ["Заказы поставщикам"]);
    // «Подтверждённые заказы» (625) не горят на общем списке и наоборот.
    assert.deepEqual(lit(purchaseRemoved, { id: 625, path: "purchase-orders" }), ["Подтверждённые заказы"]);
});

t("Цены поставщиков и рассылка — по path тоже", () => {
    assert.deepEqual(lit(purchase, { id: 800, path: "supplier-prices" }), ["Цены поставщиков"]);
    assert.deepEqual(lit(purchase, { type: "ir.actions.act_window", path: "price-mailing" }), ["Рассылка прайсов"]);
});

t("Внутри раздела ключи пунктов не повторяются (иначе горели бы два)", () => {
    for (const [name, sections] of [["Продажи", sales], ["Закупки", purchase],
                                    ["Закупки с Убранным", purchaseRemoved], ["Калькуляторы", calc]]) {
        const keys = sections.flatMap((s) => [s.actionID && `action-${s.actionID}`, s.actionPath].filter(Boolean));
        assert.equal(new Set(keys).size, keys.length, name);
    }
});

console.log(`\n${n} проверок прошло`);
