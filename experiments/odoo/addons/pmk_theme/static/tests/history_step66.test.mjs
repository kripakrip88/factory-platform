// Шаг 66 разбора UX: окно «История» как «История изменений» МоегоСклада —
// правила без Odoo.
//
// Запуск из корня репозитория (нужен только node, без браузера и Odoo):
//   node experiments/odoo/addons/pmk_theme/static/tests/history_step66.test.mjs
// Проверяется модуль ../src/js/history_rules.js (чистые функции без импортов
// Odoo). Другой файл — переменная PMK_RULES. Файл не попадает ни в один
// бандл: ассеты в манифесте pmk_theme перечислены поимённо.
//
// Тела сообщений — настоящие, с боевой базы (номера mail_message в
// подписях): так видно, что разбор держит то, что реально лежит в ленте.
import assert from "node:assert/strict";

const RULES = process.env.PMK_RULES
    || new URL("../src/js/history_rules.js", import.meta.url).href;
const {
    SYSTEM_AUTHOR,
    EMPTY_CELL,
    TABLE_HEAD,
    ACTIONS,
    shortName,
    emailName,
    authorLabel,
    stampText,
    headLine,
    plainText,
    isCreationText,
    isActivityDoneBody,
    actionWord,
    subtypeLine,
    cellText,
    trackingRows,
    TM_MODES,
    tmTree,
    tmRows,
} = await import(RULES);

let n = 0;
function t(name, fn) { fn(); n++; console.log("ok -", name); }

// ─── Мини-разбор HTML в узлы без DOM: nodeType, tagName, childNodes, textContent.
const VOID = new Set(["br", "img", "hr", "input", "meta", "link"]);
function decode(text) {
    return text.replace(/&nbsp;/g, " ").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
        .replace(/&quot;/g, '"').replace(/&amp;/g, "&");
}
function textNode(text) {
    return { nodeType: 3, textContent: decode(text), childNodes: [] };
}
function elementNode(tagName) {
    const node = { nodeType: 1, tagName: tagName.toUpperCase(), childNodes: [] };
    Object.defineProperty(node, "textContent", {
        get() { return node.childNodes.map((c) => c.textContent).join(""); },
    });
    return node;
}
function parse(html) {
    const root = elementNode("div");
    const stack = [root];
    const re = /<\/?([a-zA-Z0-9]+)[^>]*?(\/?)>|([^<]+)/g;
    let m;
    while ((m = re.exec(html))) {
        const top = stack[stack.length - 1];
        if (m[3] !== undefined) {
            top.childNodes.push(textNode(m[3]));
        } else if (m[0].startsWith("</")) {
            const name = m[1].toLowerCase();
            while (stack.length > 1) {
                const el = stack.pop();
                if (el.tagName.toLowerCase() === name) {
                    break;
                }
            }
        } else {
            const el = elementNode(m[1]);
            top.childNodes.push(el);
            if (!m[2] && !VOID.has(m[1].toLowerCase())) {
                stack.push(el);
            }
        }
    }
    return root;
}

// ─── Тела tracking_manager с боевой базы ─────────────────────────────────
const ARROW = '<div class="o_Message_trackingValueSeparator o_Message_trackingValueItem fa fa-long-arrow-right" title="Изменено"></div>';

// 2793 — два «Добавлено» в изделиях расчёта.
const BODY_2793 = `<div>
            <ul>
                    <li>
                        <b>
                            Изделия: </b>
                        <br>
                            <ul>
                                    <b>Добавлено:</b>
                                до 3мм
                            </ul>
                            <ul>
                                    <b>Добавлено:</b>
                                2
                            </ul>
                    </li>
            </ul>
        </div>`;

