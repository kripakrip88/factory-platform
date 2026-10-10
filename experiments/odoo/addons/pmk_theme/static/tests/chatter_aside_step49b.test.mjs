// Шаг 49Б разбора UX: лента справа от листа на широком экране — правила без Odoo.
//
// Запуск из корня репозитория (нужен только node, без браузера и Odoo):
//   node experiments/odoo/addons/pmk_theme/static/tests/chatter_aside_step49b.test.mjs
// Проверяется модуль ../src/js/chatter_aside_rules.js (чистые функции без
// импортов Odoo). Другой файл — переменная PMK_RULES. Файл не попадает ни в
// один бандл: ассеты в манифесте pmk_theme перечислены поимённо.
import assert from "node:assert/strict";

const RULES = process.env.PMK_RULES
    || new URL("../src/js/chatter_aside_rules.js", import.meta.url).href;
const {
    ASIDE_MIN_WIDTH,
    ASIDE_MEDIA,
    isWideViewport,
    chatterLayout,
    collapsedNow,
    shouldApplyOnWidth,
} = await import(RULES);

let n = 0;
function t(name, fn) { fn(); n++; console.log("ok -", name); }

t("порог — 2200 px, медиазапрос с ним совпадает", () => {
    // = $pmk-aside-from в forms_nexus.scss, раздел «Шаг 49Б» (сверяет и
    // тест Odoo test_step49b_aside.py).
    assert.equal(ASIDE_MIN_WIDTH, 2200);
    assert.equal(ASIDE_MEDIA, "(min-width: 2200px)");
});

t("широкое окно — от порога включительно", () => {
    assert.equal(isWideViewport(1920), false, "монитор 1920 — как было");
    assert.equal(isWideViewport(2199), false);
    assert.equal(isWideViewport(2200), true);
    assert.equal(isWideViewport(2560), true, "экран Антона");
    assert.equal(isWideViewport(2048), false, "2560 при масштабе Windows 125 %");
    assert.equal(isWideViewport(undefined), false);
    assert.equal(isWideViewport(NaN), false);
    assert.equal(isWideViewport("2560"), false, "не число — не широкое");
    assert.equal(isWideViewport(2560, Infinity), false, "выключатель «не понравилось»");
});

t("сбоку — только на широком окне", () => {
    assert.equal(chatterLayout("SIDE_CHATTER", false), "BOTTOM_CHATTER");
    assert.equal(chatterLayout("SIDE_CHATTER", true), "SIDE_CHATTER");
});

t("остальные раскладки ядра — без изменений", () => {
    for (const layout of ["COMBO", "EXTERNAL_COMBO_XXL", "EXTERNAL_COMBO", "BOTTOM_CHATTER", "NONE"]) {
        for (const wide of [false, true]) {
            assert.equal(chatterLayout(layout, wide), layout, `${layout}, wide=${wide}`);
        }
    }
});

t("сбоку история всегда развёрнута, под листом — по выбору", () => {
    assert.equal(collapsedNow(true, true), false);
    assert.equal(collapsedNow(true, false), true);
    assert.equal(collapsedNow(false, true), false);
    assert.equal(collapsedNow(false, false), false);
    assert.equal(collapsedNow(undefined, false), false);
});

t("смена порога: пересчёт сразу — только когда окно стало широким", () => {
    // При сужении рендерер ядра перекладывает ленту вниз через 200 мс, а
    // @media гаснет сразу: свёрнутая лента стояла бы справа пустой полосой.
    assert.equal(shouldApplyOnWidth(true), true);
    assert.equal(shouldApplyOnWidth(false), false);
    assert.equal(shouldApplyOnWidth(undefined), false);
});

console.log(`${n} проверок пройдено`);
