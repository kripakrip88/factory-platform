// Шаг 65 разбора UX: «История» кнопкой в строке пути — правила без Odoo.
//
// Запуск из корня репозитория (нужен только node, без браузера и Odoo):
//   node experiments/odoo/addons/pmk_theme/static/tests/doc_tools_step65.test.mjs
// Проверяется модуль ../src/js/doc_tools_rules.js (чистые функции без
// импортов Odoo). Другой файл — переменная PMK_RULES. Файл не попадает ни в
// один бандл: ассеты в манифесте pmk_theme перечислены поимённо.
import assert from "node:assert/strict";

const RULES = process.env.PMK_RULES
    || new URL("../src/js/doc_tools_rules.js", import.meta.url).href;
const {
    TOOL_TEMPLATES,
    FILES_PAGE,
    HIDE_FLAG_EXPR,
    hideChatterIf,
    shouldMoveChatter,
    chatterNodeOf,
    chatterAttrs,
    hasFilesPage,
    countLabel,
    historyTooltip,
    filesTooltip,
    dialogTitle,
    activityCounts,
    shouldFetchAttachments,
} = await import(RULES);

let n = 0;
function t(name, fn) { fn(); n++; console.log("ok -", name); }

// Узел разметки без DOM: tagName, children, getAttribute.
function el(tagName, attrs = {}, children = []) {
    return { tagName, children, getAttribute: (k) => (k in attrs ? attrs[k] : null) };
}

t("шаблоны со слотом значка", () => {
    assert.deepEqual([...TOOL_TEMPLATES], [
        "web.FormView",
        "resource.FormViewWithHtmlExpander",
        "project.ProjectTaskFormView",
        "project.ProjectFormView",
    ]);
    assert.throws(() => TOOL_TEMPLATES.push("x"), "список заморожен");
    assert.equal(FILES_PAGE, "pmk_files");
});

t("условие ленты — прежнее И не вынесена", () => {
    assert.equal(HIDE_FLAG_EXPR, "__comp__.env.pmkHideChatter");
    assert.equal(hideChatterIf("!__comp__.env.inDialog"),
        "(!__comp__.env.inDialog) and !__comp__.env.pmkHideChatter");
    // mail для ленты под листом — «t-if and (раскладка)»: скобки сохраняют смысл
    const mail = 'true and (!["COMBO", "NONE"].includes(__comp__.mailLayout(false)))';
    assert.equal(hideChatterIf(mail), `(${mail}) and !__comp__.env.pmkHideChatter`);
    assert.equal(hideChatterIf(""), "(true) and !__comp__.env.pmkHideChatter");
    assert.equal(hideChatterIf(null), "(true) and !__comp__.env.pmkHideChatter");
});

t("когда лента уходит из формы", () => {
    const base = {
        chatterInForm: false, inDialog: false, controlPanel: true,
        hasChatter: true, hasStore: true, template: "web.FormView",
    };
    assert.equal(shouldMoveChatter(base), true);
    for (const template of TOOL_TEMPLATES) {
        assert.equal(shouldMoveChatter({ ...base, template }), true, template);
    }
    assert.equal(shouldMoveChatter({ ...base, chatterInForm: true }), false, "выключатель «Убранное»");
    assert.equal(shouldMoveChatter({ ...base, inDialog: true }), false, "окно — как было");
    assert.equal(shouldMoveChatter({ ...base, controlPanel: false }), false, "без строки пути");
    assert.equal(shouldMoveChatter({ ...base, hasChatter: false }), false, "формы без ленты");
    assert.equal(shouldMoveChatter({ ...base, hasStore: false }), false);
    assert.equal(shouldMoveChatter({ ...base, template: "web.SettingsFormView" }), false,
        "чужой шаблон без слота — лента остаётся под формой");
    assert.equal(shouldMoveChatter(), false);
});

t("узел ленты — в форме или в листе, не во вложенной форме", () => {
    const direct = el("chatter", { reload_on_activity: "1" });
    assert.equal(chatterNodeOf(el("form", {}, [el("sheet"), direct])), direct);
    const inSheet = el("chatter");
    assert.equal(chatterNodeOf(el("form", {}, [el("sheet", {}, [el("group"), inSheet])])), inSheet);
    const nested = el("form", {}, [el("sheet", {}, [el("field", {}, [el("form", {}, [el("chatter")])])])]);
    assert.equal(chatterNodeOf(nested), null);
    assert.equal(chatterNodeOf(null), null);
    // XML-узел: tagName может прийти в любом регистре
    assert.equal(chatterNodeOf(el("FORM", {}, [el("CHATTER")])).tagName, "CHATTER");
});

