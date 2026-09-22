/** @odoo-module **/

import { NavBar } from "@web/webclient/navbar/navbar";
import { patch } from "@web/core/utils/patch";
import { useState, useEffect } from "@odoo/owl";

const STORAGE_KEY = "nexus_theme_dark_mode";

patch(NavBar.prototype, {
    setup() {
        super.setup();

        let initial = false;
        try {
            initial = window.localStorage.getItem(STORAGE_KEY) === "1";
        } catch {
            // localStorage unavailable (e.g. private browsing) — default to light.
            initial = false;
        }
        this.nexusDarkState = useState({ isDark: initial });

        useEffect(
            (isDark) => {
                document.body.classList.toggle("o_nexus_dark", isDark);
                try {
                    window.localStorage.setItem(STORAGE_KEY, isDark ? "1" : "0");
                } catch {
                    // ignore storage failures
                }
            },
            () => [this.nexusDarkState.isDark]
        );
    },

    toggleNexusDarkMode() {
        this.nexusDarkState.isDark = !this.nexusDarkState.isDark;
    },
});
