// Шапка документа «вариант А» (Антон 25.10.2026): одна главная кнопка,
// остальные — в «Ещё ▾», виджеты — в ряду. Правила без Odoo.
//
// Запуск из корня репозитория:
//   node experiments/odoo/addons/pmk_theme/static/tests/form_head_a.test.mjs
import assert from "node:assert/strict";

const RULES = process.env.PMK_RULES
    || new URL("../src/js/form_head_rules.js", import.meta.url).href;
const { HEAD_A_CLASS, headButtonFlags, splitHeadSlots } = await import(RULES);

assert.equal(HEAD_A_CLASS, "o_pmk_head_a");

// Классы кнопки приходят выражением компилятора: `btn-primary` + ` ` + `...`.
assert.deepEqual(headButtonFlags("`btn-primary` + ` ` + ``"), { primary: true, more: false, keep: false });
assert.deepEqual(headButtonFlags("`oe_highlight`"), { primary: true, more: false, keep: false });
assert.deepEqual(headButtonFlags("`btn-primary o_pmk_more`"), { primary: true, more: true, keep: false });
assert.deepEqual(headButtonFlags("`btn-secondary o_pmk_keep`"), { primary: false, more: false, keep: true });
assert.deepEqual(headButtonFlags("", true), { primary: false, more: false, keep: true }, "виджет — в ряду");
assert.equal(headButtonFlags("`btn-primary-x`").primary, false, "только целый класс");

// Счёт в черновике: «Технический расчёт» уступает «На согласование».
assert.deepEqual(
    splitHeadSlots([
        { name: "tech", primary: true, more: true },
        { name: "menu", keep: true },
        { name: "approve", primary: true },
        { name: "cancel" },
    ]),
    { main: "approve", more: ["tech", "cancel"], keep: ["menu"] }
);
// Счёт в работе: другой главной нет — «Технический расчёт» главная.
assert.deepEqual(
    splitHeadSlots([{ name: "tech", primary: true, more: true }, { name: "menu", keep: true }, { name: "cancel" }]),
    { main: "tech", more: ["cancel"], keep: ["menu"] }
);
// Главных две — главная первая, вторая в «Ещё ▾».
assert.deepEqual(
    splitHeadSlots([{ name: "a", primary: true }, { name: "b", primary: true }]),
    { main: "a", more: ["b"], keep: [] }
);
// Главной нет — все в «Ещё ▾».
assert.deepEqual(splitHeadSlots([{ name: "x" }, { name: "y" }]), { main: null, more: ["x", "y"], keep: [] });
assert.deepEqual(splitHeadSlots([]), { main: null, more: [], keep: [] });

console.log("form_head_a: ok");
