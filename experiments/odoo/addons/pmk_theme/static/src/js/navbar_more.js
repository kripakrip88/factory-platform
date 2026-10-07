/** @odoo-module **/
// Строка разделов: все разделы человека — одной строкой, без выпадашки.
//
// История. Разбор UX, шаг 5 (28.09.2026): пять рабочих разделов наверху,
// остальные — в выпадашке «Ещё». Шаг 61 (Антон, 08.10.2026): «давай
// выпадашку уберём из главного меню, места хватает» — разделы Производство,
// Склад, Деньги и т.п. и так видны только по галочке у человека (шаг 38),
// так что строка не растягивается.
//
// Порядок: сначала рабочие разделы в порядке работы (Продажи → Калькуляторы →
// Закупки → Лазерная резка), потом остальные в порядке меню, Настройки —
// последними. Порядок задаём здесь, а не sequence меню: sequence заодно
// правит мобильное меню и меню приложений, там порядок трогать незачем.
// Раздела нет у пользователя (например, Настроек у менеджера) — его просто
// нет в строке.
//
// Шаблон — xml/navbar.xml (выпадашка осталась в нём на случай возврата:
// pmkMoreApps пустой — и она не рисуется), оформление — scss/navbar_nexus.scss.

import { patch } from "@web/core/utils/patch";
import { NavBar } from "@web/webclient/navbar/navbar";

const FIRST_APPS = [
    "pmk_theme.menu_pmk_sales",
    "pmk_calc.menu_pmk_calc",
    "pmk_theme.menu_pmk_purchase",
    "pmk_laser.menu_pmk_laser",
];
const LAST_APPS = ["base.menu_administration"];

export function orderApps(apps) {
    const first = FIRST_APPS.map((xmlid) => apps.find((app) => app.xmlid === xmlid)).filter(Boolean);
    const last = LAST_APPS.map((xmlid) => apps.find((app) => app.xmlid === xmlid)).filter(Boolean);
    const middle = apps.filter((app) => !FIRST_APPS.includes(app.xmlid) && !LAST_APPS.includes(app.xmlid));
    return [...first, ...middle, ...last];
}

patch(NavBar.prototype, {
    get pmkMainApps() {
        return orderApps(this.menuService.getApps());
    },

    // Выпадашки «Ещё» больше нет (шаг 61): все разделы — в строке.
    get pmkMoreApps() {
        return [];
    },

    get pmkActiveMoreApp() {
        return null;
    },
});
