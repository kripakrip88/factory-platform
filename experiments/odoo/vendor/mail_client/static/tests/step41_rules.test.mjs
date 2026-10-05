// ПРАВКА ПМК — шаг 41 разбора удобства (05.10.2026): почта, остальное.
//
// Запуск из корня репозитория (нужен только node, без браузера и Odoo):
//   node experiments/odoo/vendor/mail_client/static/tests/step41_rules.test.mjs
// Проверяются чистые модули рядом (без импортов Odoo): горячие клавиши
// (panes/hotkeys.js), поиск и кнопки-фильтры (panes/quick_filters.js),
// дерево папок (panes/folder_layout.js), ширина колонок (panes/pane_widths.js),
// ключ страницы и «касается ли синхронизация списка» (panes/list_refresh.js).
// Файл .mjs сборщик ассетов Odoo не берёт (ASSET_EXTENSIONS — js, css, scss,
// sass, less, xml), в hoot-тесты он не попадает.
import assert from "node:assert/strict";

const SRC = new URL("../src/panes/", import.meta.url);
const hotkeys = await import(new URL("hotkeys.js", SRC).href);
const quick = await import(new URL("quick_filters.js", SRC).href);
const layout = await import(new URL("folder_layout.js", SRC).href);
const widths = await import(new URL("pane_widths.js", SRC).href);
const refresh = await import(new URL("list_refresh.js", SRC).href);

let n = 0;
function t(name, fn) {
    fn();
    n++;
    console.log("ok -", name);
}

// ─── А6: горячие клавиши ────────────────────────────────────────────────────
const key = (props) => ({ ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...props });

t("поле ввода, textarea, select, редактор — ввод; флажок и кнопка — нет", () => {
    const { isTypingTarget } = hotkeys;
    assert.equal(isTypingTarget({ tagName: "INPUT", type: "text" }), true);
    assert.equal(isTypingTarget({ tagName: "INPUT", type: "search" }), true);
    assert.equal(isTypingTarget({ tagName: "INPUT", type: "checkbox" }), false);
    assert.equal(isTypingTarget({ tagName: "TEXTAREA" }), true);
    assert.equal(isTypingTarget({ tagName: "SELECT" }), true);
    assert.equal(isTypingTarget({ tagName: "DIV", isContentEditable: true }), true);
    assert.equal(isTypingTarget({ tagName: "P", closest: (sel) => (sel.includes("contenteditable") ? {} : null) }), true);
    assert.equal(isTypingTarget({ tagName: "BUTTON", closest: () => null }), false);
    assert.equal(isTypingTarget(null), false);
});

t("«/» — сам знак или физическая клавиша (в русской раскладке на ней точка), без Ctrl/Alt", () => {
    const { isSearchKey } = hotkeys;
    assert.equal(isSearchKey(key({ key: "/", code: "Slash" })), true);
    assert.equal(isSearchKey(key({ key: ".", code: "Slash" })), true, "русская раскладка");
    assert.equal(isSearchKey(key({ key: "/", code: "Backslash", shiftKey: true })), true, "«/» с Shift");
    assert.equal(isSearchKey(key({ key: ",", code: "Slash", shiftKey: true })), false);
    assert.equal(isSearchKey(key({ key: "/", code: "Slash", ctrlKey: true })), false);
    assert.equal(isSearchKey(key({ key: "/", code: "Slash", isComposing: true })), false);
});

