import { describe, expect, test } from "@odoo/hoot";
import { isMarkup } from "@web/core/utils/html";

import { Composer } from "@mail_client/composer/composer";

describe.current.tags("headless");

/**
 * The editor sets its initial content through setElementContent(), which uses
 * innerHTML only for values flagged as markup and textContent for everything
 * else. Our body arrives over a plain RPC rather than an ORM read, so it never
 * carries that flag on its own - and a reply rendered as textContent shows the
 * quoted message as visible HTML source.
 */
function editorConfigFor(body) {
    const getter = Object.getOwnPropertyDescriptor(
        Composer.prototype, "editorConfig"
    ).get;
    return getter.call({ body });
}

describe("composer body", () => {
    test("editor content is flagged as markup, not plain text", () => {
        const config = editorConfigFor("<p>Hello</p>");
        expect(isMarkup(config.content)).toBe(true);
    });

    test("a quoted reply keeps its markup", () => {
        const quoted =
            '<p><br/></p><p>On 2026-08-13, a@b.com wrote:</p>' +
            '<blockquote>Original</blockquote>';
        const config = editorConfigFor(quoted);
        expect(isMarkup(config.content)).toBe(true);
        expect(config.content.toString()).toInclude("<blockquote>");
    });

    test("an empty body is still markup", () => {
        expect(isMarkup(editorConfigFor("").content)).toBe(true);
    });
});
