import { describe, expect, test } from "@odoo/hoot";
import { allowTranslations } from "@web/../tests/web_test_helpers";

import { MESSAGE_FILTERS, MailClientInbox } from "@mail_client/mail_client_action";

describe.current.tags("headless");

/**
 * The filter getters read nothing but state, so they can be exercised without
 * mounting the three-pane action and its services.
 */
function inboxWithFilter(filter) {
    const component = Object.create(MailClientInbox.prototype);
    component.state = { filter };
    return component;
}

describe("quick filters", () => {
    test("the first entry is the unfiltered default", () => {
        expect(MESSAGE_FILTERS[0].id).toBe("all");
    });

    test("every filter has a distinct id", () => {
        const ids = MESSAGE_FILTERS.map((item) => item.id);
        expect(new Set(ids).size).toBe(ids.length);
    });

    test("ids match the names the server accepts", () => {
        // MESSAGE_FILTERS in mail_client_folder.py rejects anything else, so a
        // name that drifts here becomes an error dialog on the first click.
        expect(MESSAGE_FILTERS.map((item) => item.id)).toEqual([
            "all",
            "unread",
            "read",
            "flagged",
            "attachments",
            "contact",
        ]);
    });

    test("activeFilter resolves the selected entry", () => {
        expect(inboxWithFilter("unread").activeFilter.id).toBe("unread");
    });

    test("activeFilter falls back to All for an unknown id", () => {
        // Reached if a stale value ever survives a reload; a menu button
        // labelled "undefined" is worse than showing everything.
        expect(inboxWithFilter("nonsense").activeFilter.id).toBe("all");
    });

    test("filterLabel is empty while unfiltered", () => {
        expect(inboxWithFilter("all").filterLabel).toBe("");
    });

    test("filterLabel is a plain string, not a lazy translation", () => {
        // Declared as a String prop on MessageList: handing it the object _t()
        // returns at module load fails prop validation in dev mode. Resolving
        // it is also what needs the translations to be available at all - the
        // labels are built when this module is imported, before they load.
        allowTranslations();
        const label = inboxWithFilter("unread").filterLabel;
        expect(typeof label).toBe("string");
        expect(label.length > 0).toBe(true);
    });
});
