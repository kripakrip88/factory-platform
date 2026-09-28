/** @odoo-module **/
// Строка разделов: пять рабочих наверху, остальные — в выпадашке «Ещё».
//
// Разбор UX, шаг 5 (Антон, 28.09.2026, к пункту «10 разделов → 5»): «можно не
// убирать, а спрятать в общую кнопку-выпадашку в верхнем меню, чтобы
// освободить место».
//
// Наверху — разделы, в которых завод работает каждый день, в порядке работы:
// Продажи → Калькуляторы → Закупки → Лазерная резка, и Настройки. В «Ещё» —
// Производство, Склад, Деньги, Отчёты, Сотрудники: полный контур
// производства и склада не вводим, счета и отгрузки — в МойСкладе (решения
// владельца), разделы почти пустые. Ничего не удалено и не выключено: всё
// открывается из «Ещё» за один щелчок.
//
// ПОЧЕМУ СПИСОК ОСНОВНЫХ, А НЕ СПИСОК СПРЯТАННЫХ. Раздел, который появится
// потом (новый модуль), попадёт в «Ещё», а не растянет строку. Порядок в
// строке — порядок этого списка, а не sequence меню: sequence заодно правит
// мобильное меню и меню приложений, а там порядок трогать незачем.
// Раздела нет у пользователя (например, Настроек у менеджера) — его просто
// нет в строке.
//
// Шаблон — xml/navbar.xml, оформление — scss/navbar_nexus.scss («Ещё»).

import { patch } from "@web/core/utils/patch";
import { NavBar } from "@web/webclient/navbar/navbar";

const MAIN_APPS = [
    "pmk_theme.menu_pmk_sales",
    "pmk_calc.menu_pmk_calc",
    "pmk_theme.menu_pmk_purchase",
    "pmk_laser.menu_pmk_laser",
    "base.menu_administration",
];

patch(NavBar.prototype, {
    get pmkMainApps() {
        const apps = this.menuService.getApps();
        return MAIN_APPS.map((xmlid) => apps.find((app) => app.xmlid === xmlid)).filter(Boolean);
    },

    get pmkMoreApps() {
        return this.menuService.getApps().filter((app) => !MAIN_APPS.includes(app.xmlid));
    },

    // Открыт раздел из «Ещё» — кнопка показывает его имя и подсвечена, как
    // обычный текущий раздел: иначе по шапке не понять, где находишься.
    get pmkActiveMoreApp() {
        const current = this.menuService.getCurrentApp();
        return current && !MAIN_APPS.includes(current.xmlid) ? current : null;
    },
});
