/* ПМК: разбор ответа сервера о вложении.
 *
 * Проверяется то, от чего зависит читаемость окна: ширина строк (иначе
 * разъедется закреплённая шапка), выравнивание числовых колонок, отказ от
 * чужого адреса и честное «просмотра нет» вместо пустого окна. Числа в
 * примерах взяты с живого прайса Металлсервиса: 711 строк на листе «Металл»,
 * из них в просмотр уходит первая сотня-другая.
 */
import { describe, expect, test } from "@odoo/hoot";

import {
    KINDS,
    appendSheetRows,
    columnAlignments,
    isNumericCell,
    normalizePreview,
    normalizePrice,
    safeUrl,
} from "@mail_client/attachments/preview_payload";

describe.current.tags("headless");

describe("normalizePreview", () => {
    test("pads ragged rows to one width", () => {
        // В xls у строки ровно столько ячеек, сколько заполнено. Рваный <tr>
        // ломает сетку таблицы, а вместе с ней и закреплённую шапку.
        const preview = normalizePreview({
            kind: "sheet",
            sheets: [{
                name: "Металл",
                columns: ["Профиль", "Размер, мм"],
                rows: [["Труба ВГП"], ["Уголок", "63 х 5", "Ст3сп", "6"]],
                total_rows: 711,
            }],
        });
        const sheet = preview.sheets[0];
        expect(sheet.rows.map((row) => row.length)).toEqual([4, 4]);
        expect(sheet.columns.length).toBe(4);
        expect(sheet.aligns.length).toBe(4);
    });

    test("marks a sheet that was cut short", () => {
        const preview = normalizePreview({
            kind: "sheet",
            sheets: [{ name: "Металл", rows: [["1"], ["2"]], total_rows: 711 }],
        });
        expect(preview.sheets[0].shownRows).toBe(2);
        expect(preview.sheets[0].totalRows).toBe(711);
        expect(preview.sheets[0].truncated).toBe(true);
    });

    test("never claims fewer rows than it was given", () => {
        // Потерянный total_rows не должен превратиться в «показано 2 из 0».
        const preview = normalizePreview({
            kind: "sheet",
            sheets: [{ name: "Сервис", rows: [["1"], ["2"]] }],
        });
        expect(preview.sheets[0].totalRows).toBe(2);
        expect(preview.sheets[0].truncated).toBe(false);
    });

    test("an empty table is not a table", () => {
        const preview = normalizePreview({ kind: "sheet", sheets: [] });
        expect(preview.kind).toBe(KINDS.NONE);
        expect(preview.reason).not.toBe("");
    });

    test("pdf and image keep the server's own path", () => {
        expect(normalizePreview({ kind: "pdf", url: "/web/content/1231" }).url)
            .toBe("/web/content/1231");
        expect(normalizePreview({ kind: "image", url: "/web/content/1189" }).kind)
            .toBe(KINDS.IMAGE);
    });

    test("a foreign address is dropped, and with it the preview", () => {
        // Иначе картинка из письма постороннего сама сходит на чужой сервер и
        // сообщит отправителю, что письмо открыли.
        const preview = normalizePreview({
            kind: "image",
            url: "https://tracker.example.com/pixel.gif",
        });
        expect(preview.url).toBe("");
        expect(preview.kind).toBe(KINDS.NONE);
    });

    test("rubbish from the server becomes an honest refusal", () => {
        for (const raw of [null, undefined, {}, { kind: "guesswork" }, { kind: "pdf" }]) {
            expect(normalizePreview(raw).kind).toBe(KINDS.NONE);
        }
    });

    test("keeps the number of the sheet in the workbook, not in the tab bar", () => {
        // Пустые листы в показ не попадают, и после этого «первая вкладка» и
        // «первый лист книги» — разные листы. Сервер спрашивают про лист
        // книги: спутать их значит показать сводку чужого листа.
        const preview = normalizePreview({
            kind: "sheet",
            sheets: [
                { index: 0, name: "Пустой", rows: [] },
                { index: 1, name: "Металл", rows: [["Труба"]] },
            ],
        });
        expect(preview.sheets.length).toBe(1);
        expect(preview.sheets[0].index).toBe(1);
    });
});

