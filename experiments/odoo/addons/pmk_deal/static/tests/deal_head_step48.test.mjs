// Шаг 48 разбора UX: подпись строки пути у сделки.
//
// Запуск из корня репозитория (нужен только node, без браузера и Odoo):
//   node experiments/odoo/addons/pmk_deal/static/tests/deal_head_step48.test.mjs
// Проверяется модуль ../src/js/deal_head_rules.js (чистая функция без
// импортов Odoo). Файл не попадает ни в один бандл: в манифесте pmk_deal
// ассеты перечислены поимённо, а .mjs сборщик ассетов не берёт.
import assert from "node:assert/strict";

const RULES = process.env.PMK_RULES
    || new URL("../src/js/deal_head_rules.js", import.meta.url).href;
const { dealCrumbLabel } = await import(RULES);

let n = 0;
function t(name, fn) { fn(); n++; console.log("ok -", name); }

t("сделка с номером — номер с датой", () => {
    assert.equal(
        dealCrumbLabel({ type: "opportunity", pmk_number_label: "СД-00001 от 27.09.2026" }),
        "СД-00001 от 27.09.2026");
});

t("сделка без номера (новая, архивная) — пусто: подпись штатная", () => {
    assert.equal(dealCrumbLabel({ type: "opportunity", pmk_number_label: "" }), "");
    assert.equal(dealCrumbLabel({ type: "opportunity", pmk_number_label: false }), "");
    assert.equal(dealCrumbLabel({ type: "opportunity" }), "");
});

t("лид — пусто, даже если номер остался от сделки", () => {
    assert.equal(dealCrumbLabel({ type: "lead", pmk_number_label: "СД-00002 от 03.10.2026" }), "");
});

t("нет данных — пусто", () => {
    assert.equal(dealCrumbLabel(undefined), "");
    assert.equal(dealCrumbLabel(null), "");
    assert.equal(dealCrumbLabel({}), "");
});

t("пробелы по краям срезаны", () => {
    assert.equal(dealCrumbLabel({ type: "opportunity", pmk_number_label: " СД-00003 " }), "СД-00003");
});

console.log(`\n${n} проверок пройдено`);
