/** @odoo-module **/
/**
 * Счётчик новых писем (разбор удобства, шаг 41, Г12) — правила без Owl и без
 * сервисов: их проверяет node (static/tests/step41_counter_rules.test.mjs).
 *
 * Число — непрочитанные во «Входящих» ящиков, доступных человеку, за
 * последние 30 дней (окно общих с mail.ru отметок, FLAG_WINDOW_DAYS):
 * старше окна отметка «прочитано» с mail.ru не обновляется, и число врало бы.
 * Показывается на пункте «Продажи → Почта» и во вкладке браузера «(3) …».
 */

/** Пункт меню, на котором стоит число (pmk_mail_ui/data/menus.xml). */
export const MAIL_MENU_XMLID = "pmk_mail_ui.menu_mail_sale";
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