t("рамка письма пересылает только клавиши почты и без Ctrl/Cmd/Alt", () => {
    const { forwardableKey } = hotkeys;
    for (const props of [
        { key: "Escape", code: "Escape" },
        { key: "к", code: "KeyR" },
        { key: "a", code: "KeyA" },
        { key: "f", code: "KeyF" },
        { key: "д", code: "KeyL" },
        { key: "/", code: "Slash" },
    ]) {
        assert.equal(forwardableKey(key(props)), true, JSON.stringify(props));
    }
    assert.equal(forwardableKey(key({ key: "c", code: "KeyC", ctrlKey: true })), false, "Ctrl+C — копировать");
    assert.equal(forwardableKey(key({ key: "a", code: "KeyA", metaKey: true })), false, "Cmd+A — выделить");
    assert.equal(forwardableKey(key({ key: "R", code: "KeyR", shiftKey: true })), false);
    assert.equal(forwardableKey(key({ key: "x", code: "KeyX" })), false);
    assert.equal(forwardableKey(key({ key: "PageDown", code: "PageDown" })), false, "прокрутка — письму");
    // Доводка: стрелки в тексте письма прокручивают письмо, а не открывают соседнее.
    assert.equal(forwardableKey(key({ key: "ArrowDown", code: "ArrowDown" })), false, "↓ — письму");
    assert.equal(forwardableKey(key({ key: "ArrowUp", code: "ArrowUp" })), false, "↑ — письму");
});

t("↑/↓ листают письма только «в списке»; иначе — прокрутка браузера", () => {
    const { arrowsMoveRows } = hotkeys;
    const inList = { rows: 3, current: true };
    assert.equal(arrowsMoveRows(inList), true, "письмо открыто, щёлкали по списку");
    assert.equal(arrowsMoveRows({ ...inList, current: false }), false,
        "ничего не открыто — ↓ не открывает первое письмо (не гасит его)");
    assert.equal(arrowsMoveRows({ ...inList, inReader: true }), false,
        "щёлкнули по окну письма — стрелки прокручивают письмо");
    assert.equal(arrowsMoveRows({ ...inList, readerCovers: true }), false,
        "письмо на весь экран — стрелки листают письмо, соседнее — кнопками");
    assert.equal(arrowsMoveRows({ ...inList, draft: true }), false, "пишется письмо");
    assert.equal(arrowsMoveRows({ ...inList, rows: 0 }), false, "список пуст");
    assert.equal(arrowsMoveRows(), false);
});

const rows = [{ id: 30, thread_key: "a" }, { id: 20, thread_key: "b" }, { id: 10, thread_key: "c" }];

t("↓/↑ — соседнее письмо; ничего не открыто — ↓ даёт первое (для кнопок; клавишам — arrowsMoveRows)", () => {
    const { neighbourId } = hotkeys;
    assert.deepEqual(neighbourId(rows, { selectedId: 30 }, 1), { id: 20 });
    assert.deepEqual(neighbourId(rows, { selectedId: 20 }, -1), { id: 30 });
    assert.deepEqual(neighbourId(rows, { selectedId: 30 }, -1), { id: null }, "выше первого — некуда");
    assert.deepEqual(neighbourId(rows, {}, 1), { id: 30 });
    assert.deepEqual(neighbourId(rows, {}, -1), { id: null });
    assert.deepEqual(neighbourId([], {}, 1), { id: null });
});

t("внизу загруженного — «Загрузить ещё», если оно есть", () => {
    const { neighbourId } = hotkeys;
    assert.deepEqual(neighbourId(rows, { selectedId: 10, hasMore: true }, 1), { id: null, needMore: true });
    assert.deepEqual(neighbourId(rows, { selectedId: 10, hasMore: false }, 1), { id: null });
});

t("строку переписки, которую теперь представляет другое письмо, находим по ключу", () => {
    const { neighbourId } = hotkeys;
    assert.deepEqual(neighbourId(rows, { selectedId: 99, selectedKey: "b" }, 1), { id: 10 });
});

t("кнопка для клавиши — видимая, доступная, не в бледном (inert) окне", () => {
    const { pickKeyButton } = hotkeys;
    const button = (mcKey, extra = {}) => ({ dataset: { mcKey }, disabled: false, ...extra });
    const hidden = button("r", { hidden: true });
    const inert = button("r", { inert: true });
    const shown = button("r");
    const opts = { isVisible: (b) => !b.hidden, isInert: (b) => Boolean(b.inert) };
    assert.equal(pickKeyButton([hidden, inert, shown], "r", opts), shown);
    assert.equal(pickKeyButton([hidden, inert], "r", opts), null, "нет видимой — клавиша ничего не делает");
    assert.equal(pickKeyButton([button("r", { disabled: true })], "r", opts), null);
    assert.equal(pickKeyButton([shown], "l", opts), null, "нет кнопки «Лид» — L молчит");
    assert.deepEqual(hotkeys.KEY_BUTTONS, ["r", "a", "f", "l"]);
});

