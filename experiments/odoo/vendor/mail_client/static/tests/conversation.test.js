import { describe, expect, test } from "@odoo/hoot";

import {
    collapsedSnippet,
    conversationItems,
    conversationLayout,
    newestOf,
    normalizeSubject,
} from "@mail_client/panes/conversation";
import { pluralForm } from "@mail_client/utils";

describe.current.tags("headless");

// ПРАВКА ПМК (шаг 20): переписка под письмом — какие письма видны, какие
// свёрнуты в «ещё N», что показывает строка свёрнутого письма.
const msg = (id, day, extra = {}) => ({
    id,
    date: `2026-09-${String(day).padStart(2, "0")} 10:00:00`,
    flag_seen: true,
    ...extra,
});
const shape = (layout) =>
    layout
        .map((entry) =>
            entry.type === "more"
                ? `+${entry.count}`
                : entry.expanded
                  ? `[${entry.item.id}]`
                  : String(entry.item.id)
        )
        .join(" ");
const range = (count) => Array.from({ length: count }, (_, i) => msg(i + 1, i + 1));

describe("conversationLayout", () => {
    test("up to five letters are all visible, newest first", () => {
        expect(shape(conversationLayout(range(5), { expanded: [5] }))).toBe("[5] 4 3 2 1");
    });

    test("from six letters the middle folds into «more»", () => {
        const layout = conversationLayout(range(6), { expanded: [6] });
        expect(shape(layout)).toBe("[6] 5 +3 1");
        expect(layout[2].ids).toEqual([4, 3, 2]);
    });

    test("the opened letter in the middle splits «more» in two", () => {
        expect(shape(conversationLayout(range(10), { expanded: [10, 6] }))).toBe(
            "[10] 9 +2 [6] +4 1"
        );
    });

    test("unread letters are never hidden, a single hidden letter is shown", () => {
        expect(shape(conversationLayout(range(8), { expanded: [8], shown: [5] }))).toBe(
            "[8] 7 6 5 +3 1"
        );
    });

    test("never more than two «more» pieces", () => {
        expect(shape(conversationLayout(range(12), { expanded: [12], shown: [8, 4] }))).toBe(
            "[12] 11 +2 8 +3 4 3 2 1"
        );
    });

    test("same date: the higher id is newer; no date is the oldest", () => {
        const letters = [msg(3, 5), msg(7, 5), { id: 9, date: false }, msg(1, 1)];
        expect(conversationLayout(letters).map((entry) => entry.item.id)).toEqual([7, 3, 1, 9]);
        expect(newestOf(letters).id).toBe(7);
        expect(newestOf([])).toBe(null);
    });

    test("the opened letter is always in the list", () => {
        const detail = { id: 50, date: "2026-09-20 10:00:00", attachments: [{ id: 1 }] };
        const items = conversationItems(detail, [msg(1, 1)]);
        expect(items.map((item) => item.id)).toEqual([1, 50]);
        expect(items[1].has_attachment).toBe(true);
        const thread = [msg(1, 1), msg(50, 2)];
        expect(conversationItems({ id: 50 }, thread)).toBe(thread);
    });
});

describe("collapsed letter line", () => {
    test("subject without Re:/Fwd:/Ответ: prefixes", () => {
        expect(normalizeSubject("Re: RE: Fwd: Счёт  №5")).toBe("счёт №5");
        expect(normalizeSubject("Ответ: Fw[2]: Отв: x")).toBe("x");
        expect(normalizeSubject(undefined)).toBe("");
    });

    test("preview, else a different subject, else nothing", () => {
        expect(collapsedSnippet({ preview: " Добрый день ", subject: "Re: Счёт" }, "Счёт")).toBe(
            "Добрый день"
        );
        expect(collapsedSnippet({ preview: "", subject: "Re: Счёт" }, "RE: счёт")).toBe("");
        expect(collapsedSnippet({ preview: "", subject: "Новая тема" }, "Счёт")).toBe(
            "Новая тема"
        );
    });
});

describe("pluralForm", () => {
    test("Russian: one, few, other", () => {
        expect([1, 2, 5, 11, 21, 22, 112].map((n) => pluralForm(n, "ru-RU"))).toEqual([
            "one",
            "few",
            "other",
            "other",
            "one",
            "few",
            "other",
        ]);
    });

    test("English never picks «few»; an unknown language falls back", () => {
        expect([1, 2, 5].map((n) => pluralForm(n, "en-US"))).toEqual(["one", "other", "other"]);
        expect(pluralForm(3, "не-язык")).toBe("other");
    });
});