// 2302 — «Изменено» с двумя полями строки.
const BODY_2302 = `<div>
            <ul>
                    <li>
                        <b>
                            Изделия: </b>
                        <br>
                            <ul>
                                    <b>Изменено:</b>
                                Ферма Ф-1 пролёт 6 м
                                    <ul>
                                            <li>
                                                Детали :
                                                12
                                                ${ARROW}
                                                13
                                            </li>
                                            <li>
                                                Прокат :
                                                6
                                                ${ARROW}
                                                7
                                            </li>
                                    </ul>
                            </ul>
                    </li>
            </ul>
        </div>`;

// 2291 — доборка: добавлено и изменено с пустым «Было».
const BODY_2291 = `<div>
            <ul>
                    <li>
                        <b>
                            Доборки: </b>
                        <br>
                            <ul>
                                    <b>Добавлено:</b>
                                Доборка 5
                            </ul>
                            <ul>
                                    <b>Изменено:</b>
                                Доборка 5
                                    <ul>
                                            <li>
                                                Название доборки :

                                                ${ARROW}
                                                Доборка 5
                                            </li>
                                    </ul>
                            </ul>
                    </li>
            </ul>
        </div>`;

// Исходный английский шаблон (до перевода i18n_extra) и удаление.
const BODY_EN = `<div><ul><li><b>Lines: </b><br>
    <ul><b>New :</b> Line A</ul>
    <ul><b>Delete :</b> Line B</ul>
</li></ul></div>`;

// Выполненная задача, 2758 (шаблон ядра mail.message_activity_done).
const BODY_DONE = `<div>
    <p>
        <span class="fa fa-check-square-o fa-fw"></span><span>Согласовать счёт</span> выполнено
        <span>: </span><span>Согласовать счёт</span>
    </p>
        <div class="o_mail_note_title fw-bold">Исходная заметка:</div>
        <div><p>Счёт СЧ-00021 на 2&nbsp;515&nbsp;500,00&nbsp;руб ждёт согласования.</p></div>
</div>`;

// ─── Автор ───────────────────────────────────────────────────────────────
t("константы", () => {
    assert.equal(SYSTEM_AUTHOR, "Система");
    assert.equal(EMPTY_CELL, "—");
    assert.deepEqual([...TABLE_HEAD], ["Поле", "Было", "Стало"]);
    assert.throws(() => TABLE_HEAD.push("x"), "шапка заморожена");
    assert.deepEqual({ ...ACTIONS }, {
        email: "письмо",
        activityDone: "задача выполнена",
        created: "создано",
        changed: "изменено",
        note: "заметка",
        other: "запись",
    });
});

t("краткое имя «Фамилия И.»", () => {
    assert.equal(shortName("Антон Карнеев"), "Карнеев А.");
    assert.equal(shortName("Владимир Голубенко"), "Голубенко В.");
    assert.equal(shortName("Игорь Бутов"), "Бутов И.");
    assert.equal(shortName("Ирина Кузнецова"), "Кузнецова И.");
    assert.equal(shortName("Кытманова Мария"), "Кытманова М.", "фамилия первой");
    assert.equal(shortName("Валентин Ким"), "Ким В.", "имя с окончанием фамилии");
    assert.equal(shortName("Кузнецов Алексей Владимирович"), "Кузнецов А.");
    assert.equal(shortName("Гуль Александр Геннадьевич"), "Гуль А.");
    assert.equal(shortName("Алексей Владимирович Кузнецов"), "Кузнецов А.");
    assert.equal(shortName("Пётр Ильич Чайковский"), "Чайковский П.");
    // Фамилия без фамильного окончания — рядом с известным именем.
    assert.equal(shortName("Ким Ирина"), "Ким И.", "не «Ирина К.»");
    assert.equal(shortName("Ким Валентин"), "Ким В.", "не «Валентин К.»");
    assert.equal(shortName("Гуль Александр"), "Гуль А.", "не «Александр Г.»");
    assert.equal(shortName("Александр Гуль"), "Гуль А.");
});

