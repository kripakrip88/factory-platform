// ПМК — шаг 46 разбора удобства (06.10.2026): окно чертежа DXF.
//
// Запуск из корня репозитория (нужен только node, без браузера и Odoo):
//   node experiments/odoo/addons/pmk_drawing/static/tests/dxf_view_math.test.mjs
// Проверяется чистый модуль static/src/js/dxf_view_math.js: «Вписать»,
// масштаб с неподвижной точкой под курсором и его пределы, сдвиг, смена
// размера окна, колесо мыши, цвета на белом листе (ACI 2 жёлтый, 4 голубой,
// 3 зелёный, белый, серый), подписи габарита и единиц, проверка ответа
// сервера (normalizeDrawing). Файл .mjs сборщик ассетов Odoo не берёт.
import assert from "node:assert/strict";

const math = await import(new URL("../src/js/dxf_view_math.js", import.meta.url).href);
const {
    MAX_ZOOM,
    MIN_CONTRAST,
    MIN_ZOOM,
    clampView,
    contrastOnWhite,
    fitView,
    formatMm,
    isDxfFile,
    layersBox,
    normalizeDrawing,
    panBy,
    pinchPoint,
    pinchView,
    resizeView,
    sheetColor,
    sizeLabel,
    unitsLabel,
    viewBoxString,
    wheelFactor,
    zoomAt,
    zoomLabel,
    zoomPercent,
} = math;

let n = 0;
function t(name, fn) {
    fn();
    n++;
    console.log("ok -", name);
}
const near = (actual, expected, eps = 1e-6) =>
    assert.ok(Math.abs(actual - expected) <= eps, `${actual} ≠ ${expected}`);

const canvas = { w: 1000, h: 500 };
const content = { w: 1_000_000, h: 457_600 };

t("файл DXF — по имени и по типу", () => {
    assert.equal(isDxfFile("Кронштейн.DXF", "application/octet-stream"), true);
    assert.equal(isDxfFile(" деталь.dxf ", ""), true);
    assert.equal(isDxfFile("scan.pdf", "image/vnd.dxf"), true);
    assert.equal(isDxfFile("scan.pdf", "application/pdf"), false);
    assert.equal(isDxfFile("dxf", ""), false);
    assert.equal(isDxfFile(null, null), false);
});

t("«Вписать»: весь чертёж в окне с полями, пропорции окна", () => {
    const fit = fitView(content, canvas);
    near(fit.w / fit.h, canvas.w / canvas.h);
    assert.ok(fit.w >= content.w && fit.h >= content.h);
    // Центр чертежа — в центре окна.
    near(fit.x + fit.w / 2, content.w / 2);
    near(fit.y + fit.h / 2, content.h / 2);
    // Узкий высокий чертёж упирается в высоту.
    const tall = fitView({ w: 100_000, h: 1_000_000 }, canvas);
    assert.ok(tall.h >= 1_000_000 && tall.h < 1_100_000);
    // Пустой холст и линия без высоты не дают деления на ноль.
    const flat = fitView({ w: 1_000_000, h: 0 }, { w: 0, h: 0 });
    assert.ok(Number.isFinite(flat.w) && flat.w > 0);
});

t("«Вписать» рамку не от нуля: центр рамки — в центре окна", () => {
    const fit = fitView({ x: 2_000_000, y: -500_000, w: 1000, h: 500 }, canvas);
    near(fit.x + fit.w / 2, 2_000_500);
    near(fit.y + fit.h / 2, -499_750);
    assert.ok(fit.w >= 1000 && fit.w < 1100);
});

t("вписываются слои с галочкой: выключенный далеко в стороне не мешает", () => {
    const layers = [
        { id: 0, box: { x0: 0, y0: 0, x1: 1_000_000, y1: 600_000 } },
        { id: 1, box: { x0: 200_000_000, y0: -199_400_000, x1: 200_020_000, y1: -199_400_000 } },
        { id: 2, box: null },
    ];
    assert.deepEqual(layersBox(layers, { 0: true, 1: false, 2: true }), {
        x: 0,
        y: 0,
        w: 1_000_000,
        h: 600_000,
    });
    const both = layersBox(layers, { 0: true, 1: true });
    assert.deepEqual(both, { x: 0, y: -199_400_000, w: 200_020_000, h: 200_000_000 });
    assert.equal(layersBox(layers, { 0: false, 1: false, 2: true }), null, "нет рамок — весь лист");
    assert.equal(layersBox([], {}), null);
});

