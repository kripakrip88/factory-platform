// Шаг 48 разбора UX: шапка документа — правила без Odoo.
//
// Запуск из корня репозитория (нужен только node, без браузера и Odoo):
//   node experiments/odoo/addons/pmk_theme/static/tests/form_head_step48.test.mjs
// Проверяется модуль ../src/js/form_head_rules.js (чистые функции без
// импортов Odoo). Другой файл — переменная PMK_RULES. Файл не попадает ни в
// один бандл: ассеты в манифесте pmk_theme перечислены поимённо.
import assert from "node:assert/strict";

const RULES = process.env.PMK_RULES
    || new URL("../src/js/form_head_rules.js", import.meta.url).href;
const {
    HEADER_UP_CLASS,
    HEADER_UP_MIN_SIZE,
    headerUpAt,
    isStatusNode,
    isAlwaysHidden,
    hotkeyLabel,
    pagerTooltip,
    isShortCrumb,
} = await import(RULES);

let n = 0;
function t(name, fn) { fn(); n++; console.log("ok -", name); }

t("метка формы", () => {
    assert.equal(HEADER_UP_CLASS, "o_pmk_header_up");
});

t("шапка наверху — от SIZES.XL (1200 px)", () => {
    // SIZES ядра Odoo 19: XS 0, SM 1, MD 2, LG 3, XL 4, XXL 5.
    // Не от 992: у сделки с правками ряд помещается лишь примерно от 1060 px.
    assert.equal(HEADER_UP_MIN_SIZE, 4);
    assert.equal(headerUpAt(2), false, "768–991 — шапка в листе");
    assert.equal(headerUpAt(3), false, "992–1199 — шапка в листе");
    assert.equal(headerUpAt(4), true, "1200–1399");
    assert.equal(headerUpAt(5), true, "от 1400");
    assert.equal(headerUpAt(0), false);
    assert.equal(headerUpAt(undefined), false);
    assert.equal(headerUpAt(4, 5), false, "порог передаётся");
});

t("этап — поле без btn, остальное — кнопки (как compileHeader)", () => {
    assert.equal(isStatusNode("field", []), true);
    assert.equal(isStatusNode("FIELD", ""), true);
    assert.equal(isStatusNode("field", ["o_field", "btn"]), false, "поле-кнопка — к кнопкам");
    assert.equal(isStatusNode("field", "btn btn-link"), false);
    assert.equal(isStatusNode("button", []), false);
    assert.equal(isStatusNode("span", ["pmk-signal"]), false, "плашка расчёта — к кнопкам");
    assert.equal(isStatusNode("widget", []), false);
});

t("скрыто насовсем", () => {
    for (const v of ["1", "True", "true", " 1 "]) assert.equal(isAlwaysHidden(v), true, v);
    for (const v of [null, undefined, "", "0", "False", "type == 'lead'"]) {
        assert.equal(isAlwaysHidden(v), false, String(v));
    }
});

t("клавиша: Control на Mac, Alt на остальных", () => {
    assert.equal(hotkeyLabel("n", true), "Control+N");
    assert.equal(hotkeyLabel("n", false), "Alt+N");
    assert.equal(hotkeyLabel("s", false), "Alt+S");
    assert.equal(hotkeyLabel("J", true), "Control+J");
});

t("подсказка листалки — клавиша и «N из M»", () => {
    assert.equal(pagerTooltip(1, 1, 6, true), "Следующая — Control+N (2 из 6)");
    assert.equal(pagerTooltip(-1, 1, 6, false), "Предыдущая — Alt+P (2 из 6)");
    assert.equal(pagerTooltip(1, 0, 1, false), "Следующая — Alt+N (1 из 1)");
    assert.equal(pagerTooltip(-1, 0, 0, true), "Предыдущая — Control+P", "без записей — без счёта");
    assert.equal(pagerTooltip(1, 9, 3, false), "Следующая — Alt+N (3 из 3)", "за пределами — к краю");
});

t("короткое звено строки пути", () => {
    for (const name of ["СМ-00025", "ДОБ-00007", "ЛР-00012", "РК-00003", "СД-00001",
                        "СД-00001 от 27.09.2026", "Воронка", "Расчёты и КП"]) {
        assert.equal(isShortCrumb(name), true, name);
    }
    for (const name of ["Запрос стоимости изготовления МК п. Горный - СОФ тест",
                        "Калькулятор металлопроката", "СД-00001 от 27 сентября 2026 г.",
                        "", null, undefined]) {
        assert.equal(isShortCrumb(name), false, String(name));
    }
});

console.log(`\n${n} проверок пройдено`);