t("краткое имя: фамилию не опознать — как есть, порядок не угадываем", () => {
    // Названия компаний с боевой без ООО/кавычек — проверено на реестре.
    assert.equal(shortName("Восток Маркет"), "Восток Маркет");
    assert.equal(shortName("Частный заказ"), "Частный заказ");
    assert.equal(shortName("Металл Сервис"), "Металл Сервис");
    assert.equal(shortName("Металлсервис Хабаровск"), "Металлсервис Хабаровск");
    // Слово заглавными — сокращение, это название.
    assert.equal(shortName("УК БСМ"), "УК БСМ", "«УК» не фамилия на -ук");
    assert.equal(shortName("ПМК Парк"), "ПМК Парк");
    assert.equal(shortName("Цех ПМК Парк"), "Цех ПМК Парк");
});

t("краткое имя: организация (is_company) — как есть", () => {
    assert.equal(shortName("Восток Маркет", { isCompany: true }), "Восток Маркет");
    assert.equal(shortName("Карнеев Групп", { isCompany: true }), "Карнеев Групп", "фамилия в названии");
    assert.equal(shortName("Антон Карнеев", { isCompany: false }), "Карнеев А.");
});

t("краткое имя: как есть", () => {
    assert.equal(shortName("Оксана"), "Оксана", "одно слово");
    assert.equal(shortName("OdooBot"), "OdooBot");
    assert.equal(shortName("ООО «ЦКС»"), "ООО «ЦКС»");
    assert.equal(shortName("ИП Чулков"), "ИП Чулков");
    assert.equal(shortName("zakaz@pmkpark.ru"), "zakaz@pmkpark.ru");
    assert.equal(shortName("Отдел 2 продаж"), "Отдел 2 продаж", "цифры");
    assert.equal(shortName("Анна Мария Луиза Фон"), "Анна Мария Луиза Фон", "четыре слова");
    assert.equal(shortName("  Антон   Карнеев "), "Карнеев А.", "лишние пробелы");
    assert.equal(shortName(""), "");
    assert.equal(shortName(null), "");
});

t("имя из адреса письма", () => {
    assert.equal(emailName('"Оксана" <oksana@cks1.ru>'), "Оксана");
    assert.equal(emailName("Оксана Петрова <oksana@cks1.ru>"), "Оксана Петрова");
    assert.equal(emailName("<oksana@cks1.ru>"), "oksana@cks1.ru");
    assert.equal(emailName("oksana@cks1.ru"), "oksana@cks1.ru");
    assert.equal(emailName(""), "");
});

t("автор события", () => {
    assert.equal(authorLabel({ hasAuthor: true, isSystem: true, name: "OdooBot" }), "Система");
    assert.equal(authorLabel({ hasAuthor: false, name: "", emailFrom: "" }), "Система", "ни автора, ни адреса");
    assert.equal(authorLabel({}), "Система");
    assert.equal(authorLabel({ hasAuthor: true, name: "Антон Карнеев" }), "Карнеев А.");
    assert.equal(authorLabel({ hasAuthor: false, emailFrom: '"Оксана Петрова" <o@cks1.ru>' }), "Петрова О.");
    assert.equal(authorLabel({ hasAuthor: false, emailFrom: '"Оксана" <o@cks1.ru>' }), "Оксана");
    assert.equal(authorLabel({ hasAuthor: false, emailFrom: "o@cks1.ru" }), "o@cks1.ru");
    assert.equal(authorLabel({ hasAuthor: true, name: "" }), "Система");
    // Письмо от контрагента-организации: author_id = компания, найденная по адресу.
    assert.equal(authorLabel({ hasAuthor: true, isCompany: true, name: "УК БСМ" }), "УК БСМ");
    assert.equal(authorLabel({ hasAuthor: true, isCompany: true, name: "Восток Маркет" }), "Восток Маркет");
    assert.equal(authorLabel({ hasAuthor: true, isCompany: true, name: "Металл Сервис" }), "Металл Сервис");
    assert.equal(authorLabel({ hasAuthor: true, isCompany: false, name: "Антон Карнеев" }), "Карнеев А.");
});