t("щипок: точка под серединой пальцев стоит на месте, чертёж едет за ними", () => {
    const fit = fitView(content, canvas);
    const before = pinchPoint({ x: 400, y: 200 }, { x: 600, y: 300 });
    assert.deepEqual(before, { x: 500, y: 250, d: Math.hypot(200, 100) });
    const under = { x: fit.x + (before.x / canvas.w) * fit.w, y: fit.y + (before.y / canvas.h) * fit.h };
    // Развели вдвое и сдвинули середину на (+50, −30).
    const after = pinchPoint({ x: 350, y: 120 }, { x: 750, y: 320 });
    const view = pinchView(fit, before, after, canvas, fit);
    near(fit.w / view.w, after.d / before.d, 1e-9);
    near(view.x + (after.x / canvas.w) * view.w, under.x, 1e-6);
    near(view.y + (after.y / canvas.h) * view.h, under.y, 1e-6);
    // Пальцы не разошлись — только сдвиг; совпали в точку — без деления на ноль.
    const moved = pinchView(fit, before, { ...before, x: 510 }, canvas, fit);
    near(moved.w, fit.w);
    const dot = pinchView(fit, { x: 1, y: 1, d: 0 }, { x: 1, y: 1, d: 0 }, canvas, fit);
    assert.ok(Number.isFinite(dot.w) && dot.w === fit.w);
    // Пределы — те же, что у колеса.
    const huge = pinchView(fit, { x: 500, y: 250, d: 1 }, { x: 500, y: 250, d: 1e9 }, canvas, fit);
    near(fit.w / huge.w, MAX_ZOOM, 1e-6);
});

t("масштаб колесом: точка под курсором стоит на месте", () => {
    const fit = fitView(content, canvas);
    const px = 730;
    const py = 120;
    const before = { x: fit.x + (px / canvas.w) * fit.w, y: fit.y + (py / canvas.h) * fit.h };
    const view = zoomAt(fit, 2, px, py, canvas, fit);
    near(view.w, fit.w / 2);
    const after = { x: view.x + (px / canvas.w) * view.w, y: view.y + (py / canvas.h) * view.h };
    near(after.x, before.x, 1e-6);
    near(after.y, before.y, 1e-6);
    assert.equal(zoomPercent(view, fit), 200);
});

t("пределы масштаба: не дальше 10 % и не крупнее MAX_ZOOM", () => {
    const fit = fitView(content, canvas);
    let view = fit;
    for (let i = 0; i < 100; i++) {
        view = zoomAt(view, 2, 500, 250, canvas, fit);
    }
    near(fit.w / view.w, MAX_ZOOM, 1e-6);
    for (let i = 0; i < 200; i++) {
        view = zoomAt(view, 0.5, 500, 250, canvas, fit);
    }
    near(fit.w / view.w, MIN_ZOOM, 1e-9);
    assert.equal(zoomLabel(zoomPercent(zoomAt(fit, MAX_ZOOM, 0, 0, canvas, fit), fit)), "500 000 %");
});

t("сдвиг: чертёж едет за рукой, но с глаз не уходит", () => {
    const fit = fitView(content, canvas);
    const view = zoomAt(fit, 4, 500, 250, canvas, fit);
    const moved = panBy(view, 100, -50, canvas);
    near(moved.x, view.x - 100 * (view.w / canvas.w));
    near(moved.y, view.y + 50 * (view.h / canvas.h));
    const far = clampView(panBy(view, -1e9, -1e9, canvas), fit);
    near(far.x + far.w / 2, fit.x + fit.w, 1e-6);
    near(far.y + far.h / 2, fit.y + fit.h, 1e-6);
});

