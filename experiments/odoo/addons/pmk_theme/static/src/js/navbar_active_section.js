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
 * КАК ОПРЕДЕЛЯЕМ — И ПОЧЕМУ НЕ ПО АДРЕСУ.
 * Первая версия сравнивала первый сегмент адресной строки с ссылкой пункта.
 * Это давало подсветку, отстающую на один шаг: открыты «Лиды» — подсвечены
 * «Заказы клиентов». Причина в том, что запись в адресную строку отложена —
 * router.js кладёт её в setTimeout (makeDebouncedPush, router.js:405-410),
 * поэтому в момент, когда шина сообщает о новом действии, location.pathname
 * ещё держит предыдущее.
 *
 * Вторая причина не использовать адрес: путь не всегда «первый сегмент —
 * действие». Odoo складывает стек в вид active_id/action/res_id
 * (router.js:134), так что у вложенного действия первым сегментом идёт
 * идентификатор родителя, а не то, что нам нужно.
 *
 * Поэтому берём router.current.action — состояние роутера, которое
 * обновляется сразу, до записи в адрес. Приводим его к тому же виду, в каком
 * ядро рисует ссылку пункта: число или строка с точкой дают «action-<N>»,
 * остальное — сам путь (та же развилка, что в stateToUrl, router.js:97-101).
 * Ссылку пункта берём у самого ядра через getMenuItemHref, чтобы обе стороны
 * сравнения происходили из одного источника.
 *
 * ПОЧЕМУ ПРАВИМ DOM, А НЕ ШАБЛОН. Шапку уже наследуют ядро, тема
 * theme_liquid_glass и мы — третий участник в том же узле нам дорого обошёлся.
 * К тому же класс через шаблон потребовал бы перерисовывать шапку на каждое
 * действие, а перерисовка тянет adapt() с пересчётом ширин всех пунктов.
 *
 * КОГДА ПЕРЕСЧИТЫВАЕМ:
 *  · ACTION_MANAGER:UI-UPDATED — шина сообщает о каждом открытом действии
 *    (action_service.js:1044);
 *  · ROUTE_CHANGE — навигация «назад/вперёд» в браузере, когда действие
 *    меняется мимо action_service (router.js:286, 301);
 *  · после каждого рендера шапки — иначе класс слетит, когда adapt()
 *    перерисует пункты, схлопнув часть из них в меню «ещё».
 */

import { patch } from "@web/core/utils/patch";
import { useBus } from "@web/core/utils/hooks";
import { browser } from "@web/core/browser/browser";
import { router, routerBus } from "@web/core/browser/router";
import { NavBar } from "@web/webclient/navbar/navbar";
import { useEffect } from "@odoo/owl";

patch(NavBar.prototype, {
    setup() {
        super.setup();
        useBus(this.env.bus, "ACTION_MANAGER:UI-UPDATED", () => this.pmkMarkActiveSection());
        useBus(routerBus, "ROUTE_CHANGE", () => this.pmkMarkActiveSection());
        useEffect(() => {
            this.pmkMarkActiveSection();
        });
    },

    /**
     * Текущее действие в том же виде, в каком оно попадает в ссылку пункта.
     * Развилка повторяет stateToUrl (router.js:97-101).
     */
    pmkCurrentKey() {
        const action = router.current && router.current.action;
        if (action === undefined || action === null || action === "") {
            // Запасной путь на случай, если состояние роутера ещё пустое:
            // берём последний сегмент вида action-N из адреса.
            const m = /\/odoo\/(?:.*\/)?(action-[^/?#]+)/.exec(browser.location.pathname);
            return m ? m[1] : null;
        }
        return typeof action === "number" || String(action).includes(".")
            ? `action-${action}`
            : String(action);
    },

    /** Ссылку пункта берём у ядра и отрезаем префикс — сравниваем сопоставимое. */
    pmkMenuKey(menu) {
        return this.getMenuItemHref(menu).replace(/^\/odoo\//, "");
    },

    /** Пункт активен сам или активен кто-то из потомков (пункт-выпадашка). */
    pmkIsActive(menu, key) {
        if (!key) {
            return false;
        }
        if (this.pmkMenuKey(menu) === key) {
            return true;
        }
        return (menu.childrenTree || []).some((child) => this.pmkIsActive(child, key));
    },

    pmkMarkActiveSection() {
        const root = this.root.el;
        if (!root) {
            return;
        }

        const key = this.pmkCurrentKey();
        const active = this.currentAppSections.find((section) => this.pmkIsActive(section, key));
        const activeId = active ? String(active.id) : null;

        // Цвет текущего раздела отдаём в CSS одной переменной на всю шапку —
        // так обе строки подсвечиваются одним цветом, а сами цвета остаются
        // в scss и не дублируются в коде.
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
