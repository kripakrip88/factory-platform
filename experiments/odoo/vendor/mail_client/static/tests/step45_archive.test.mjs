// ПРАВКА ПМК — шаг 45 разбора удобства (05.10.2026): просмотр архивов ZIP.
//
// Запуск из корня репозитория (нужен только node, без браузера и Odoo):
//   node experiments/odoo/vendor/mail_client/static/tests/step45_archive.test.mjs
// Проверяется чистый модуль attachments/preview_payload.js: разбор списка
// архива (группы по папкам, что можно посмотреть и скачать), адрес файла из
// архива, размер русскими единицами, ветка «архив» и файл из архива в
// normalizePreview, текст отказа «Скачать» у строки (downloadRefusal). Файл .mjs сборщик ассетов Odoo не берёт.
import assert from "node:assert/strict";

const payload = await import(new URL("../src/attachments/preview_payload.js", import.meta.url).href);
const { KINDS, downloadRefusal, formatBytes, memberUrl, normalizeArchive, normalizePreview } = payload;

let n = 0;
function t(name, fn) {
    fn();
    n++;
    console.log("ok -", name);
}

const entry = (index, path, extra = {}) => {
    const parts = path.split("/");
    return {
        index,
        path,
        dir: parts.slice(0, -1).join("/"),
        name: parts[parts.length - 1],
        size: 1000,
        date: "01.10.2026 12:30",
        kind: "pdf",
        reason: "",
        warn: "",
        ...extra,
    };
};

t("размер — русскими единицами, через запятую", () => {
    assert.equal(formatBytes(512), "512 Б");
    assert.equal(formatBytes(2048), "2,0 КБ");
    assert.equal(formatBytes(5.3 * 1024 * 1024), "5,3 МБ");
    assert.equal(formatBytes(3 * 1024 ** 3), "3,0 ГБ");
    assert.equal(formatBytes(0), "");
    assert.equal(formatBytes(undefined), "");
    assert.equal(formatBytes(-5), "");
});

t("адрес файла из архива — только из целых чисел", () => {
    assert.equal(memberUrl(7, 3), "/mail_client/attachment/7/member/3");
    assert.equal(memberUrl(7, 0, true), "/mail_client/attachment/7/member/0?download=1");
    for (const [id, index] of [[0, 1], [-1, 1], [7, -1], [7, 1.5], ["7", 1], [7, "1"], [7, null], [NaN, 1]]) {
        assert.equal(memberUrl(id, index), "", `${id}/${index}`);
    }
});

t("список: группы по папкам, корень первым, порядок строк сервера", () => {
    const archive = normalizeArchive({
        entries: [
            entry(4, "Чертежи/Узел 1/Лист 2.pdf"),
            entry(1, "Счёт.pdf"),
            entry(2, "Чертежи/Лист 10.pdf"),
            entry(3, "Чертежи/Лист 11.pdf"),
        ],
        total: 4,
        size: 4000,
        hidden: 2,
        notes: ["Показано файлов: 1000 из 1228.", "", null],
    });
    assert.deepEqual(archive.groups.map((group) => group.dir), ["", "Чертежи/Узел 1", "Чертежи"]);
    assert.equal(archive.groups[1].label, "Чертежи / Узел 1");
    assert.deepEqual(archive.groups[2].entries.map((item) => item.index), [2, 3]);
    assert.equal(archive.total, 4);
    assert.equal(archive.shown, 4);
    assert.equal(archive.hidden, 2);
    assert.deepEqual(archive.notes, ["Показано файлов: 1000 из 1228."]);
});

t("посмотреть — PDF, таблицу, картинку; скачать — всё, что не отказано", () => {
    const archive = normalizeArchive({
        entries: [
            entry(0, "a.pdf", { kind: "pdf" }),
            entry(1, "b.xlsx", { kind: "sheet" }),
            entry(2, "c.png", { kind: "image" }),
            entry(3, "d.zip", { kind: "archive" }),
            entry(4, "e.dwg", { kind: "other" }),
            entry(5, "f.pdf", { kind: "pdf", reason: "закрыт паролем" }),
            entry(6, "g.bin", { kind: "guess" }),
        ],
    });
    const view = Object.fromEntries(archive.entries.map((item) => [item.name, [item.canView, item.canDownload]]));
    assert.deepEqual(view, {
        "a.pdf": [true, true],
        "b.xlsx": [true, true],
        "c.png": [true, true],
        "d.zip": [false, true],
        "e.dwg": [false, true],
        "f.pdf": [false, false],
        "g.bin": [false, true],
    });
    assert.equal(archive.entries[6].kind, "other", "неизвестный вид — «прочее»");
});

