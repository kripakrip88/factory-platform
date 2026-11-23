import { describe, expect, test } from "@odoo/hoot";

import { conversationItems, newestOf } from "@mail_client/panes/conversation";
import { pluralForm } from "@mail_client/utils";

describe.current.tags("headless");

const msg = (id, day) => ({
    id,
    date: `2026-09-${String(day).padStart(2, "0")} 10:00:00`,
});

describe("conversationItems", () => {
    test("a long thread shows every message, oldest first", () => {
        const letters = Array.from({ length: 12 }, (_, i) => msg(i + 1, i + 1)).reverse();
        const cards = conversationItems(letters[5], letters);
        expect(cards.map((item) => item.id)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
        expect(letters[0].id).toBe(12);
    });

    test("includes the selected message when absent from the thread", () => {
        const selected = msg(50, 2);
        expect(conversationItems(selected, [msg(1, 1), msg(2, 3)])).toEqual([
            msg(1, 1), selected, msg(2, 3),
        ]);
        expect(conversationItems(selected, [])).toEqual([selected]);
    });

    test("same date: the higher id is newer; no date is the oldest", () => {
        const letters = [msg(3, 5), msg(7, 5), { id: 9, date: false }, msg(1, 1)];
        expect(conversationItems(letters[0], letters).map((item) => item.id)).toEqual([9, 1, 3, 7]);
        expect(newestOf(letters).id).toBe(7);
        expect(newestOf([])).toBe(null);
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
