import { describe, expect, mockDate, test } from "@odoo/hoot";
import { allowTranslations } from "@web/../tests/web_test_helpers";

import { formatMessageDate, formatSize, senderName } from "@mail_client/utils";

describe.current.tags("headless");

describe("senderName", () => {
    test("keeps the display name and drops the address", () => {
        expect(senderName('"Budi Santoso" <budi@example.co.id>')).toBe("Budi Santoso");
        expect(senderName("Budi Santoso <budi@example.co.id>")).toBe("Budi Santoso");
    });

    test("falls back to the address when there is no display name", () => {
        expect(senderName("budi@example.co.id")).toBe("budi@example.co.id");
        expect(senderName("<budi@example.co.id>")).toBe("<budi@example.co.id>");
    });

    test("survives a missing sender", () => {
        // Real mailboxes contain messages with no From at all; the list must
        // still render rather than throwing on every row. The fallback goes
        // through _t(), which refuses to resolve until translations exist.
        allowTranslations();
        expect(String(senderName(""))).toBe("(unknown sender)");
        expect(String(senderName(undefined))).toBe("(unknown sender)");
    });
});

describe("formatSize", () => {
    test("scales to a readable unit", () => {
        expect(formatSize(512)).toBe("512 B");
        expect(formatSize(2048)).toBe("2.0 KB");
        expect(formatSize(5 * 1024 * 1024)).toBe("5.0 MB");
    });

    test("shows nothing for an unknown size", () => {
        expect(formatSize(0)).toBe("");
        expect(formatSize(undefined)).toBe("");
    });
});

describe("formatMessageDate", () => {
    test("returns an empty string for missing or broken input", () => {
        expect(formatMessageDate(null)).toBe("");
        expect(formatMessageDate("")).toBe("");
        expect(formatMessageDate("not a date")).toBe("");
    });

    test("shows only the time for a message from today", () => {
        // Both the clock and the zone are pinned: without that this asserts
        // something different every day, and passes for the wrong reason.
        mockDate("2026-08-12 15:00:00", +7);
        // Server format (UTC), which is what the RPC payloads carry.
        expect(formatMessageDate("2026-08-12 03:05:00")).toBe("10:05");
    });

    test("shows the weekday for a message from the last week", () => {
        mockDate("2026-08-14 15:00:00", +7);
        expect(formatMessageDate("2026-08-12 03:05:00")).toBe("Wed 10:05");
    });
});