// ─── Дата и заголовок ────────────────────────────────────────────────────
t("дата и время числами", () => {
    assert.equal(stampText({ year: 2026, month: 10, day: 8, hour: 22, minute: 5 }), "08.10.2026 22:05");
    assert.equal(stampText({ year: 2026, month: 1, day: 1, hour: 0, minute: 0 }), "01.01.2026 00:00");
    assert.equal(stampText(null), "");
    assert.equal(stampText({}), "");
});

t("заголовок события", () => {
    assert.equal(headLine({ author: "Карнеев А.", action: "изменено", stamp: "08.10.2026 22:48" }),
        "Карнеев А., изменено 08.10.2026 22:48");
    assert.equal(headLine({ author: "", action: "создано", stamp: "" }), "Система, создано");
    assert.equal(headLine({ author: "Бутов И." }), "Бутов И., запись");
});

// ─── Действие словом ─────────────────────────────────────────────────────
t("текст без разметки", () => {
    assert.equal(plainText("<p>Счёт на 2&nbsp;515 руб</p>"), "Счёт на 2 515 руб");
    assert.equal(plainText(""), "");
    assert.equal(plainText(null), "");
});

t("создание записи", () => {
    assert.ok(isCreationText("Создано: Расчёт металлопроката"));
    assert.ok(isCreationText("Создано: Заказ вентзонтов"));
    assert.ok(isCreationText("Для команды \"Продажи\" создан новый лид."));
    assert.ok(isCreationText("В проекте «Доработка системы» создана новая задача."));
    assert.ok(isCreationText("Sale Order has been created"));
    assert.ok(isCreationText("", "Сделка создана"));
    assert.ok(!isCreationText("Цены перечитаны: 12 позиций"));
    assert.ok(!isCreationText("Из Телеграма: созданы чертежи?"), "не начало и не «создан нов…»");
    // Без шаблонов по тексту (запись не системная) — только подтип.
    assert.ok(!isCreationText("Создан новый расчёт", "", { textRules: false }));
    assert.ok(!isCreationText("Создано: Расчёт", "", { textRules: false }));
    assert.ok(isCreationText("Создан новый расчёт", "Сделка создана", { textRules: false }));
});

t("выполненная задача", () => {
    assert.ok(isActivityDoneBody(BODY_DONE));
    assert.ok(!isActivityDoneBody("<p>Согласовать счёт выполнено</p>"), "нужен значок ядра");
    assert.ok(!isActivityDoneBody(""));
});

t("действие по типу сообщения", () => {
    const html = (s) => ({ bodyHtml: s, bodyText: plainText(s) });
    // 2841 — создано нашим переводом tracking_manager
    assert.equal(actionWord({ messageType: "notification", isNote: true, ...html("<p>Создано: Расчёт металлопроката</p>") }),
        "создано");
    // лид из письма: подтип «Сделка создана»
    assert.equal(actionWord({ messageType: "notification", ...html("<p>Для команды \"Продажи\" создан новый лид.</p>"),
        subtypeDescription: "Сделка создана" }), "создано");
    assert.equal(actionWord({ messageType: "notification", isNote: false, ...html(BODY_DONE) }), "задача выполнена");
    assert.equal(actionWord({ messageType: "notification", hasTracking: true, ...html("") }), "изменено");
    assert.equal(actionWord({ messageType: "notification", isNote: true, hasX2m: true, ...html(BODY_2793) }), "изменено");
    // «Этап изменен» — изменение с подтипом
    assert.equal(actionWord({ messageType: "notification", hasTracking: true, subtypeDescription: "Этап изменен",
        ...html("") }), "изменено");
    assert.equal(actionWord({ messageType: "comment", isNote: true, ...html("<p>Из Телеграма: звонил клиент</p>") }),
        "заметка");
    // Заметка человека про создание — заметка: шаблоны по тексту только у системных записей.
    assert.equal(actionWord({ messageType: "comment", isNote: true,
        ...html("<p>Создан новый расчёт для клиента, жду цены</p>") }), "заметка");
    assert.equal(actionWord({ messageType: "comment", isNote: true, ...html("<p>Создано: черновик КП</p>") }),
        "заметка");
    assert.equal(actionWord({ messageType: "comment", isNote: true,
        ...html("<p>Order has been created by client</p>") }), "заметка");
    // 2819 — лид из письма: первое событие — само письмо с подтипом «Сделка создана».
    assert.equal(actionWord({ messageType: "email", subtypeDescription: "Сделка создана",
        ...html("<p>Прошу рассчитать</p>") }), "письмо");
    assert.equal(actionWord({ messageType: "notification", isNote: true, ...html("<p>Цены перечитаны: 12 позиций</p>") }),
        "запись");
    assert.equal(actionWord({ messageType: "email", ...html("<p>Добрый день, создан новый запрос</p>") }), "письмо",
        "письмо — раньше «создано»");
    assert.equal(actionWord({ messageType: "email_outgoing", ...html("<p>КП во вложении</p>") }), "письмо");
    assert.equal(actionWord({ messageType: "comment", isDiscussion: true, ...html("<p>КП во вложении</p>") }), "письмо");
    assert.equal(actionWord({ messageType: "user_notification", ...html("<p>Вам назначено</p>") }), "запись");
    assert.equal(actionWord({}), "запись");
});