t("окно поменяло размер: тот же центр и тот же масштаб", () => {
    const fit = fitView(content, canvas);
    const view = zoomAt(fit, 3, 200, 100, canvas, fit);
    const wide = { w: 1600, h: 500 };
    const next = resizeView(view, canvas, wide);
    near(next.w / wide.w, view.w / canvas.w);
    near(next.x + next.w / 2, view.x + view.w / 2);
    near(next.h / wide.h, view.h / canvas.h);
});

t("колесо: щелчок мыши ×1,16, сенсорная панель мельче, рывок не больше ×2", () => {
    near(wheelFactor(-100, 0), Math.exp(0.15), 1e-9);
    assert.ok(wheelFactor(100, 0) < 1);
    assert.ok(wheelFactor(-3, 1) > wheelFactor(-4, 0));
    assert.equal(wheelFactor(-100000, 0), 2);
    assert.equal(wheelFactor(100000, 0), 0.5);
    assert.equal(wheelFactor(Number.NaN, 0), 1);
});

t("viewBox — без длинных хвостов", () => {
    assert.equal(viewBoxString({ x: 1 / 3, y: -2, w: 1000.126, h: 5 }), "0.33 -2 1000.13 5");
});

t("цвета на белом листе: читаемые — как в файле, светлые — темнее того же оттенка", () => {
    assert.equal(sheetColor("#FF0000"), "#ff0000", "красный читается");
    assert.equal(sheetColor("#0000ff"), "#0000ff");
    assert.equal(sheetColor("#ff00ff"), "#ff00ff", "пурпурный читается");
    assert.equal(sheetColor("#808080"), "#808080", "серый ACI 8 — как в файле");
    assert.equal(sheetColor("#000000"), "#000000");
    assert.equal(sheetColor("#ffffff"), "#000000", "белый AutoCAD — цвет переднего плана");
    assert.equal(sheetColor("#f0f0f0"), "#000000");
    for (const light of ["#ffff00", "#00ffff", "#00ff00", "#c0c0c0", "#33acca", "#ff7f7f"]) {
        const dark = sheetColor(light);
        assert.ok(contrastOnWhite(dark) >= MIN_CONTRAST, `${light} -> ${dark}`);
        assert.ok(contrastOnWhite(dark) < MIN_CONTRAST + 0.6, `${light} -> ${dark}: не чернее нужного`);
    }
    // Жёлтый остаётся жёлтым по оттенку (оливковым), а не чёрным.
    const yellow = sheetColor("#ffff00");
    assert.equal(yellow.slice(1, 3), yellow.slice(3, 5));
    assert.equal(yellow.slice(5, 7), "00");
    assert.equal(sheetColor("красный"), "#000000", "мусор — чёрным");
});

t("подписи: габарит и единицы по-русски", () => {
    assert.equal(formatMm(3455.365), "3455");
    assert.equal(formatMm(12.5), "12,5");
    assert.equal(formatMm(0.25), "0,25");
    assert.equal(formatMm(20), "20");
    assert.equal(formatMm(150000), "150 000");
    assert.equal(sizeLabel(3455.365, 1581.12), "3455 × 1581 мм");
    assert.equal(sizeLabel(500, 0), "500 × 0 мм");
    assert.equal(unitsLabel({ code: 4, label: "мм", assumed: false }), "единицы: мм");
    assert.equal(unitsLabel({ code: 0, label: "не заданы", assumed: true }), "единицы не заданы — считаем мм");
    assert.equal(unitsLabel(null), "");
});

