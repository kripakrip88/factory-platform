import { describe, expect, mockDate, test } from "@odoo/hoot";
import { allowTranslations, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";

import {
    dayBucket,
    formatMessageDate,
    formatSize,
    readPref,
    recipientLabel,
    senderName,
    splitAddress,
    splitRecipients,
    writePref,
} from "@mail_client/utils";

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

// ПРАВКА ПМК: строка «От» над письмом (шаг 17) — имя и адрес по частям.
describe("splitAddress", () => {
    test("splits the display name from the address", () => {
        expect(splitAddress('"Budi Santoso" <budi@example.co.id>')).toEqual({
            name: "Budi Santoso",
            address: "budi@example.co.id",
        });
        expect(splitAddress("Budi Santoso <budi@example.co.id>")).toEqual({
            name: "Budi Santoso",
            address: "budi@example.co.id",
        });
    });

    test("a bare address has no name", () => {
        expect(splitAddress("budi@example.co.id")).toEqual({
            name: "",
            address: "budi@example.co.id",
        });
        expect(splitAddress("<budi@example.co.id>")).toEqual({
            name: "",
            address: "budi@example.co.id",
        });
    });

    test("a name that repeats the address is not shown twice", () => {
        expect(splitAddress('"budi@example.co.id" <budi@example.co.id>')).toEqual({
            name: "",
            address: "budi@example.co.id",
        });
    });

    test("survives a missing sender", () => {
        expect(splitAddress("")).toEqual({ name: "", address: "" });
        expect(splitAddress(undefined)).toEqual({ name: "", address: "" });
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

// ПРАВКА ПМК (шаг 18): «Кому: …» в строке нашего письма.
describe("recipientLabel", () => {
    test("the first name, and how many more", () => {
        expect(recipientLabel("Client <client@firm.ru>")).toBe("Client");
        expect(recipientLabel("client@firm.ru")).toBe("client@firm.ru");
        expect(recipientLabel("Кирилл Данилов <megafuga@gmail.com>, granitsa.sk@mail.ru")).toBe(
            "Кирилл Данилов +1"
        );
        expect(recipientLabel("a@x.ru, b@x.ru; c@x.ru")).toBe("a@x.ru +2");
    });

    test("a comma inside the name does not split the recipient", () => {
        // Заголовок приходит без кавычек: это один адресат.
        const to = "Зимихина Наталья, АО Хабаровск Автомост <habavtpto@mail.ru>";
        expect(splitRecipients(to)).toEqual([to]);
        expect(recipientLabel(to)).toBe("Зимихина Наталья, АО Хабаровск Автомост");
        expect(splitRecipients('"Doe, John" <j@x.ru>, k@x.ru')).toEqual([
            '"Doe, John" <j@x.ru>',
            "k@x.ru",
        ]);
    });

    test("no recipient", () => {
        allowTranslations();
        expect(String(recipientLabel(""))).toBe("(no recipient)");
        expect(String(recipientLabel(undefined))).toBe("(no recipient)");
    });
});

// ПРАВКА ПМК (шаг 18): группы «Сегодня / Вчера / Раньше» — в зоне браузера.
describe("dayBucket", () => {
    test("splits at local midnight, not at UTC midnight", () => {
        // Хабаровск, UTC+10, половина первого ночи.
        mockDate("2026-08-12 00:30:00", +10);
        expect(dayBucket("2026-08-11 14:20:00")).toBe("today"); // 00:20 местного
        expect(dayBucket("2026-08-11 13:50:00")).toBe("yesterday"); // 23:50 вчера
        expect(dayBucket("2026-08-10 14:10:00")).toBe("yesterday"); // 00:10 вчера
        expect(dayBucket("2026-08-10 13:50:00")).toBe("earlier");
    });

    test("a clock running ahead is still today; nonsense is earlier", () => {
        mockDate("2026-08-12 15:00:00", +10);
        expect(dayBucket("2026-08-12 10:00:00")).toBe("today");
        expect(dayBucket("")).toBe("earlier");
        expect(dayBucket("not a date")).toBe("earlier");
    });
});

// ПРАВКА ПМК (шаг 18): вид списка и режим переписок помнятся в браузере, но
// хранилище, которое бросает (приватное окно, запрет сайта), почту не роняет.
describe("readPref / writePref", () => {
    test("round trip", () => {
        writePref("mail_client.test_pref", "compact");
        expect(readPref("mail_client.test_pref", "comfortable")).toBe("compact");
        expect(readPref("mail_client.missing_pref", "comfortable")).toBe("comfortable");
    });

    test("a storage that throws gives the default and is not written", () => {
        patchWithCleanup(browser, {
            localStorage: {
                getItem() {
                    throw new Error("SecurityError");
                },
                setItem() {
                    throw new Error("QuotaExceededError");
                },
            },
        });
        expect(readPref("mail_client.threaded.v2", null)).toBe(null);
        expect(readPref("mail_client.list_view", "comfortable")).toBe("comfortable");
        writePref("mail_client.list_view", "compact"); // не бросает
    });
});