t("описание подтипа строкой", () => {
    assert.equal(subtypeLine({ action: "изменено", description: "Этап изменен" }), "Этап изменен");
    assert.equal(subtypeLine({ action: "запись", description: "Сделка выиграна" }), "Сделка выиграна");
    assert.equal(subtypeLine({ action: "создано", description: "Сделка создана" }), "", "заголовок уже говорит «создано»");
    assert.equal(subtypeLine({ action: "письмо", description: "Счёт отправлен" }), "");
    assert.equal(subtypeLine({ action: "письмо", description: "Сделка создана" }), "Сделка создана",
        "лид из письма: создание видно строкой под «письмо»");
    assert.equal(subtypeLine({ action: "запись", description: "Счёт отправлен", bodyText: "счёт отправлен" }), "",
        "совпадает с текстом — как у ядра");
    assert.equal(subtypeLine({ action: "запись", description: "" }), "");
});

// ─── Таблица ─────────────────────────────────────────────────────────────
t("ячейка", () => {
    assert.equal(cellText(0), "0");
    assert.equal(cellText("0,00 руб"), "0,00 руб");
    assert.equal(cellText(false), "—");
    assert.equal(cellText(null), "—");
    assert.equal(cellText(undefined), "—");
    assert.equal(cellText(""), "—");
    assert.equal(cellText("   "), "—");
    // ru_RU: разряды и «руб» — через неразрывный пробел (formatMonetary).
    assert.equal(cellText("9\u00a0500\u00a0000,00\u00a0руб"), "9\u00a0500\u00a0000,00 руб",
        "перед «руб» — обычный пробел, разряды не рвутся");
    assert.equal(cellText("0,00\u00a0руб"), "0,00 руб");
    assert.equal(cellText("12\u00a0шт"), "12 шт");
    assert.equal(cellText("Ферма\u00a0Ф-1"), "Ферма\u00a0Ф-1", "не число — не трогаем");
    assert.equal(cellText("1\u00a0500"), "1\u00a0500", "число без единицы — как есть");
});

t("строки изменений полей", () => {
    assert.deepEqual(trackingRows([
        { field: "Цена клиенту", old: "0,00 руб", new: "9 500 000,00 руб" },
        { field: "Ответственный", old: "", new: "Антон Карнеев" },
        { field: "Этап", old: "Новая", new: false },
    ]), [
        { field: "Цена клиенту", old: "0,00 руб", new: "9 500 000,00 руб" },
        { field: "Ответственный", old: "—", new: "Антон Карнеев" },
        { field: "Этап", old: "Новая", new: "—" },
    ]);
    assert.deepEqual(trackingRows(null), []);
});

