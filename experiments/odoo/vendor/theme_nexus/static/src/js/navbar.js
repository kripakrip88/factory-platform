/** @odoo-module **/

import { NavBar } from "@web/webclient/navbar/navbar";
import { patch } from "@web/core/utils/patch";
import { useState, useEffect } from "@odoo/owl";

const PIN_BREAKPOINT = 1200; // keep in sync with $nx-sidebar-breakpoint in variables.scss

patch(NavBar.prototype, {
    setup() {
        super.setup();
        this.sidebarState = useState({ isOpen: this.isWideScreen() });

        useEffect(
            (isOpen) => {
                const pinned = isOpen && this.isWideScreen();
                document.body.classList.toggle("o_nexus_sidebar_pinned", pinned);
            },
            () => [this.sidebarState.isOpen]
        );
    },

    isWideScreen() {
        return typeof window !== "undefined" && window.innerWidth >= PIN_BREAKPOINT;
    },

    toggleSidebar() {
        this.sidebarState.isOpen = !this.sidebarState.isOpen;
    },

    closeSidebar() {
        this.sidebarState.isOpen = false;
    },

    onNavBarAppClick(app) {
        if (!this.isWideScreen()) {
            this.closeSidebar();
        }
        this.menuService.selectMenu(app);
    },
});
