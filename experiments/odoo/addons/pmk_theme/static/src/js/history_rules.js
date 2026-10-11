/** @odoo-module **/
/**
 * Окно «История» как «История изменений» МоегоСклада — разбор UX, шаг 66
 * (11.10.2026): правила без Odoo.
 *
 * Антон 11.10 прислал два скриншота — наше окно «История» и «Историю
 * изменений» МоегоСклада: «в моём складе гораздо чётче выглядит структура
 * изменений». Там каждое событие — строка «Голубенко В., изменено
 * 01.10.2026 12:38», под ней таблица «Поле | Было | Стало», позиции — по одной
 * на строку.
 *
 * Чистые функции без импортов Odoo — их гоняет node
 * (static/tests/history_step66.test.mjs). Использует doc_history.js
 * (PmkHistoryMessage).
 */

/** Автор системных записей (OdooBot, записи без автора и адреса). */
export const SYSTEM_AUTHOR = "Система";

/** Пустая ячейка таблицы. */
export const EMPTY_CELL = "—";

/** Шапка таблицы изменений. */
export const TABLE_HEAD = Object.freeze(["Поле", "Было", "Стало"]);

/** Действие словом — в заголовке события после автора. */
export const ACTIONS = Object.freeze({
    email: "письмо",
    activityDone: "задача выполнена",
    created: "создано",
    changed: "изменено",
    note: "заметка",
    other: "запись",
});

// ─── Автор ───────────────────────────────────────────────────────────────