t("метки tracking_manager", () => {
    assert.equal(TM_MODES["добавлено"], "create");
    assert.equal(TM_MODES["удалено"], "unlink");
    assert.equal(TM_MODES["изменено"], "update");
    assert.equal(TM_MODES["new"], "create");
    assert.equal(TM_MODES["delete"], "unlink");
    assert.equal(TM_MODES["change"], "update");
});

t("разбор 2793: два «Добавлено»", () => {
    const tree = tmTree(parse(BODY_2793));
    assert.deepEqual(tree, [{ field: "Изделия", items: [
        { mode: "create", record: "до 3мм", changes: [] },
        { mode: "create", record: "2", changes: [] },
    ] }]);
    assert.deepEqual(tmRows(tree), [
        { field: "Изделия: добавлено", old: "—", new: "до 3мм" },
        { field: "Изделия: добавлено", old: "—", new: "2" },
    ]);
});

t("разбор 2302: «Изменено» с двумя полями", () => {
    const tree = tmTree(parse(BODY_2302));
    assert.equal(tree.length, 1);
    assert.deepEqual(tree[0].items[0].changes, [
        { name: "Детали", old: "12", new: "13" },
        { name: "Прокат", old: "6", new: "7" },
    ]);
    assert.deepEqual(tmRows(tree), [
        { field: "Изделия: Ферма Ф-1 пролёт 6 м — Детали", old: "12", new: "13" },
        { field: "Изделия: Ферма Ф-1 пролёт 6 м — Прокат", old: "6", new: "7" },
    ]);
});

t("разбор 2291: добавлено и изменено с пустым «Было»", () => {
    assert.deepEqual(tmRows(tmTree(parse(BODY_2291))), [
        { field: "Доборки: добавлено", old: "—", new: "Доборка 5" },
        { field: "Доборки: Доборка 5 — Название доборки", old: "—", new: "Доборка 5" },
    ]);
});

t("разбор: английские метки, удаление, изменено без полей", () => {
    assert.deepEqual(tmRows(tmTree(parse(BODY_EN))), [
        { field: "Lines: добавлено", old: "—", new: "Line A" },
        { field: "Lines: удалено", old: "Line B", new: "—" },
    ]);
    assert.deepEqual(tmRows([{ field: "Изделия", items: [{ mode: "update", record: "Ферма", changes: [] }] }]),
        [{ field: "Изделия: изменено", old: "—", new: "Ферма" }]);
    assert.deepEqual(tmRows(null), []);
});

t("разбор: запятые в названии изделия не режут строку", () => {
    const body = `<div><ul><li><b>Изделия: </b><br><ul><b>Добавлено:</b>
        Профиль П-образный 30×60, стенка 3 мм, L=3000</ul></li></ul></div>`;
    assert.deepEqual(tmRows(tmTree(parse(body))), [
        { field: "Изделия: добавлено", old: "—", new: "Профиль П-образный 30×60, стенка 3 мм, L=3000" },
    ]);
});

t("разбор: чужой вид — null (запись как есть)", () => {
    assert.equal(tmTree(parse("<p>текст</p>")), null);
    assert.equal(tmTree(parse("<p>Создано: Расчёт металлопроката</p>")), null);
    assert.equal(tmTree(parse(BODY_DONE)), null);
    assert.equal(tmTree(parse("<ul><li>просто список</li></ul>")), null);
    assert.equal(tmTree(parse("<div><ul><li><b>Изделия: </b><br><ul><b>Перенесено:</b> X</ul></li></ul></div>")),
        null, "незнакомая метка");
    assert.equal(tmTree(parse("<div>Изделия<ul><li><b>Изделия: </b><br><ul><b>Добавлено:</b> X</ul></li></ul></div>")),
        null, "лишний текст рядом со списком");
    assert.equal(tmTree(parse("")), null);
    assert.equal(tmTree(null), null);
});

console.log(`\n${n} проверок — все прошли`);
