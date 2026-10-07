/** @odoo-module **/
/**
 * Какой ящик и какое письмо открыть первыми (разбор UX, шаг 53, 07.10.2026)
 * — правила без Owl и без сервисов: их проверяет node
 * (static/tests/step53_open_rules.test.mjs).
 *
 * Почта открывается с параметрами действия (pmk_mail_ui/data/menus.xml):
 *   pmk_mailbox    — адрес ящика: из Продаж — заявки (pmkpark@mail.ru), из
 *                    Закупок — закупки (zakaz@pmkpark.ru). Без него модуль
 *                    почты открывал первый ящик по порядку (заявки) и из
 *                    Закупок тоже;
 *   pmk_message_id — письмо, по которому щёлкнули на вкладке «Связи»
 *                    (pmk_flow): первой встаёт его папка, и письмо
 *                    открывается.
 * Ничего не нашлось (ящика с таким адресом у человека нет, письмо удалено
 * или чужое) — null: почта открывается как раньше, первым ящиком.
 */

/** Адрес без пробелов и регистра: «Zakaz@PMKpark.ru » — тот же ящик. */
export function normEmail(value) {
    return String(value || "").trim().toLowerCase();
}

/** Что просили открыть — из params действия. */
export function openParams(params) {
    const messageId = Math.floor(Number(params?.pmk_message_id) || 0);
    return {
        mailbox: normEmail(params?.pmk_mailbox),
        messageId: messageId > 0 ? messageId : 0,
        // Папка письма — её спрашивают у сервера при первой загрузке ящиков.
        folderId: null,
        asked: false,
    };
}

/** Есть ли папка в дереве ящиков человека (get_inbox_state). */
export function hasFolder(accounts, folderId) {
    if (!folderId) {
        return false;
    }
    return (accounts || []).some((account) =>
        (account.folders || []).some((folder) => folder.id === folderId)
    );
}

/** «Входящие» ящика, а нет их — первая папка (как firstFolderId почты). */
export function inboxOf(account) {
    const folders = account?.folders || [];
    const inbox = folders.find((folder) => folder.role === "inbox");
    return (inbox || folders[0] || {}).id || null;
}

/**
 * Папка, которую открыть первой: папка письма, если она в дереве; иначе
 * «Входящие» ящика с адресом mailbox; иначе null (решает модуль почты).
 */
export function pickFolder(accounts, open) {
    if (!open) {
        return null;
    }
    if (hasFolder(accounts, open.folderId)) {
        return open.folderId;
    }
    if (open.mailbox) {
        const account = (accounts || []).find(
            (candidate) => normEmail(candidate.email) === open.mailbox
        );
        const folderId = account && inboxOf(account);
        if (folderId) {
            return folderId;
        }
    }
    return null;
}
