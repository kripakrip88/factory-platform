import { describe, expect, test } from "@odoo/hoot";

import { isAbove, mergeListHead, rowKey } from "@mail_client/panes/list_refresh";

describe.current.tags("headless");

// ПРАВКА ПМК (шаг 22): список после синхронизации — без сброса. Свежее
// начало списка сводится с тем, что на экране: что поставить целиком, что
// обновить на месте, сколько строк встанет над экраном.
const row = (id, minute, extra = {}) => ({
    id,
    date: `2026-09-30 10:${String(minute).padStart(2, "0")}:00`,
    flag_seen: true,
    ...extra,
});
const ids = (rows) => rows.map((r) => r.id);
const head = (messages, hasMore = false) => ({ messages, has_more: hasMore });

describe("mergeListHead", () => {
    test("nothing changed: same rows, no updates, nothing fresh", () => {
        const current = [row(3, 30), row(2, 20), row(1, 10)];
        const merge = mergeListHead(current, head([row(3, 30), row(2, 20), row(1, 10)]));
        expect(ids(merge.messages)).toEqual([3, 2, 1]);
        expect(merge.updates.length).toBe(0);
        expect(merge.fresh).toBe(0);
        expect(merge.structural).toBe(false);
    });

    test("a new letter goes on top, loaded pages stay", () => {
        // 4 rows loaded; the head is re-read with room to spare (a page more
        // than the screen) and taken down to the last row on screen.
        const current = [row(4, 40), row(3, 30), row(2, 20), row(1, 10)];
        const merge = mergeListHead(
            current,
            head([row(5, 50), row(4, 40), row(3, 30), row(2, 20), row(1, 10), row(0, 5)], true),
            { hasMore: true }
        );
        expect(ids(merge.messages)).toEqual([5, 4, 3, 2, 1]);
        expect(merge.fresh).toBe(1);
        expect(merge.structural).toBe(true);
        expect(merge.hasMore).toBe(true);
    });

    test("letters arriving at the bottom of the loaded range all show up", () => {
        // Two letters dated between the last two rows on screen (moved out of
        // Spam on mail.ru). The old tail kept only one of them, and «Load
        // more» asked for rows older than the bottom row — never for the other.
        const current = [row(9, 50), row(8, 40), row(1, 10)];
        const merge = mergeListHead(
            current,
            head([row(9, 50), row(8, 40), row(21, 30), row(20, 20), row(1, 10), row(0, 5)], true),
            { hasMore: true }
        );
        expect(ids(merge.messages)).toEqual([9, 8, 21, 20, 1]);
        expect(merge.fresh).toBe(0);
        expect(merge.hasMore).toBe(true);
    });

    test("a head that stops short of the screen's bottom cuts the list there", () => {
        // More new letters than the margin: rather than glue the old rows on
        // behind a gap, the list ends with the answer and «Load more» brings
        // the rest.
        const current = [row(3, 30), row(2, 20), row(1, 10)];
        const merge = mergeListHead(
            current,
            head([row(7, 57), row(6, 56), row(5, 55), row(4, 54), row(3, 30)], true),
            { hasMore: false }
        );
        expect(ids(merge.messages)).toEqual([7, 6, 5, 4, 3]);
        expect(merge.hasMore).toBe(true);
        expect(merge.fresh).toBe(4);
    });

    test("a fully loaded list stays fully loaded: no stray «Load more»", () => {
        // The request asks for more than the screen holds; nothing new — the
        // answer is shorter than asked and has_more is false.
        const current = [row(3, 30), row(2, 20), row(1, 10)];
        const merge = mergeListHead(current, head([row(3, 30), row(2, 20, { flag_seen: false }), row(1, 10)]));
        expect(merge.hasMore).toBe(false);
        expect(merge.structural).toBe(false);
        expect(merge.updates.length).toBe(1);
    });

    test("the margin does not load more rows by itself", () => {
        // One page on screen, the rest of the folder fits in the margin: the
        // answer is the whole folder, but the list keeps its length and
        // «Load more» stays.
        const current = [row(3, 30), row(2, 20)];
        const merge = mergeListHead(current, head([row(4, 40), row(3, 30), row(2, 20), row(1, 10)]), {
            hasMore: true,
        });
        expect(ids(merge.messages)).toEqual([4, 3, 2]);
        expect(merge.hasMore).toBe(true);
    });

    test("a head ending exactly on the bottom row keeps the old continuation", () => {
        // At the 200-row cap the server says has_more whenever it returns 200
        // rows; ending on our last row says nothing about what lies beyond.
        const current = [row(3, 30), row(2, 20), row(1, 10)];
        const answer = head([row(3, 30), row(2, 20), row(1, 10)], true);
        expect(mergeListHead(current, answer, { hasMore: false }).hasMore).toBe(false);
        expect(mergeListHead(current, answer, { hasMore: true }).hasMore).toBe(true);
    });

    test("the whole list fits: what is missing is gone", () => {
        const current = [row(3, 30), row(2, 20), row(1, 10)];
        const merge = mergeListHead(current, head([row(3, 30), row(1, 10)]), { hasMore: true });
        expect(ids(merge.messages)).toEqual([3, 1]);
        expect(merge.hasMore).toBe(false);
        expect(merge.fresh).toBe(0);
        expect(merge.structural).toBe(true);
    });

    test("a changed mark is an update in place", () => {
        const current = [row(2, 20, { flag_seen: false }), row(1, 10)];
        const merge = mergeListHead(current, head([row(2, 20), row(1, 10)]));
        expect(merge.updates.length).toBe(1);
        expect(merge.updates[0][0]).toBe(current[0]);
        expect(merge.updates[0][1].flag_seen).toBe(true);
        expect(merge.structural).toBe(false);
    });

    test("threaded: a reply moves the conversation up, keyed by thread", () => {
        const current = [
            row(3, 30, { thread_key: "B" }),
            row(2, 20, { thread_key: "A" }),
            row(1, 10, { thread_key: "C" }),
        ];
        // A got a reply (letter 9): its row is now letter 9, on top.
        const merge = mergeListHead(
            current,
            head([
                row(9, 50, { thread_key: "A", thread_count: 2 }),
                row(3, 30, { thread_key: "B" }),
                row(1, 10, { thread_key: "C" }),
            ]),
            { threaded: true, selectedIds: [2, 1] }
        );
        expect(ids(merge.messages)).toEqual([9, 3, 1]);
        expect(merge.fresh).toBe(1);
        expect(merge.selectedIds).toEqual([9, 1]);
    });

    test("a ticked row that is gone loses its tick", () => {
        const current = [row(2, 20), row(1, 10)];
        const merge = mergeListHead(current, head([row(2, 20)]), { selectedIds: [1, 2] });
        expect(merge.selectedIds).toEqual([2]);
    });

    test("rows newly matching further down are not counted as new letters", () => {
        // Filter «read»: letter 5 was read on mail.ru and now matches, but it
        // is older than the top row — it lands in the middle, not on top.
        const current = [row(9, 50), row(1, 10)];
        const merge = mergeListHead(current, head([row(9, 50), row(5, 30), row(1, 10)]));
        expect(merge.fresh).toBe(0);
        expect(merge.structural).toBe(true);
        expect(ids(merge.messages)).toEqual([9, 5, 1]);
    });

    test("an empty screen takes the head as is", () => {
        const merge = mergeListHead([], head([row(1, 10)], true));
        expect(ids(merge.messages)).toEqual([1]);
        expect(merge.hasMore).toBe(true);
        expect(merge.fresh).toBe(1);
    });
});

describe("row order and keys", () => {
    test("newer date first, then higher id", () => {
        expect(isAbove(row(1, 20), row(2, 10))).toBe(true);
        expect(isAbove(row(2, 10), row(1, 10))).toBe(true);
        expect(isAbove(row(1, 10), row(2, 10))).toBe(false);
    });

    test("a conversation is keyed by thread, a letter by id", () => {
        expect(rowKey({ id: 5, thread_key: "K" }, true)).toBe("t:K");
        expect(rowKey({ id: 5, thread_key: "K" }, false)).toBe("m:5");
        expect(rowKey({ id: 5 }, true)).toBe("m:5");
    });
});
