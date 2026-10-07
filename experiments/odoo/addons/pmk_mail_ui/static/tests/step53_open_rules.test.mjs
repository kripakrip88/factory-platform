// Шаг 53 разбора удобства (07.10.2026): какой ящик и какое письмо почта
// открывает первыми.
//
// Запуск из корня репозитория (нужен только node, без браузера и Odoo):
//   node experiments/odoo/addons/pmk_mail_ui/static/tests/step53_open_rules.test.mjs
// Проверяется модуль правил рядом — ../src/js/step53_open_rules.js (чистые
// функции без импортов Odoo). Файл .mjs сборщик ассетов не берёт.
import assert from "node:assert/strict";

const rules = await import(new URL("../src/js/step53_open_rules.js", import.meta.url).href);
const { normEmail, openParams, hasFolder, inboxOf, pickFolder } = rules;

let n = 0;
function t(name, fn) {
    fn();
    n++;
    console.log("ok -", name);
}

// Как на бою: заявки первыми по порядку, закупки вторыми.
const ACCOUNTS = [
    {
        id: 2, email: "pmkpark@mail.ru",
        folders: [{ id: 21, role: "inbox" }, { id: 22, role: "sent" }],
    },
    {
        id: 1, email: "zakaz@pmkpark.ru",
        folders: [{ id: 11, role: "inbox" }, { id: 12, role: "sent" }, { id: 13, role: "spam" }],
    },
];

t("параметры действия: адрес без регистра, номер письма числом", () => {
    assert.deepEqual(openParams({ pmk_mailbox: " Zakaz@PMKpark.ru ", pmk_message_id: "75" }), {
        mailbox: "zakaz@pmkpark.ru", messageId: 75, folderId: null, asked: false,
    });
    assert.deepEqual(openParams(undefined), { mailbox: "", messageId: 0, folderId: null, asked: false });
    assert.equal(openParams({ pmk_message_id: "мусор" }).messageId, 0);
    assert.equal(openParams({ pmk_message_id: -4 }).messageId, 0);
    assert.equal(normEmail(null), "");
});

t("Закупки → ящик закупок, Продажи → заявки", () => {
    assert.equal(pickFolder(ACCOUNTS, openParams({ pmk_mailbox: "zakaz@pmkpark.ru" })), 11);
    assert.equal(pickFolder(ACCOUNTS, openParams({ pmk_mailbox: "pmkpark@mail.ru", pmk_crm: true })), 21);
});

t("регистр адреса в ящике не мешает", () => {
    const accounts = [{ id: 1, email: "ZAKAZ@pmkpark.RU", folders: [{ id: 5, role: "inbox" }] }];
    assert.equal(pickFolder(accounts, openParams({ pmk_mailbox: "zakaz@pmkpark.ru" })), 5);
});

t("письмо со «Связей»: его папка — первой, даже из другого ящика", () => {
    const open = { ...openParams({ pmk_mailbox: "pmkpark@mail.ru", pmk_message_id: 7 }), folderId: 12 };
    assert.equal(pickFolder(ACCOUNTS, open), 12);
});

t("папки письма нет в дереве — ящик по адресу", () => {
    const open = { ...openParams({ pmk_mailbox: "zakaz@pmkpark.ru", pmk_message_id: 7 }), folderId: 999 };
    assert.equal(hasFolder(ACCOUNTS, 999), false);
    assert.equal(pickFolder(ACCOUNTS, open), 11);
});

t("ящика с таким адресом у человека нет — решает модуль почты (null)", () => {
    assert.equal(pickFolder(ACCOUNTS, openParams({ pmk_mailbox: "nobody@example.org" })), null);
    assert.equal(pickFolder(ACCOUNTS, openParams({})), null);
    assert.equal(pickFolder([], openParams({ pmk_mailbox: "zakaz@pmkpark.ru" })), null);
    assert.equal(pickFolder(ACCOUNTS, null), null);
});

t("«Входящих» нет — первая папка ящика, папок нет — null", () => {
    assert.equal(inboxOf({ folders: [{ id: 3, role: "other" }, { id: 4, role: "sent" }] }), 3);
    assert.equal(inboxOf({ folders: [] }), null);
    assert.equal(inboxOf(undefined), null);
    const accounts = [{ id: 9, email: "x@example.org", folders: [] }];
    assert.equal(pickFolder(accounts, openParams({ pmk_mailbox: "x@example.org" })), null);
});

t("hasFolder: пустой номер — нет", () => {
    assert.equal(hasFolder(ACCOUNTS, null), false);
    assert.equal(hasFolder(ACCOUNTS, 0), false);
    assert.equal(hasFolder(undefined, 11), false);
    assert.equal(hasFolder(ACCOUNTS, 13), true);
});

console.log(`${n} проверок пройдено`);
