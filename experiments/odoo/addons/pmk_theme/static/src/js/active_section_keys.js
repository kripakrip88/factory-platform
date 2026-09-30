/** @odoo-module **/
/**
 * Ключи «где я» для подсветки текущего пункта строки разделов.
 *
 * Чистые функции без импортов Odoo — чтобы их можно было прогнать в node
 * без браузера (разбор UX, шаг 23). Использует navbar_active_section.js.
 *
 * Ключ — строка того же вида, в каком ядро пишет действие в адрес:
 * «action-<номер>» для номера (и для xmlid — как stateToUrl, router.js) или
 * сам path действия («crm», «purchase», «price-mailing»). У действия и у
 * пункта меню может быть по два ключа — номер и path: пункт горит, если
 * совпал любой.
 */

/**
 * Одно значение → ключ. Число, строка из цифр и xmlid (есть точка) дают
 * «action-…», любое другое непустое — путь как есть. Пусто — null.
 */
export function actionKey(value) {
    if (value === undefined || value === null || value === false || value === "") {
        return null;
    }
    const text = String(value);
    return typeof value === "number" || /^\d+$/.test(text) || text.includes(".")
        ? `action-${text}`
        : text;
}

/**
 * Ключи открытого действия: номер и path. Действие, которое вернуло
 * серверное (воронка через /odoo/crm, рассылка прайсов), несёт path
 * серверного — ядро приписывает его само (action_service.js,
 * _executeServerAction: nextAction.path ||= action.path).
 */
export function controllerKeys(action) {
    if (!action) {
        return [];
    }
    return [action.id, action.path].map(actionKey).filter(Boolean);
}

/** Ключи пункта меню: номер его действия и path (actionID / actionPath). */
export function menuKeys(menu) {
    const keys = [];
    if (menu && menu.actionID) {
        keys.push(`action-${menu.actionID}`);
    }
    if (menu && menu.actionPath) {
        keys.push(String(menu.actionPath));
    }
    return keys;
}

/** Пункт активен сам или активен кто-то из потомков (пункт-выпадашка). */
export function isMenuActive(menu, keys) {
    if (!menu || !keys || !keys.length) {
        return false;
    }
    if (menuKeys(menu).some((key) => keys.includes(key))) {
        return true;
    }
    return (menu.childrenTree || []).some((child) => isMenuActive(child, keys));
}