// ─── А7: поиск по мере ввода, кнопки-фильтры ───────────────────────────────
t("поиск: от двух знаков, Enter — и с одного, пусто — обычный список", () => {
    const { searchDecision, SEARCH_MIN_CHARS, SEARCH_DELAY_MS } = quick;
    assert.equal(SEARCH_MIN_CHARS, 2);
    assert.equal(SEARCH_DELAY_MS, 400);
    assert.equal(searchDecision("с"), "wait");
    assert.equal(searchDecision("с", { enter: true }), "search");
    assert.equal(searchDecision("сч"), "search");
    assert.equal(searchDecision("  00627 "), "search");
    assert.equal(searchDecision("00627", { applied: "00627" }), "same", "тот же текст — без запроса");
    assert.equal(searchDecision("", { applied: "00627" }), "reset");
    assert.equal(searchDecision("0", { applied: "00627" }), "reset", "стёрли до одного знака");
    assert.equal(searchDecision(""), "same");
});

t("кнопка-фильтр: щелчок включает, повторный — «Все»", () => {
    const { toggleQuickFilter, QUICK_FILTER_IDS } = quick;
    assert.deepEqual(QUICK_FILTER_IDS, ["unread", "attachments", "awaiting"]);
    assert.equal(toggleQuickFilter("all", "unread"), "unread");
    assert.equal(toggleQuickFilter("unread", "unread"), "all");
    assert.equal(toggleQuickFilter("unread", "awaiting"), "awaiting");
});

// ─── В4: имена вложений в строке ───────────────────────────────────────────
t("имена вложений: до трёх плашек и «+N» за остальные", () => {
    const { attachmentChips } = quick;
    assert.deepEqual(attachmentChips(["Счёт 00627.pdf", "Спецификация.xlsx"], 2), {
        shown: ["Счёт 00627.pdf", "Спецификация.xlsx"], more: 0 });
    assert.deepEqual(attachmentChips(["a", "b", "c"], 5), { shown: ["a", "b", "c"], more: 2 });
    assert.deepEqual(attachmentChips(["a", "b", "c", "d"], 0), { shown: ["a", "b", "c"], more: 1 });
    assert.deepEqual(attachmentChips(undefined, undefined), { shown: [], more: 0 });
});

// ─── А8: дерево папок ──────────────────────────────────────────────────────
// Папки ящиков стенда на 05.10.2026 (SELECT по mail_client_folder) — в
// порядке get_inbox_state: роль, затем имя; сортировщики mail.ru (Новости,
// Рассылки, Соцсети, Чеки) у pmk_mail_ui — в конце.
const F = (id, name, role, parent_id, total, extra = {}) =>
    ({ id, name, role, parent_id: parent_id || false, total, unread: 0, quiet: false, ...extra });
