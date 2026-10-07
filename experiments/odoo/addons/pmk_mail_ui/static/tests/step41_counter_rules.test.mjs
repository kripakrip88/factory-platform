// Шаг 41 разбора удобства (05.10.2026): счётчик новых писем (Г12).
//
// Запуск из корня репозитория (нужен только node, без браузера и Odoo):
//   node experiments/odoo/addons/pmk_mail_ui/static/tests/step41_counter_rules.test.mjs
// Проверяется модуль правил рядом — ../src/js/mail_counter_rules.js (чистые
// функции без импортов Odoo). Файл .mjs сборщик ассетов не берёт.
import assert from "node:assert/strict";

const rules = await import(new URL("../src/js/mail_counter_rules.js", import.meta.url).href);
const { counterText, counterTitle, shouldRefresh, MAIL_MENU_XMLID, COUNTER_DAYS } = rules;
const { MAIL_MENUS, PURCHASE_MAIL_MENU_XMLID, menuCounts } = rules;

let n = 0;
function t(name, fn) {
    fn();
    n++;
    console.log("ok -", name);
}

t("число на пункте: пусто при нуле, дальше 99 — «99+»", () => {
    assert.equal(counterText(0), "");
    assert.equal(counterText(-3), "");
    assert.equal(counterText(undefined), "");
    assert.equal(counterText(3), "3");
    assert.equal(counterText(99), "99");
    assert.equal(counterText(101), "99+");
});

t("подсказка — словами и с окном в 30 дней", () => {
    assert.equal(COUNTER_DAYS, 30);
    assert.equal(counterTitle(0), "");
    assert.equal(counterTitle(101), "Непрочитанных во «Входящих» за 30 дней: 101");
});

t("сигнал синхронизации: перечитать, только если проход что-то изменил", () => {
    assert.equal(shouldRefresh({ changed: true, folder_ids: [6] }), true);
    assert.equal(shouldRefresh({ changed: false }), false);
    assert.equal(shouldRefresh({ account_id: 2 }), true, "старый сервер без changed");
    assert.equal(shouldRefresh(null), true);
});

t("пункт меню — «Продажи → Почта»", () => {
    assert.equal(MAIL_MENU_XMLID, "pmk_mail_ui.menu_mail_sale");
});

t("шаг 53: у каждого пункта «Почта» — число своего ящика", () => {
    assert.equal(PURCHASE_MAIL_MENU_XMLID, "pmk_mail_ui.menu_mail_purchase");
    assert.deepEqual(MAIL_MENUS, [MAIL_MENU_XMLID, PURCHASE_MAIL_MENU_XMLID]);
    assert.deepEqual(
        menuCounts({ "pmk_mail_ui.menu_mail_sale": 1, "pmk_mail_ui.menu_mail_purchase": "2" }, 3),
        { "pmk_mail_ui.menu_mail_sale": 1, "pmk_mail_ui.menu_mail_purchase": 2 }
    );
    assert.deepEqual(
        menuCounts({ "pmk_mail_ui.menu_mail_sale": -1, chuzhoi: 9 }, 0),
        { "pmk_mail_ui.menu_mail_sale": 0, "pmk_mail_ui.menu_mail_purchase": 0 },
        "мусор — ноль, чужие ключи не берутся"
    );
});

t("старый сервер без разбивки: число — на Продажах, у Закупок пусто", () => {
    assert.deepEqual(menuCounts(undefined, 5), {
        "pmk_mail_ui.menu_mail_sale": 5,
        "pmk_mail_ui.menu_mail_purchase": 0,
    });
    assert.deepEqual(menuCounts(null), {
        "pmk_mail_ui.menu_mail_sale": 0,
        "pmk_mail_ui.menu_mail_purchase": 0,
    });
});

console.log(`\n${n} проверок прошло`);
