import { describe, expect, test } from "@odoo/hoot";

import { RecipientInput } from "@mail_client/composer/recipient_input";

describe.current.tags("headless");

/**
 * splitTyped decides which part of the field the autocomplete completes.
 * Getting it wrong either replaces recipients the user already entered or
 * searches for the whole string and finds nothing - both were easy to hit.
 */
function split(value) {
    return RecipientInput.prototype.splitTyped.call(null, value);
}

describe("recipient splitting", () => {
    test("treats a single entry as the one being typed", () => {
        expect(split("budi")).toEqual({ prefix: "", current: "budi" });
    });

    test("keeps earlier recipients untouched", () => {
        const { prefix, current } = split('"A" <a@x.com>, bud');
        expect(prefix).toBe('"A" <a@x.com>,');
        expect(current).toBe("bud");
    });

    test("handles a trailing comma with nothing typed yet", () => {
        const { prefix, current } = split('"A" <a@x.com>, ');
        expect(prefix).toBe('"A" <a@x.com>,');
        expect(current).toBe("");
    });

    test("is not confused by an address containing no comma", () => {
        expect(split("a@x.com").current).toBe("a@x.com");
    });

    test("ignores commas inside a quoted display name only at the end", () => {
        // The last comma wins, which is what matters: everything before it is
        // already-entered text that must be preserved verbatim.
        const { prefix } = split('"Santoso, Budi" <b@x.com>, ren');
        expect(prefix).toBe('"Santoso, Budi" <b@x.com>,');
    });
});