const pmkpark = [
    F(6, "Входящие", "inbox", 0, 2264), F(16, "Черновики", "drafts", 0, 10),
    F(15, "Отправленные", "sent", 0, 1245), F(18, "Архив", "archive", 0, 0),
    F(14, "Спам", "spam", 0, 3119, { quiet: true }), F(17, "Корзина", "trash", 0, 3, { quiet: true }),
    F(20, "Авито Фарпост Юла", "other", 6, 18), F(7, "Документы", "other", 0, 1),
    F(13, "Лаба", "other", 0, 0), F(8, "Модуль рассылка", "other", 0, 9),
    F(22, "НПС Снабжение", "other", 6, 0), F(10, "Прайс листы", "other", 0, 0),
    F(9, "Рабочая", "other", 0, 0), F(21, "Расчет заказов", "other", 6, 0),
    F(11, "Счета на оплату", "other", 0, 0), F(19, "Чертежи", "other", 6, 0),
    F(12, "эксель", "other", 0, 0),
    F(25, "Новости", "other", 6, 0, { quiet: true }), F(24, "Рассылки", "other", 6, 549, { quiet: true }),
    F(23, "Соцсети", "other", 6, 0, { quiet: true }), F(26, "Чеки", "other", 6, 22, { quiet: true }),
];
const zakaz = [
    F(1, "Входящие", "inbox", 0, 90), F(5, "Черновики", "drafts", 1, 0),
    F(4, "Отправленные", "sent", 1, 12), F(3, "Спам", "spam", 1, 29, { quiet: true }),
    F(2, "Корзина", "trash", 1, 0, { quiet: true }),
];
const shape = (entries) => entries.map((e) => `${"  ".repeat(e.depth)}${e.folder.name}`);

t("pmkpark@: подпапки с отступом под «Входящими», сортировщики — последними", () => {
    const { main } = layout.layoutFolders(pmkpark);
    assert.deepEqual(shape(main), [
        "Входящие",
        "  Авито Фарпост Юла",
        "  Рассылки",
        "  Чеки",
        "Черновики",
        "Отправленные",
        "Спам",
        "Корзина",
        "Документы",
        "Модуль рассылка",
    ]);
});

t("pmkpark@: 11 пустых — под «Ещё папки», у вложенных — имя родителя", () => {
    const { more } = layout.layoutFolders(pmkpark);
    assert.equal(more.length, 11);
    assert.deepEqual(more.map((e) => e.folder.name), [
        "НПС Снабжение", "Расчет заказов", "Чертежи", "Новости", "Соцсети",
        "Архив", "Лаба", "Прайс листы", "Рабочая", "Счета на оплату", "эксель",
    ]);
    assert.equal(more[0].parentName, "Входящие");
    assert.equal(more[5].parentName, "");
});

t("zakaz@: служебные папки (на сервере — внутри INBOX) — верхним уровнем, пустые тоже видны", () => {
    const { main, more } = layout.layoutFolders(zakaz);
    assert.deepEqual(shape(main), ["Входящие", "Черновики", "Отправленные", "Спам", "Корзина"]);
    assert.equal(more.length, 0);
});

t("пустой родитель непустой подпапки не прячется", () => {
    const folders = [F(1, "Входящие", "inbox", 0, 5), F(2, "Проекты", "other", 0, 0), F(3, "Ограждения", "other", 2, 4)];
    const { main, more } = layout.layoutFolders(folders);
    assert.deepEqual(shape(main), ["Входящие", "Проекты", "  Ограждения"]);
    assert.equal(more.length, 0);
});

t("выключатели: без вложения и без «Ещё» — прежний плоский список", () => {
    const { main, more } = layout.layoutFolders(pmkpark, { nest: false, hideEmpty: false });
    assert.equal(main.length, pmkpark.length);
    assert.ok(main.every((e) => e.depth === 0));
    assert.deepEqual(main.map((e) => e.folder.id), pmkpark.map((f) => f.id));
    assert.equal(more.length, 0);
});

t("старый сервер без total — ни одна папка не пустая", () => {
    const folders = pmkpark.map(({ total, ...rest }) => rest);
    assert.equal(layout.layoutFolders(folders).more.length, 0);
});

t("полоса значков — служебные папки; число до 99, дальше «99+»", () => {
    assert.deepEqual(layout.railFolders(pmkpark).map((f) => f.name),
        ["Входящие", "Черновики", "Отправленные", "Спам", "Корзина"]);
    assert.equal(layout.railCount(0), "");
    assert.equal(layout.railCount(7), "7");
    assert.equal(layout.railCount(313), "99+");
});

