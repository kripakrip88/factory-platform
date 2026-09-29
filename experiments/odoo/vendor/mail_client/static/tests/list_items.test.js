import { describe, expect, test } from "@odoo/hoot";

import { buildListItems } from "@mail_client/panes/list_items";

describe.current.tags("headless");

// ПРАВКА ПМК (шаг 18): из чего состоит список — строки, группы по дням,
// строки рассылок. Группу даёт bucketOf: здесь — по дню даты, чтобы тест не
// зависел от часов и зоны (сами границы суток проверяет utils.test.js).
const bucketOf = (date) =>
    ({ "2026-09-30": "today", "2026-09-29": "yesterday" })[(date || "").slice(0, 10)] ||
    "earlier";
const row = (id, date) => ({ id, date });
const shape = (items) =>
    items.map((item) =>
        item.type === "group"
            ? `[${item.bucket}]`
            : item.type === "digest"
              ? `digest:${item.digest.folder_id}`
              : `row:${item.message.id}`
    );

describe("buildListItems", () => {
    test("a heading before the first row of each day", () => {
        const items = buildListItems(
            [
                row(1, "2026-09-30 09:00:00"),
                row(2, "2026-09-30 01:00:00"),
                row(3, "2026-09-29 12:00:00"),
                row(4, "2026-09-20 12:00:00"),
                row(5, "2026-09-01 12:00:00"),
            ],
            [],
            { bucketOf }
        );
        expect(shape(items)).toEqual([
            "[today]",
            "row:1",
            "row:2",
            "[yesterday]",
            "row:3",
            "[earlier]",
            "row:4",
            "row:5",
        ]);
        const keys = items.map((item) => item.key);
        expect(new Set(keys).size).toBe(keys.length);
    });

    test("no heading for an empty day", () => {
        const items = buildListItems([row(1, "2026-09-20 12:00:00")], [], { bucketOf });
        expect(shape(items)).toEqual(["[earlier]", "row:1"]);
        expect(buildListItems([], [], { bucketOf })).toEqual([]);
    });

    test("a digest takes the place of its latest message", () => {
        const items = buildListItems(
            [row(1, "2026-09-30 09:00:00"), row(2, "2026-09-29 12:00:00")],
            [
                { folder_id: 24, date: "2026-09-29 18:00:00", senders: [] },
                { folder_id: 26, date: "2026-09-30 10:00:00", senders: [] },
            ],
            { bucketOf }
        );
        expect(shape(items)).toEqual([
            "[today]",
            "digest:26",
            "row:1",
            "[yesterday]",
            "digest:24",
            "row:2",
        ]);
    });

    test("an older digest waits for Load more", () => {
        const messages = [row(1, "2026-09-30 09:00:00")];
        const digests = [{ folder_id: 26, date: "2026-09-25 10:00:00", senders: [] }];
        expect(shape(buildListItems(messages, digests, { hasMore: true, bucketOf }))).toEqual([
            "[today]",
            "row:1",
        ]);
        expect(shape(buildListItems(messages, digests, { hasMore: false, bucketOf }))).toEqual([
            "[today]",
            "row:1",
            "[earlier]",
            "digest:26",
        ]);
    });

    test("rows without a date repeat a heading with a distinct key", () => {
        const items = buildListItems(
            [row(1, "2026-09-30 09:00:00"), row(2, false), row(3, "2026-09-30 08:00:00")],
            [],
            { bucketOf }
        );
        expect(shape(items)).toEqual([
            "[today]",
            "row:1",
            "[earlier]",
            "row:2",
            "[today]",
            "row:3",
        ]);
        const keys = items.map((item) => item.key);
        expect(new Set(keys).size).toBe(keys.length);
    });
});
