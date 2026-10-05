// ПРАВКА ПМК — шаг 46 разбора удобства (06.10.2026): чертежи DXF в почте.
//
// Запуск из корня репозитория (нужен только node, без браузера и Odoo):
//   node experiments/odoo/vendor/mail_client/static/tests/step46_drawing.test.mjs
// Проверяется чистый модуль attachments/preview_payload.js: вид 'drawing'
// (чертёж пришёл — пробрасывается окну чертежа; не пришёл — отказ словами),
// строка архива с чертежом — «Посмотреть». Пути чертежа проверяет окно
// pmk_drawing (его тест — addons/pmk_drawing/static/tests). Файл .mjs
// сборщик ассетов Odoo не берёт.
import assert from "node:assert/strict";

const payload = await import(new URL("../src/attachments/preview_payload.js", import.meta.url).href);
const { KINDS, normalizeArchive, normalizePreview } = payload;

let n = 0;
function t(name, fn) {
    fn();
    n++;
    console.log("ok -", name);
}

const drawing = {
    ok: true,
    viewbox: [1_000_000, 500_000],
    layers: [{ name: "КОНТУР", color: "#ff0000", on: true }],
    palette: ["#ff0000"],
    items: [[0, 0, 0, "M 0 0 l 10 10"]],
};

t("чертёж пришёл — вид 'drawing', пути — окну чертежа как есть", () => {
    const preview = normalizePreview({
        kind: "drawing",
        name: "Кронштейн.dxf",
        format_title: "чертёж DXF",
        size: 2048,
        drawing,
    });
    assert.equal(preview.kind, KINDS.DRAWING);
    assert.equal(preview.drawing, drawing, "без копирования: до 150 000 путей");
    assert.equal(preview.formatTitle, "чертёж DXF");
    assert.equal(preview.reason, "");
});

t("чертёж не пришёл или с отказом — отказ словами, а не пустое окно", () => {
    const empty = normalizePreview({ kind: "drawing" });
    assert.equal(empty.kind, KINDS.NONE);
    assert.match(empty.reason, /не удалось показать/);
    const refused = normalizePreview({ kind: "drawing", drawing: { ok: false, reason: "Файл обрезан" } });
    assert.equal(refused.kind, KINDS.NONE);
    assert.equal(refused.reason, "Файл обрезан");
    const listed = normalizePreview({ kind: "drawing", drawing: [1, 2] });
    assert.equal(listed.kind, KINDS.NONE);
    assert.equal(normalizePreview({ kind: "drawing", reason: "занято", drawing: null }).reason, "занято");
});

t("у других видов поля чертежа нет", () => {
    assert.equal(normalizePreview({ kind: "pdf", url: "/x" }).drawing, null);
    assert.equal(normalizePreview({ kind: "drawing3d" }).kind, KINDS.NONE, "незнакомый вид — отказ");
});

t("строка архива с чертежом — «Посмотреть» и «Скачать»", () => {
    const archive = normalizeArchive({
        entries: [
            { index: 0, path: "Чертежи/Кронштейн.dxf", dir: "Чертежи/", name: "Кронштейн.dxf", size: 10, kind: "drawing" },
            { index: 1, path: "Сборка.dwg", dir: "", name: "Сборка.dwg", size: 10, kind: "other" },
        ],
        total: 2,
    });
    const [dwg, dxf] = [archive.entries[1], archive.entries[0]];
    assert.equal(dxf.kind, "drawing");
    assert.equal(dxf.canView, true);
    assert.equal(dxf.canDownload, true);
    assert.equal(dwg.canView, false, "DWG — не этот шаг");
});

console.log(`\n${n} проверок пройдено`);
