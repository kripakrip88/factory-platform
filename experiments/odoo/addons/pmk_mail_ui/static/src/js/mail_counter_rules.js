/** @odoo-module **/
/**
 * Счётчик новых писем (разбор удобства, шаг 41, Г12) — правила без Owl и без
 * сервисов: их проверяет node (static/tests/step41_counter_rules.test.mjs).
 *
 * Число — непрочитанные во «Входящих» за последние 30 дней (окно общих с
 * mail.ru отметок, FLAG_WINDOW_DAYS): старше окна отметка «прочитано» с
 * mail.ru не обновляется, и число врало бы. С шага 53 (07.10.2026) у каждого
 * пункта «Почта» — число того ящика, который он открывает: «Продажи → Почта»
 * — заявки, «Закупки → Почта» — закупки (models/mail_client_step53.py,
 * pmk_mail_unread_counts). Вкладка браузера «(3) …» — все «Входящие»
 * человека.
 */

/** Пункт «Продажи → Почта» (pmk_mail_ui/data/menus.xml). */
export const MAIL_MENU_XMLID = "pmk_mail_ui.menu_mail_sale";
/** Пункт «Закупки → Почта» — свой ящик с шага 53. */
export const PURCHASE_MAIL_MENU_XMLID = "pmk_mail_ui.menu_mail_purchase";
/** Пункты, на которых стоит число, — те же, что MAIL_MENUS на сервере. */
export const MAIL_MENUS = [MAIL_MENU_XMLID, PURCHASE_MAIL_MENU_XMLID];
/** Окно счётчика, дней — то же, что FLAG_WINDOW_DAYS в mail_client_flags.py. */
export const COUNTER_DAYS = 30;
/** Пауза перед перечитыванием: правки в почте идут пачкой. */
export const REFRESH_DELAY_MS = 1500;
/** Запасной опрос, если сигнал синхронизации не дошёл, — только на видимой вкладке. */
export const POLL_MS = 5 * 60 * 1000;

/** Число на пункте меню: пусто при нуле, дальше 99 — «99+». */
export function counterText(count) {
    const value = Math.floor(Number(count) || 0);
    if (value <= 0) {
        return "";
    }
    return value > 99 ? "99+" : String(value);
}

/** Подсказка пункта меню — что значит число (цвет повторён словом). */
export function counterTitle(count, days = COUNTER_DAYS) {
    const value = Math.floor(Number(count) || 0);
    if (value <= 0) {
        return "";
    }
    return `Непрочитанных во «Входящих» за ${days} дней: ${value}`;
}

/**
 * Перечитать ли число по сигналу синхронизации почты (mail_client.sync):
 * проход что-то изменил в письмах (changed). Сигнал старого сервера без
 * changed — «изменилось».
 */
export function shouldRefresh(payload) {
    return !payload || payload.changed !== false;
}

/**
 * Числа пунктов меню: {xmlid пункта: число} для каждого из MAIL_MENUS.
 * Ответ старого сервера — одно число без разбивки (menus нет): оно, как
 * раньше, на «Продажи → Почта», у Закупок — пусто.
 */
export function menuCounts(menus, total = 0) {
    const result = {};
    for (const xmlid of MAIL_MENUS) {
        result[xmlid] = 0;
    }
    if (menus && typeof menus === "object") {
        for (const xmlid of MAIL_MENUS) {
            result[xmlid] = Math.max(0, Math.floor(Number(menus[xmlid]) || 0));
        }
    } else {
        result[MAIL_MENU_XMLID] = Math.max(0, Math.floor(Number(total) || 0));
    }
    return result;
}
