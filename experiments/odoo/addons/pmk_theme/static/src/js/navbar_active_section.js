/**
 * Подсветка активного пункта во второй строке шапки.
 *
 * ЗАЧЕМ. Ядро Odoo 19 не помечает текущий подраздел никак: в шаблоне
 * web.NavBar.SectionsMenu пункт рисуется как
 *     <DropdownItem class="'o_nav_entry'" .../>
 * — ни класса active, ни aria-current (navbar.xml:166). Пользователь видит
 * строку пунктов и не понимает, где находится. Правило nav-state-active
 * требует, чтобы текущее положение читалось визуально.
 *
 * ПОЧЕМУ ВЫЧИСЛЯЕМ САМИ. menuService хранит только текущее ПРИЛОЖЕНИЕ
 * (currentAppId в menu_service.js), понятия «текущий пункт» в нём нет вовсе.
 *
 * КАК ОПРЕДЕЛЯЕМ. Сравниваем первый сегмент пути в адресной строке с тем,
 * что даёт getMenuItemHref(section) — то есть ровно с той функцией, которой
 * ядро рисует ссылку пункта. Симметрия важна: если Odoo однажды поменяет
 * формат адресов, подсветка поедет вместе с разметкой, а не разойдётся с ней.
 * Сегмент берём первый, потому что при открытии записи адрес удлиняется
 * (/odoo/action-348 → /odoo/action-348/5), а пункт остаётся тем же.
 *
 * ПОЧЕМУ ПРАВИМ DOM, А НЕ ШАБЛОН. Шапку уже наследуют и ядро, и тема
 * theme_liquid_glass, и мы. Ещё одно наследование ради одного класса добавило
 * бы третьего участника в тот же узел. К тому же класс через шаблон потребовал
 * бы перерисовывать всю шапку на каждое действие, а перерисовка тянет за собой
 * adapt() с пересчётом ширин всех пунктов. Проставить класс дешевле.
 *
 * КОГДА ПЕРЕСЧИТЫВАЕМ:
 *  · ACTION_MANAGER:UI-UPDATED — шина сообщает о каждом открытом действии
 *    (action_service.js:1044), это и есть смена пункта;
 *  · после каждого рендера шапки — иначе класс слетит, когда adapt() перерисует
 *    пункты, схлопнув часть из них в меню «ещё».
 */

import { patch } from "@web/core/utils/patch";
import { useBus } from "@web/core/utils/hooks";
import { browser } from "@web/core/browser/browser";
import { NavBar } from "@web/webclient/navbar/navbar";
import { useEffect } from "@odoo/owl";

patch(NavBar.prototype, {
    setup() {
        super.setup();
        useBus(this.env.bus, "ACTION_MANAGER:UI-UPDATED", () => this.pmkMarkActiveSection());
        useEffect(() => {
            this.pmkMarkActiveSection();
        });
    },

    /** Первый сегмент пути после /odoo/ — общий знаменатель адреса и ссылки пункта. */
    pmkPathKey(path) {
        const m = /^\/odoo\/([^/?#]+)/.exec(path || "");
        return m ? m[1] : null;
    },

    /** Пункт активен сам или активен кто-то из его потомков (пункт-выпадашка). */
    pmkIsActive(section, key) {
        if (!key) {
            return false;
        }
        if (this.pmkPathKey(this.getMenuItemHref(section)) === key) {
            return true;
        }
        return (section.childrenTree || []).some((child) => this.pmkIsActive(child, key));
    },

    pmkMarkActiveSection() {
        const root = this.root.el;
        if (!root) {
            return;
        }

        const key = this.pmkPathKey(browser.location.pathname);
        const active = this.currentAppSections.find((section) => this.pmkIsActive(section, key));
        const activeId = active ? String(active.id) : null;

        // Цвет текущего раздела отдаём в CSS одной переменной на всю шапку —
        // так обе строки подсвечиваются одним цветом, а сами цвета остаются
        // в одном месте, в scss, и не дублируются в коде.
        const app = this.currentApp;
        if (app && app.xmlid) {
            root.dataset.pmkApp = app.xmlid;
        } else {
            delete root.dataset.pmkApp;
        }

        for (const el of root.querySelectorAll(".o_menu_sections [data-section]")) {
            // У обычного пункта data-section висит на самой ссылке, у пункта с
            // потомками — на <span> внутри кнопки-выпадашки. Красим то, что видно.
            const target = el.closest(".o_nav_entry, .dropdown-toggle, button") || el;
            const on = activeId !== null && String(el.dataset.section) === activeId;

            target.classList.toggle("pmk_section--active", on);
            if (on) {
                target.setAttribute("aria-current", "page");
            } else {
                target.removeAttribute("aria-current");
            }
        }
    },
});