t("строка без целого номера выбрасывается: открыть её нечем", () => {
    const archive = normalizeArchive({ entries: [entry("1", "a.pdf"), entry(-1, "b.pdf"), null, entry(2, "c.pdf")] });
    assert.deepEqual(archive.entries.map((item) => item.name), ["c.pdf"]);
    assert.equal(archive.total, 1, "total не меньше показанного");
});

t("ответ «архив»: список, а пустой — честный отказ", () => {
    const preview = normalizePreview({
        kind: "archive",
        name: "Заказ 45.zip",
        format_title: "архив ZIP",
        archive: { entries: [entry(0, "a.pdf")], total: 1 },
    });
    assert.equal(preview.kind, KINDS.ARCHIVE);
    assert.equal(preview.formatTitle, "архив ZIP");
    assert.equal(preview.archive.entries.length, 1);

    const empty = normalizePreview({ kind: "archive", archive: { entries: [], total: 0 } });
    assert.equal(empty.kind, KINDS.NONE);
    assert.equal(empty.reason, "В архиве нет ни одного файла.");
    const junk = normalizePreview({ kind: "archive", archive: { entries: [], hidden: 3 } });
    assert.equal(junk.reason, "В архиве только служебные файлы архиватора.");
    assert.equal(normalizePreview({ kind: "archive" }).kind, KINDS.NONE, "нет списка — отказ");
});

t("файл из архива: номер, имя архива, свой адрес скачивания", () => {
    const preview = normalizePreview({
        kind: "pdf",
        name: "Чертёж.pdf",
        url: "/mail_client/attachment/7/member/3",
        download_url: "/mail_client/attachment/7/member/3?download=1",
        member: { index: 3, path: "Чертежи/Чертёж.pdf" },
        archive_name: "Заказ 45.zip",
    });
    assert.deepEqual(preview.member, { index: 3, path: "Чертежи/Чертёж.pdf" });
    assert.equal(preview.archiveName, "Заказ 45.zip");
    assert.equal(preview.downloadUrl, "/mail_client/attachment/7/member/3?download=1");
    const foreign = normalizePreview({ kind: "pdf", url: "/x", download_url: "https://evil.example/x" });
    assert.equal(foreign.downloadUrl, "", "чужой адрес скачивания отброшен");
    assert.equal(normalizePreview({ kind: "pdf", url: "/x", member: { index: -1 } }).member, null);
});

t("«Скачать» у строки: отказ сервера — его словами, страница HTML — нет", () => {
    const crc = "Файл «a.csv» в архиве повреждён: контрольная сумма не сходится.";
    assert.equal(downloadRefusal(422, "text/plain; charset=utf-8", `${crc}\n`), crc);
    assert.equal(downloadRefusal(413, "Text/Plain", "  Файл «z.csv» распаковывается больше заявленного размера.  "),
        "Файл «z.csv» распаковывается больше заявленного размера.");
    const html = "<!doctype html><title>404 Not Found</title><h1>Not Found</h1>";
    assert.match(downloadRefusal(404, "text/html; charset=utf-8", html), /^Файл не найден/);
    assert.equal(downloadRefusal(500, "text/html", html), "Файл не скачался. Скачайте архив целиком.");
    assert.equal(downloadRefusal(502, null, ""), "Файл не скачался. Скачайте архив целиком.");
    assert.equal(downloadRefusal(422, "text/plain", "x".repeat(2000)).length, 500, "простыня обрезана");
});

t("прежние виды не задеты", () => {
    assert.equal(normalizePreview({ kind: "sheet", sheets: [{ rows: [["1"]] }] }).kind, KINDS.SHEET);
    assert.equal(normalizePreview({ kind: "guesswork" }).kind, KINDS.NONE);
    assert.equal(normalizePreview({ kind: "image", url: "/web/content/1" }).archive, null);
});

console.log(`\n${n} проверок — все прошли`);