describe("normalizePrice", () => {
    test("reads the summary and orders the reasons by weight", () => {
        const price = normalizePrice({
            is_price: true, sheet: 0,
            rows_total: 627, matched: 421, unmatched: 206,
            by_status: {
                "совпало": 421,
                "вида нет в справочнике": 18,
                "размера нет в справочнике": 153,
            },
            unmatched_examples: [{ row: 32, text: "Труба эл/св 40 х 1,5", status: "размера нет" }],
        });
        expect(price.matchedPercent).toBe(67);
        // «Совпало» — не причина отказа, ему в списке причин не место.
        expect(price.byStatus.map((item) => item.status)).toEqual([
            "размера нет в справочнике",
            "вида нет в справочнике",
        ]);
        expect(price.unmatchedExamples[0].row).toBe(32);
    });

    test("a sheet that is not a price list gets no summary at all", () => {
        // Под каждым счётом «узнано 0 из 0» приучает не читать эту строку.
        expect(normalizePrice({ is_price: false, reason: "на прайс не похоже" })).toBe(null);
        expect(normalizePrice(null)).toBe(null);
    });

    test("a price list that could not be parsed keeps its summary", () => {
        // Молчание здесь человек прочтёт как ответ про прайс, хотя это
        // ответ про систему: справочник металла недоступен.
        const price = normalizePrice({ is_price: true, error: "Справочник металла пуст" });
        expect(price.error).toBe("Справочник металла пуст");
        expect(price.rowsTotal).toBe(0);
    });
});

describe("appendSheetRows", () => {
    test("a wider row from the second page widens the whole sheet", () => {
        // Ширина листа считается по самой длинной строке. Дописать строку на
        // 3 ячейки к листу на 2 — значит развалить сетку и вместе с ней
        // закреплённую шапку.
        const sheet = normalizePreview({
            kind: "sheet",
            sheets: [{ index: 0, name: "Металл", columns: ["Профиль", "Цена"],
                       rows: [["Труба", "82 290"]], total_rows: 4 }],
        }).sheets[0];
        const grown = appendSheetRows(sheet, {
            rows: [["Уголок", "74 100", "Ст3сп"]], total_rows: 4,
        });
        expect(grown.rows.map((row) => row.length)).toEqual([3, 3]);
        expect(grown.columns.length).toBe(3);
        expect(grown.shownRows).toBe(2);
        expect(grown.index).toBe(0);
    });

    test("an empty page means the end, whatever was promised", () => {
        const sheet = normalizePreview({
            kind: "sheet",
            sheets: [{ index: 0, name: "Металл", rows: [["Труба"]], total_rows: 900 }],
        }).sheets[0];
        expect(sheet.truncated).toBe(true);
        const ended = appendSheetRows(sheet, { rows: [], total_rows: 900 });
        expect(ended.truncated).toBe(false);
        expect(ended.totalRows).toBe(1);
    });
});

describe("safeUrl", () => {
    test("keeps a path on our own server and nothing else", () => {
        expect(safeUrl("/web/content/7")).toBe("/web/content/7");
        expect(safeUrl("//tracker.example.com/pixel.gif")).toBe("");
        expect(safeUrl("https://tracker.example.com/pixel.gif")).toBe("");
        expect(safeUrl("")).toBe("");
    });
});

describe("isNumericCell", () => {
    test("reads a price the way a person does", () => {
        // 82 290 приходит из xls с неразрывным пробелом между разрядами.
        expect(isNumericCell("82 290")).toBe(true);
        expect(isNumericCell("600,717")).toBe(true);
        expect(isNumericCell("-3")).toBe(true);
        expect(isNumericCell("12%")).toBe(true);
    });

    test("does not mistake a size or a steel grade for a number", () => {
        expect(isNumericCell("15 х 2.5")).toBe(false);
        expect(isNumericCell("Ст3сп\\пс")).toBe(false);
        expect(isNumericCell("по запросу")).toBe(false);
        expect(isNumericCell("")).toBe(false);
    });
});

describe("columnAlignments", () => {
    test("one odd cell does not turn a price column into text", () => {
        const rows = [
            ["Труба ВГП", "82 290"],
            ["Уголок", "по запросу"],
            ["Швеллер", "74 100"],
            ["Балка", "91 500"],
        ];
        expect(columnAlignments(rows, 2)).toEqual(["text", "num"]);
    });

    test("an empty column stays text rather than guessing", () => {
        expect(columnAlignments([["", ""], ["", ""]], 2)).toEqual(["text", "text"]);
    });
});