// Организация или адрес — имя как есть: «ООО «ЦКС»», «zakaz@pmkpark.ru».
const KEEP_AS_IS = /[@«»"0-9]/;
const COMPANY = /(?:^|\s)(?:ООО|АО|ПАО|ЗАО|ОАО|ИП|LLC|Ltd)(?:\s|$|\.)/i;
// Слово целиком заглавными (две буквы и больше) — сокращение: «УК БСМ»,
// «ПМК Парк», «Цех ПМК Парк» — название, а не человек.
const ABBREVIATION = /(?:^|\s)[A-ZА-ЯЁ]{2,}(?=\s|$)/;
// Похоже на фамилию: Карнеев, Кузнецова, Никитин, Голубенко, Ковальчук,
// Черных, Белоцерковский.
const SURNAME_END = /(?:ов|ова|ев|ева|ёв|ёва|ин|ина|ын|ына|ский|ская|цкий|цкая|ко|ук|юк|их|ых)$/i;
// Частые имена. Нужны с двух сторон: имя с окончанием фамилии («Валентин»,
// «Ирина») — не фамилия; рядом с известным именем стоит фамилия, даже без
// фамильного окончания («Ким Ирина» → «Ким И.», «Гуль Александр» →
// «Гуль А.»).
const FIRST_NAMES = new Set([
    // похожие на фамилию окончанием
    "валентин", "вениамин", "константин", "мартин", "марина", "кристина",
    "алина", "полина", "галина", "ирина", "екатерина", "регина", "нина",
    "янина", "карина", "ангелина", "валентина", "дарина", "арина",
    // прочие частые
    "александр", "александра", "алексей", "анатолий", "андрей", "антон",
    "аркадий", "артём", "артем", "борис", "вадим", "василий", "виктор",
    "виталий", "владимир", "владислав", "вячеслав", "геннадий", "георгий",
    "григорий", "денис", "дмитрий", "евгений", "егор", "иван", "игорь",
    "илья", "кирилл", "леонид", "максим", "михаил", "никита", "николай",
    "олег", "павел", "пётр", "петр", "роман", "руслан", "сергей",
    "станислав", "степан", "тимур", "фёдор", "федор", "юрий", "ярослав",
    "алла", "анастасия", "анна", "вера", "виктория", "дарья", "евгения",
    "елена", "елизавета", "жанна", "зоя", "инна", "кира", "ксения",
    "лариса", "любовь", "людмила", "мария", "надежда", "наталья", "наталия",
    "оксана", "ольга", "светлана", "софья", "татьяна", "юлия",
]);
// Отчество: Владимирович, Геннадьевна, Ильинична, Кемал оглы, Алиевна кызы.
const PATRONYMIC_END = /(?:вич|вна|ична|инична|оглы|кызы)$/i;

function isFirstName(word) {
    return FIRST_NAMES.has(String(word || "").toLowerCase());
}

function looksSurname(word) {
    return SURNAME_END.test(word) && !isFirstName(word);
}

function initial(word) {
    return word ? word.charAt(0).toUpperCase() + "." : "";
}

/**
 * «Фамилия И.» из полного имени: «Антон Карнеев» → «Карнеев А.»,
 * «Кытманова Мария» → «Кытманова М.», «Кузнецов Алексей Владимирович» →
 * «Кузнецов А.». Как есть: одно слово, организация (isCompany, ООО/АО/ИП,
 * кавычки, цифры, слово заглавными), адрес, четыре слова и больше, а также
 * имя, где фамилию не опознать («Восток Маркет», «Металл Сервис») — лучше
 * полностью, чем угадывать порядок.
 */
export function shortName(name, { isCompany = false } = {}) {
    const text = String(name || "").replace(/\s+/g, " ").trim();
    if (!text || isCompany || KEEP_AS_IS.test(text) || COMPANY.test(text) || ABBREVIATION.test(text)) {
        return text;
    }
    const words = text.split(" ");
    if (words.length === 2) {
        const [first, second] = words;
        // Фамилия — слово с фамильным окончанием или соседнее с известным именем.
        const firstIsSurname = looksSurname(first) || isFirstName(second);
        const secondIsSurname = looksSurname(second) || isFirstName(first);
        if (firstIsSurname && !secondIsSurname) {
            return `${first} ${initial(second)}`;
        }
        if (secondIsSurname) {
            return `${second} ${initial(first)}`;
        }
        return text;
    }
    if (words.length === 3) {
        const [a, b, c] = words;
        if (PATRONYMIC_END.test(c)) {
            return `${a} ${initial(b)}`; // Фамилия Имя Отчество
        }
        if (PATRONYMIC_END.test(b)) {
            return `${c} ${initial(a)}`; // Имя Отчество Фамилия
        }
        if (looksSurname(c) || isFirstName(a)) {
            return `${c} ${initial(a)}`; // Пётр Ильич Чайковский
        }
        if (looksSurname(a)) {
            return `${a} ${initial(b)}`;
        }
        return text;
    }
    return text;
}

/** Имя из адреса письма: «"Оксана" <oksana@cks1.ru>» → «Оксана». */
export function emailName(emailFrom) {
    const text = String(emailFrom || "").trim();
    const match = text.match(/^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$/);
    if (match) {
        return match[1].trim() || match[2].trim();
    }
    return text;
}

/**
 * Автор кратко. OdooBot, а также запись без автора и без адреса —
 * «Система». Автор-организация (isCompany — res.partner.is_company, ядро
 * присылает его с автором) — название как есть.
 */
export function authorLabel({ hasAuthor, isSystem, isCompany, name, emailFrom } = {}) {
    if (isSystem) {
        return SYSTEM_AUTHOR;
    }
    if (hasAuthor) {
        // Организация-автор (письмо от контрагента) — название как есть.
        return shortName(name, { isCompany: Boolean(isCompany) }) || SYSTEM_AUTHOR;
    }
    if (emailFrom) {
        return shortName(emailName(emailFrom)) || SYSTEM_AUTHOR;
    }
    return SYSTEM_AUTHOR;
}

// ─── Дата и заголовок ────────────────────────────────────────────────────

function pad2(n) {
    return String(n).padStart(2, "0");
}

/**
 * «08.10.2026 22:48» по {year, month, day, hour, minute} (у luxon эти поля
 * есть; время — в поясе человека, как у ядра). Без даты — пусто.
 */
export function stampText(dt) {
    if (!dt || !dt.year) {
        return "";
    }
    return `${pad2(dt.day)}.${pad2(dt.month)}.${dt.year} ${pad2(dt.hour || 0)}:${pad2(dt.minute || 0)}`;
}

/** «Карнеев А., изменено 08.10.2026 22:48». */
export function headLine({ author, action, stamp } = {}) {
    const who = author || SYSTEM_AUTHOR;
    return [`${who}, ${action || ACTIONS.other}`, stamp].filter(Boolean).join(" ");
}

// ─── Действие словом ─────────────────────────────────────────────────────

/** Текст HTML без тегов, пробелы схлопнуты. */
export function plainText(html) {
    return String(html || "")
        .replace(/<[^>]*>/g, " ")
        .replace(/&nbsp;/g, " ")
        .replace(/&laquo;/g, "«")
        .replace(/&raquo;/g, "»")
        .replace(/&quot;/g, '"')
        .replace(/&amp;/g, "&")
        .replace(/\s+/g, " ")
        .trim();
}

/**
 * Создание записи: «Создано: Расчёт металлопроката» (наш перевод
 * tracking_manager), «Для команды «Продажи» создан новый лид.», «В проекте …
 * создана новая задача.», подтип «Сделка создана».
 *
 * Шаблоны по тексту — только для системных записей (systemOnly: тип
 * notification; на боевой все 1589 таких записей — notification): заметка
 * человека «Создан новый расчёт, жду цены» — заметка, а не «создано».
 * Описание подтипа проверяется у любой записи.
 */
export function isCreationText(text, subtypeDescription, { textRules = true } = {}) {
    const body = String(text || "").trim();
    if (textRules && /^Создан[оаы]?\s*:/i.test(body)) {
        return true;
    }
    if (textRules && (/создан[аоы]?\s+нов/i.test(body) || /has been created/i.test(body))) {
        return true;
    }
    return /создан/i.test(String(subtypeDescription || ""));
}

/**
 * Выполненная задача — шаблон ядра mail.message_activity_done: первый абзац
 * «<span class="fa … fa-fw"></span><span>Имя задачи</span> выполнено».
 */
export function isActivityDoneBody(html) {
    return /<p[^>]*>\s*<span[^>]*class="[^"]*\bfa\b[^"]*"[^>]*>\s*<\/span>\s*<span[^>]*>[^<]*<\/span>\s*(?:выполнено|done)(?![\wа-яё])/i
        .test(String(html || ""));
}

/**
 * Действие словом по типу сообщения. Порядок проверок важен: письмо — даже
 * если в нём есть «создан» (лид из письма: первое событие — само письмо с
 * подтипом «Сделка создана», его subtypeLine выводит строкой); выполненная
 * задача — раньше создания; изменения полей — раньше заметки
 * (tracking_manager пишет их заметкой). Создание по тексту тела — только у
 * системной записи (notification), у заметки человека — по подтипу.
 */
export function actionWord({
    messageType,
    isNote,
    isDiscussion,
    hasTracking,
    hasX2m,
    bodyText,
    bodyHtml,
    subtypeDescription,
} = {}) {
    if (messageType === "email" || messageType === "email_outgoing"
        || (isDiscussion && (messageType === "comment" || messageType === "auto_comment"))) {
        return ACTIONS.email;
    }
    if (isActivityDoneBody(bodyHtml)) {
        return ACTIONS.activityDone;
    }
    const text = bodyText !== undefined ? bodyText : plainText(bodyHtml);
    // Текст тела — признак создания только у системной записи.
    if (isCreationText(text, subtypeDescription, { textRules: messageType === "notification" })) {
        return ACTIONS.created;
    }
    if (hasTracking || hasX2m) {
        return ACTIONS.changed;
    }
    if (messageType === "comment" && isNote) {
        return ACTIONS.note;
    }
    return ACTIONS.other;
}

/**
 * Описание подтипа отдельной строкой («Этап изменен», «Сделка выиграна»).
 * У писем — только про создание: лид из письма начинается самим письмом с
 * подтипом «Сделка создана» (отдельной записи «создан новый лид» нет), и без
 * этой строки создание в истории не видно. Не у «создано», если оно само про
 * создание; не когда совпадает с текстом записи (как у ядра —
 * showSubtypeDescription).
 */
export function subtypeLine({ action, description, bodyText } = {}) {
    const desc = String(description || "").trim();
    if (!desc) {
        return "";
    }
    if (action === ACTIONS.email) {
        return /создан/i.test(desc) ? desc : "";
    }
    if (action === ACTIONS.created && /создан/i.test(desc)) {
        return "";
    }
    if (bodyText && desc.toLowerCase() === String(bodyText).trim().toLowerCase()) {
        return "";
    }
    return desc;
}

// ─── Таблица «Поле | Было | Стало» ───────────────────────────────────────

// Неразрывный пробел между числом и единицей в конце: «000,00\u00a0руб».
const UNIT_NBSP = /(\d)\u00a0(?=[^\d\s\u00a0]+$)/;

/**
 * Ячейка: пустое, null, false — «—»; ноль — «0». Пробел перед единицей в
 * конце («9 500 000,00 руб» — formatMonetary ставит неразрывный) — обычный:
 * на телефоне «руб» уходит на следующую строку целиком, а не «ру» / «б».
 * Пробелы между разрядами остаются неразрывными — число не рвётся.
 */
export function cellText(value) {
    if (value === undefined || value === null || value === false) {
        return EMPTY_CELL;
    }
    const text = String(value).trim().replace(UNIT_NBSP, "$1 ");
    return text ? text : EMPTY_CELL;
}

/** Строки таблицы из изменений полей [{field, old, new}]. */
export function trackingRows(items) {
    return (items || []).map((item) => ({
        field: String(item.field || "").trim() || EMPTY_CELL,
        old: cellText(item.old),
        new: cellText(item.new),
    }));
}

// Метки vendor/tracking_manager (views/message_template.xml) — по-русски
// (i18n_extra) и, на всякий случай, исходные английские.
export const TM_MODES = Object.freeze({
    "добавлено": "create",
    "new": "create",
    "удалено": "unlink",
    "delete": "unlink",
    "изменено": "update",
    "change": "update",
});

const ELEMENT = 1;
const TEXT = 3;

function tag(node) {
    return node && node.nodeType === ELEMENT ? String(node.tagName || "").toLowerCase() : "";
}

function kids(node) {
    return Array.from((node && node.childNodes) || []);
}

function elements(node) {
    return kids(node).filter((n) => n.nodeType === ELEMENT);
}

function squash(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
}

function modeOf(label) {
    const key = squash(label).replace(/\s*:\s*$/, "").toLowerCase();
    return TM_MODES[key] || null;
}

/** «Детали : 12 → 13» — имя до « :», старое до стрелки, новое после. */
function parseChange(li) {
    let before = "";
    let after = "";
    let arrow = false;
    for (const node of kids(li)) {
        if (node.nodeType === ELEMENT && tag(node) === "div") {
            arrow = true;
            continue;
        }
        const text = node.nodeType === TEXT ? node.textContent : (node.textContent || "");
        if (arrow) {
            after += text;
        } else {
            before += text;
        }
    }
    if (!arrow) {
        return null;
    }
    const flat = squash(before);
    const cut = flat.indexOf(" :");
    const name = cut === -1 ? flat.replace(/:\s*$/, "") : flat.slice(0, cut);
    const old = cut === -1 ? "" : flat.slice(cut + 2);
    return { name: squash(name), old: squash(old), new: squash(after) };
}

/** Одна строка позиции: «<b>Добавлено:</b> Доборка 5 [<ul> изменения </ul>]». */
function parseItem(ul) {
    const parts = kids(ul);
    const label = parts.find((n) => tag(n) === "b");
    if (!label) {
        return null;
    }
    const mode = modeOf(label.textContent);
    if (!mode) {
        return null;
    }
    let record = "";
    const changes = [];
    for (const node of parts) {
        if (node === label) {
            continue;
        }
        if (node.nodeType === TEXT) {
            record += node.textContent;
        } else if (tag(node) === "ul") {
            for (const li of elements(node)) {
                if (tag(li) !== "li") {
                    return null;
                }
                const change = parseChange(li);
                if (!change) {
                    return null;
                }
                changes.push(change);
            }
        } else {
            record += node.textContent || "";
        }
    }
    return { mode, record: squash(record), changes };
}

/** Поле: «<li><b>Изделия: </b><br/><ul>…</ul><ul>…</ul></li>». */
function parseField(li) {
    const parts = elements(li);
    const head = parts[0];
    if (tag(head) !== "b") {
        return null;
    }
    const field = squash(head.textContent).replace(/\s*:\s*$/, "");
    if (!field) {
        return null;
    }
    const items = [];
    for (const node of parts.slice(1)) {
        if (tag(node) === "br") {
            continue;
        }
        if (tag(node) !== "ul") {
            return null;
        }
        const item = parseItem(node);
        if (!item) {
            return null;
        }
        items.push(item);
    }
    // Текст между узлами поля — только пробелы.
    if (kids(li).some((n) => n.nodeType === TEXT && squash(n.textContent))) {
        return null;
    }
    return items.length ? { field, items } : null;
}

/**
 * Разбор записи vendor/tracking_manager — изменения строк (изделия,
 * позиции доборки): `div > ul > li > b` с именем поля, затем по одному `ul`
 * на строку. Узлы — DOM или похожие объекты (nodeType, tagName,
 * childNodes, textContent). Вид другой — null: тогда запись показывается как
 * есть, списком.
 */
export function tmTree(root) {
    let node = root;
    // Обёртки: div от createElementWithContent и div шаблона.
    for (let i = 0; i < 3; i++) {
        const els = elements(node);
        const loose = kids(node).some((n) => n.nodeType === TEXT && squash(n.textContent));
        if (els.length === 1 && tag(els[0]) === "div" && !loose) {
            node = els[0];
        } else {
            break;
        }
    }
    const lists = elements(node);
    if (!lists.length || lists.some((n) => tag(n) !== "ul")
        || kids(node).some((n) => n.nodeType === TEXT && squash(n.textContent))) {
        return null;
    }
    const fields = [];
    for (const ul of lists) {
        for (const li of elements(ul)) {
            if (tag(li) !== "li") {
                return null;
            }
            const field = parseField(li);
            if (!field) {
                return null;
            }
            fields.push(field);
        }
    }
    return fields.length ? fields : null;
}

/**
 * Строки таблицы из разбора tracking_manager — по одной позиции на строку:
 *   добавлено → «Изделия: добавлено | — | Ферма Ф-1»;
 *   удалено   → «Изделия: удалено | Ферма Ф-1 | —»;
 *   изменено  → по строке на каждое изменение: «Изделия: Ферма Ф-1 —
 *               Детали | 12 | 13»; без изменений — «Изделия: изменено | — |
 *               Ферма Ф-1».
 */
export function tmRows(tree) {
    const rows = [];
    for (const { field, items } of tree || []) {
        for (const item of items) {
            if (item.mode === "create") {
                rows.push({ field: `${field}: добавлено`, old: EMPTY_CELL, new: cellText(item.record) });
            } else if (item.mode === "unlink") {
                rows.push({ field: `${field}: удалено`, old: cellText(item.record), new: EMPTY_CELL });
            } else if (item.changes.length) {
                for (const change of item.changes) {
                    const what = [item.record, change.name].filter(Boolean).join(" — ");
                    rows.push({ field: `${field}: ${what}`, old: cellText(change.old), new: cellText(change.new) });
                }
            } else {
                rows.push({ field: `${field}: изменено`, old: EMPTY_CELL, new: cellText(item.record) });
            }
        }
    }
    return rows;
}