// ─── А9: ширина колонок ────────────────────────────────────────────────────
t("ширины — ключ с номером пользователя, битая запись — как ничего", () => {
    const { widthsKey, parseWidths } = widths;
    assert.equal(widthsKey(2), "mail_client.pane_widths.u2");
    assert.deepEqual(parseWidths("{битое"), {});
    assert.deepEqual(parseWidths(null), {});
    assert.deepEqual(parseWidths("[1,2]"), {});
    assert.deepEqual(parseWidths('{"folders": 300, "list": "abc", "x": 5}'), { folders: 300 });
    assert.deepEqual(parseWidths('{"folders": 9000, "list": 10}'), { folders: 400, list: 280 }, "в пределах");
});

t("перетаскивание: колонка в своих пределах, письму не меньше 360 px", () => {
    const { clampPane, READER_MIN } = widths;
    assert.equal(READER_MIN, 360);
    assert.equal(clampPane("folders", 100), 160);
    assert.equal(clampPane("folders", 520), 400);
    assert.equal(clampPane("list", 700, { available: 1440, others: 246 }), 700);
    assert.equal(clampPane("list", 1000, { available: 1440, others: 246 }), 1440 - 246 - 360);
    assert.equal(clampPane("list", 150, { available: 1440, others: 246 }), 280);
});

t("ширины — CSS-переменными корня; что не меняли — из стилей", () => {
    const { paneVars } = widths;
    assert.equal(paneVars({}), "");
    assert.equal(paneVars({ folders: 200, listCompact: 600 }), "--mc-folders-w: 200px; --mc-list-w-compact: 600px");
});

// ─── Б1: ключ страницы; Б2: что касается списка ────────────────────────────
t("«Загрузить ещё»: ключ — дата и id строки, у переписки — thread_max_id", () => {
    const { pageAfter, isAbove } = refresh;
    assert.deepEqual(pageAfter([]), { before: null, before_id: null });
    assert.deepEqual(pageAfter([{ id: 7, date: "2026-10-05 10:00:00" }]),
        { before: "2026-10-05 10:00:00", before_id: 7 });
    assert.deepEqual(pageAfter([{ id: 7, thread_max_id: 9, date: "2026-10-05 10:00:00" }]),
        { before: "2026-10-05 10:00:00", before_id: 9 });
    // Равные даты: выше — больший второй ключ (как ORDER BY сервера).
    const d = "2026-10-05 10:00:00";
    assert.equal(isAbove({ id: 1, thread_max_id: 50, date: d }, { id: 2, thread_max_id: 40, date: d }), true);
    assert.equal(isAbove({ id: 9, date: d }, { id: 8, date: d }), true);
});

const folders = [
    { id: 6, role: "inbox" }, { id: 15, role: "sent" }, { id: 14, role: "spam", quiet: true },
    { id: 24, role: "other", quiet: true }, { id: 7, role: "other" },
];

t("синхронизация: открытая папка, переписки — не тихие, «везде» — всё, кроме Спама и Корзины", () => {
    const { showsChange } = refresh;
    const plain = { activeFolderId: 6, threaded: false, unified: false, digestIds: [] };
    assert.equal(showsChange(plain, folders, [6]), true);
    assert.equal(showsChange(plain, folders, [15]), false);
    assert.equal(showsChange({ ...plain, threaded: true }, folders, [15]), true);
    assert.equal(showsChange({ ...plain, threaded: true }, folders, [14]), false, "новый спам — нет");
    assert.equal(showsChange({ ...plain, everywhere: true }, folders, [7]), true, "найденное лежит где угодно");
    assert.equal(showsChange({ ...plain, everywhere: true }, folders, [14]), false);
    assert.equal(showsChange({ ...plain, digestIds: [24] }, folders, [24]), true, "строка рассылок");
    assert.equal(showsChange(plain, folders, null), true, "старый сервер — везде");
    assert.equal(showsChange(plain, folders, [999]), true, "папки нет в дереве — касается");
    assert.equal(showsChange({ ...plain, activeFolderId: null, unified: true }, folders, [6]), true);
});

console.log(`\n${n} проверок прошло`);
