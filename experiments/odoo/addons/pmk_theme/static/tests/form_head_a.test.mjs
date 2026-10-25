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
assert.deepEqual(headButtonFlags("`btn-primary` + ` ` + ``"), { primary: true, more: false, keep: false, skip: false, pin: false });
assert.deepEqual(headButtonFlags("`oe_highlight`"), { primary: true, more: false, keep: false, skip: false, pin: false });
assert.deepEqual(headButtonFlags("`btn-primary o_pmk_more`"), { primary: true, more: true, keep: false, skip: false, pin: false });
assert.deepEqual(headButtonFlags("`btn-secondary o_pmk_keep`"), { primary: false, more: false, keep: true, skip: false, pin: false });
assert.deepEqual(headButtonFlags("", true), { primary: false, more: false, keep: true, skip: false, pin: false }, "виджет — в ряду");
assert.equal(headButtonFlags("`btn-primary-x`").primary, false, "только целый класс");
assert.equal(headButtonFlags("`btn-primary o_pmk_in_create`").skip, true, "есть в «Создать ▾»");
assert.equal(headButtonFlags("`o_pmk_in_cog`").skip, true, "есть в «⚙»");

// Счёт в черновике у руководителя: «На согласование» главная, «Согласовано» —
// одна — обычной кнопкой; «Технический расчёт» и «Отменить счёт» — в меню.
assert.deepEqual(
    splitHeadSlots([
        { name: "tech", primary: true, skip: true },
        { name: "menu", keep: true },
        { name: "toApproval", primary: true },
        { name: "approve", primary: true },
        { name: "cancel", skip: true },
    ]),
    { pinned: [], main: "toApproval", inline: ["approve"], more: [], keep: ["menu"] }
);
// Счёт в работе: шага нет — ни главной, ни «Ещё ▾».
assert.deepEqual(
    splitHeadSlots([{ name: "tech", primary: true, skip: true }, { name: "menu", keep: true }, { name: "cancel", skip: true }]),
    { pinned: [], main: null, inline: [], more: [], keep: ["menu"] }
);
// «Ещё ▾» — от двух; главная с o_pmk_more уступает.
assert.deepEqual(
    splitHeadSlots([{ name: "a", primary: true, more: true }, { name: "b", primary: true }, { name: "c" }]),
    { pinned: [], main: "b", inline: [], more: ["a", "c"], keep: [] }
);
// Другой главной нет — уступающая главная.
assert.deepEqual(
    splitHeadSlots([{ name: "a", primary: true, more: true }, { name: "c" }]),
    { pinned: [], main: "a", inline: ["c"], more: [], keep: [] }
);
assert.deepEqual(splitHeadSlots([]), { pinned: [], main: null, inline: [], more: [], keep: [] });
// Пометка расчёта («Без цены клиенту») — справа первой, не в «Ещё ▾».
assert.deepEqual(headButtonFlags("", false, true), { primary: false, more: false, keep: false, skip: false, pin: true });
assert.deepEqual(
    splitHeadSlots([{ name: "menu", keep: true }, { name: "signal", pin: true }, { name: "refresh" }]),
    { pinned: ["signal"], main: null, inline: ["refresh"], more: [], keep: ["menu"] }
);

console.log("form_head_a: ok");