t("атрибуты ленты — как читает mail", () => {
    assert.deepEqual(chatterAttrs(el("chatter", { reload_on_activity: "1", reload_on_post: "True" })), {
        reloadOnActivity: true, reloadOnAttachment: false, reloadOnFollower: false, reloadOnPost: true,
    });
    assert.deepEqual(chatterAttrs(null), {
        reloadOnActivity: false, reloadOnAttachment: false, reloadOnFollower: false, reloadOnPost: false,
    });
});

t("вкладка «Файлы» — только sheet/notebook/page[@name=pmk_files]", () => {
    const page = el("page", { name: "pmk_files" });
    assert.equal(hasFilesPage(el("form", {}, [el("sheet", {}, [el("notebook", {}, [el("page", { name: "a" }), page])])])), true);
    assert.equal(hasFilesPage(el("form", {}, [el("sheet", {}, [el("notebook", {}, [el("page", { name: "a" })])])])), false);
    assert.equal(hasFilesPage(el("form", {}, [el("sheet", {}, [el("group", {}, [el("notebook", {}, [page])])])])), false,
        "вложенная панель — не наша");
    assert.equal(hasFilesPage(el("form", {}, [el("sheet")])), false);
    assert.equal(hasFilesPage(null), false);
});

t("число на значке", () => {
    assert.equal(countLabel(0), "");
    assert.equal(countLabel(undefined), "");
    assert.equal(countLabel(-1), "");
    assert.equal(countLabel(3), "3");
    assert.equal(countLabel(99), "99");
    assert.equal(countLabel(100), "99+");
});

t("подсказка «Истории»: просрочка словом", () => {
    assert.equal(historyTooltip({ isNew: true, activities: 3 }), "История появится после сохранения");
    assert.equal(historyTooltip({}), "История");
    assert.equal(historyTooltip({ activities: 2 }), "История · задач: 2");
    assert.equal(historyTooltip({ activities: 2, overdue: 1 }), "История · задач: 2, просрочено: 1");
});

t("подсказка скрепки", () => {
    assert.equal(filesTooltip({ isNew: true, count: 2 }), "Файлы появятся после сохранения");
    assert.equal(filesTooltip({ count: 0 }), "Файлы");
    assert.equal(filesTooltip({ count: 4 }), "Файлы · 4");
});

t("заголовок окна — номер целиком", () => {
    assert.equal(dialogTitle("История", "СМ-00025"), "История · СМ-00025");
    assert.equal(dialogTitle("Файлы", "  ВЗ-00002 "), "Файлы · ВЗ-00002");
    assert.equal(dialogTitle("История", ""), "История");
    assert.equal(dialogTitle("История", undefined), "История");
});

t("задачи и просроченные", () => {
    assert.deepEqual(activityCounts([{ state: "overdue" }, { state: "today" }, { state: "planned" }, null]),
        { activities: 3, overdue: 1 });
    assert.deepEqual(activityCounts(undefined), { activities: 0, overdue: 0 });
});

t("вложения: свежие при открытии, один запрос на всех", () => {
    assert.equal(shouldFetchAttachments(null), false);
    assert.equal(shouldFetchAttachments(null, { fresh: true }), false);
    // ещё не грузились — спросить и без fresh
    assert.equal(shouldFetchAttachments({ areAttachmentsLoaded: false, isLoadingAttachments: false }), true);
    // загружены раньше в этой вкладке браузера: без fresh — нет, при открытии — да
    const loaded = { areAttachmentsLoaded: true, isLoadingAttachments: false };
    assert.equal(shouldFetchAttachments(loaded), false);
    assert.equal(shouldFetchAttachments(loaded, { fresh: true }), true,
        "повторное открытие документа — список с сервера заново");
    // запрос уже идёт (значок, ярлык и вкладка открываются разом) — второй не нужен
    const loading = { areAttachmentsLoaded: true, isLoadingAttachments: true };
    assert.equal(shouldFetchAttachments(loading, { fresh: true }), false);
    assert.equal(shouldFetchAttachments({ areAttachmentsLoaded: false, isLoadingAttachments: true }), false);
});

console.log(`\n${n} проверок — все прошли`);
