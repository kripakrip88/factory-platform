import { browser } from "@web/core/browser/browser";
import { deserializeDateTime, formatDateTime } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";

/**
 * Render a message timestamp the way mail clients do: time for today,
 * weekday for the last week, date beyond that.
 */
export function formatMessageDate(value) {
    if (!value) {
        return "";
    }
    const dt = deserializeDateTime(value);
    if (!dt || !dt.isValid) {
        return "";
    }
    const now = dt.constructor.now();
    if (dt.hasSame(now, "day")) {
        return dt.toFormat("HH:mm");
    }
    if (now.diff(dt, "days").days < 7) {
        return dt.toFormat("ccc HH:mm");
    }
    return formatDateTime(dt, { format: "dd MMM yyyy" });
}

/** Strip the angle-bracket address, keeping the display name when there is one. */
export function senderName(emailFrom) {
    if (!emailFrom) {
        return _t("(unknown sender)");
    }
    const match = emailFrom.match(/^\s*"?([^"<]*?)"?\s*<[^>]+>\s*$/);
    if (match && match[1].trim()) {
        return match[1].trim();
    }
    return emailFrom.trim();
}

/**
 * ПРАВКА ПМК: «Имя <адрес>» по частям — для строки «От» над письмом, где имя
 * выделено, а адрес приглушён (шаг 17). Без имени name пустой; адрес без
 * угловых скобок — address как есть.
 */
export function splitAddress(emailFrom) {
    const text = (emailFrom || "").trim();
    const match = text.match(/^"?([^"<]*?)"?\s*<([^>]+)>\s*$/);
    if (!match) {
        return { name: "", address: text };
    }
    const name = match[1].trim();
    const address = match[2].trim();
    return { name: name === address ? "" : name, address };
}

/**
 * ПРАВКА ПМК (шаг 18): получатель для строки «Кому: …» — первое имя (без
 * имени — адрес) и «+N», если адресатов несколько.
 *
 * Делим по запятой только ПОСЛЕ адреса: имя в заголовке бывает с запятой и
 * без кавычек («Зимихина Наталья, АО Хабаровск Автомост <habavtpto@mail.ru>»
 * — это один адресат, а не два), и не внутри кавычек или угловых скобок.
 */
export function splitRecipients(emailTo) {
    const parts = [];
    let current = "";
    for (const char of emailTo || "") {
        const outside =
            current.includes("@") &&
            !/<[^>]*$/.test(current) &&
            (current.split('"').length - 1) % 2 === 0;
        if ((char === "," || char === ";") && outside) {
            parts.push(current);
            current = "";
        } else {
            current += char;
        }
    }
    parts.push(current);
    return parts.map((part) => part.trim()).filter(Boolean);
}

export function recipientLabel(emailTo) {
    const recipients = splitRecipients(emailTo);
    if (!recipients.length) {
        return _t("(no recipient)");
    }
    const first = splitAddress(recipients[0]);
    const label = first.name || first.address;
    return recipients.length > 1 ? `${label} +${recipients.length - 1}` : label;
}

/**
 * ПРАВКА ПМК (шаг 18): группа строки списка — "today", "yesterday" или
 * "earlier". Сутки — в той же зоне, в которой formatMessageDate показывает
 * время (зона браузера): у Антона Asia/Vladivostok, время Хабаровска.
 * Письмо «из будущего» (часы отправителя спешат) — сегодня.
 */
export function dayBucket(value, now = null) {
    const dt = value ? deserializeDateTime(value) : null;
    if (!dt || !dt.isValid) {
        return "earlier";
    }
    const today = (now || dt.constructor.now()).setZone(dt.zone).startOf("day");
    if (dt >= today) {
        return "today";
    }
    if (dt >= today.minus({ days: 1 })) {
        return "yesterday";
    }
    return "earlier";
}

/**
 * ПРАВКА ПМК (шаг 18): настройка вида в хранилище браузера. Хранилища может
 * не быть или оно бросает (приватное окно, запрет сайта) — тогда значение по
 * умолчанию, а запись молча пропускается: вид не повод ронять почту.
 */
export function readPref(key, fallback = null) {
    try {
        const value = browser.localStorage.getItem(key);
        return value === null || value === undefined ? fallback : value;
    } catch {
        return fallback;
    }
}

export function writePref(key, value) {
    try {
        browser.localStorage.setItem(key, String(value));
    } catch {
        // Не запомнили — в следующий раз вид по умолчанию.
    }
}

/**
 * ПРАВКА ПМК: форма числа по правилам языка — "one", "few" или "other"
 * («1 письмо», «2 письма», «5 писем»). В _t форм множественного числа нет,
 * а по-русски их три, поэтому форму выбирает Intl.PluralRules, а у каждой
 * формы своя строка перевода (шаг 17: «14 писем» в строке над письмом;
 * шаг 20: «ещё 3 письма» в переписке). Английский «few» не выбирает
 * никогда; "many" русского («5 писем») сводим к "other". lang — как у
 * браузера («ru-RU»), у Odoo это user.lang.
 */
export function pluralForm(count, lang) {
    let form = "other";
    try {
        form = new Intl.PluralRules(lang || "en").select(count);
    } catch {
        return "other"; // неизвестный браузеру язык — английские формы
    }
    return form === "one" || form === "few" ? form : "other";
}

/** Format a byte count for display. */
export function formatSize(bytes) {
    if (!bytes) {
        return "";
    }
    const units = ["B", "KB", "MB", "GB"];
    let value = bytes;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
        value /= 1024;
        unit++;
    }
    return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}