const raw = () => ({
    ok: true,
    version: 1,
    viewbox: [1_000_000, 457_600],
    layers: [
        { name: "Размеры", color: "#00ff00", on: true, box: [10, 20, 300, 400] },
        { name: "0", color: "#000000", on: true, box: [0, 0, 1_000_000, "x"] },
        { name: "Скрытый", color: "#0000ff", on: false, box: [5, 5, 1, 1] },
        { name: "Пустой", color: "#ff0000", on: true },
        { name: "10", color: "#ffff00", on: true },
        { name: "2", color: "#ffffff", on: true },
    ],
    palette: ["#000000", "#00ff00", "#ffff00"],
    items: [
        [1, 0, 0, "M 0 0 l 100 0"],
        [0, 1, 1, "M 10 10 c 1 2 3 4 5 6 Z"],
        [2, 2, 0, "M 1e3 2.5E2 L -5 +6"],
        [4, 0, 2, "M 0 0 l 1 1"],
        [5, 0, 0, "M 0 0 l 2 2"],
    ],
    size_mm: [3455.365, 1581.12],
    units: { code: 4, label: "мм", assumed: false },
    layout: "Model",
    notes: ["Кодировка текста в файле указана неверно — прочитали как русскую (cp1251)."],
});

t("ответ сервера: слои по имени, пустые слои не в списке, цвета на белом", () => {
    const drawing = normalizeDrawing(raw());
    assert.equal(drawing.ok, true);
    assert.deepEqual(
        drawing.layers.map((layer) => layer.name),
        ["0", "2", "10", "Размеры", "Скрытый"],
        "как в АвтоКАДе: числа по значению, слой без путей не показан"
    );
    const byName = Object.fromEntries(drawing.layers.map((layer) => [layer.name, layer]));
    assert.equal(byName["Скрытый"].on, false);
    assert.equal(byName["Размеры"].fileColor, "#00ff00");
    assert.ok(contrastOnWhite(byName["Размеры"].color) >= MIN_CONTRAST);
    assert.equal(byName["2"].color, "#000000", "белый слой — чёрный образец");
    assert.equal(drawing.items.length, 5);
    assert.equal(drawing.items[3].color, sheetColor("#ffff00"));
    assert.equal(drawing.sizeLabel, "3455 × 1581 мм");
    assert.equal(drawing.unitsLabel, "единицы: мм");
    assert.equal(drawing.width, 1_000_000);
    assert.equal(drawing.notes.length, 1);
    assert.equal(drawing.dropped, 0);
    assert.deepEqual(byName["Размеры"].box, { x0: 10, y0: 20, x1: 300, y1: 400 });
    assert.equal(byName["0"].box, null, "не число — рамки нет");
    assert.equal(byName["Скрытый"].box, null, "вывернутая рамка — нет");
    assert.equal(byName["2"].box, null, "старый ответ без рамок");
});

t("ответ сервера: негодные пути выброшены и посчитаны", () => {
    const bad = raw();
    bad.items.push(
        [0, 0, 0, '<script>alert(1)</script>'],
        [0, 0, 0, "M 0 0 l 1 1 \" onload=\"x"],
        [99, 0, 0, "M 0 0"],
        [0, 7, 0, "M 0 0"],
        [0, 0, 99, "M 0 0"],
        [0, 0, 0, ""],
        [0, 0, 0],
        "M 0 0",
        [0.5, 0, 0, "M 0 0"]
    );
    bad.palette.push("url(javascript:1)");
    const drawing = normalizeDrawing(bad);
    assert.equal(drawing.items.length, 5);
    assert.equal(drawing.dropped, 9);
    assert.match(drawing.notes.at(-1), /Не показано путей с ошибками: 9/);
    assert.ok(drawing.items.every((item) => /^#[0-9a-f]{6}$/.test(item.color)));
});

t("ответ сервера: отказ и пустота — словами", () => {
    assert.deepEqual(normalizeDrawing({ ok: false, reason: "Файл повреждён" }), {
        ok: false,
        reason: "Файл повреждён",
    });
    assert.equal(normalizeDrawing(null).ok, false);
    assert.match(normalizeDrawing({ ok: false }).reason, /не удалось показать/);
    assert.match(normalizeDrawing({ ...raw(), viewbox: [0, 10] }).reason, /без размеров/);
    assert.match(normalizeDrawing({ ...raw(), items: [] }).reason, /нет ни одной линии/);
    const noSize = normalizeDrawing({ ...raw(), size_mm: null, units: null });
    assert.equal(noSize.sizeLabel, "");
    assert.equal(noSize.unitsLabel, "");
});

console.log(`\n${n} проверок пройдено`);
