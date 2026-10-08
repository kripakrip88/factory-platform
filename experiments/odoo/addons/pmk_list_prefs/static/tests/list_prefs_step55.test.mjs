// Шаг 55 разбора UX: колонки у каждого — правила без Odoo.
//
// Запуск из корня репозитория (нужен только node, без браузера и Odoo):
//   node experiments/odoo/addons/pmk_list_prefs/static/tests/list_prefs_step55.test.mjs
// Проверяется модуль ../src/js/list_prefs_rules.js (чистые функции без
// импортов Odoo). Другой файл — переменная PMK_RULES. Этот файл не попадает
// ни в один бандл: ассеты в манифесте перечислены поимённо.
import assert from "node:assert/strict";

const RULES = process.env.PMK_RULES
    || new URL("../src/js/list_prefs_rules.js", import.meta.url).href;
const R = await import(RULES);

let n = 0;
function t(name, fn) { fn(); n++; console.log("ok -", name); }

// Колонки, как их отдаёт list_arch_parser ядра.
const f = (id, name, extra = {}) => ({ id, name, type: "field", attrs: {}, ...extra });
const cols = [
    f("column_0", "sequence", { widget: "handle" }),
    f("column_1", "name"),
    { id: "column_2", type: "button_group", buttons: [] },
    f("column_3", "partner_id"),
    f("column_4", "amount", { optional: "show" }),
    f("column_5", "email", { optional: "hide" }),
    f("column_6", "partner_id"),
    { id: "column_7", type: "widget", name: "attach_doc" },
];

t("ключ вида: основной список и таблица в форме", () => {
    assert.equal(R.viewKey({ model: "res.partner", viewId: 12, actionId: 7 }), "list|res.partner|12|7");
    assert.equal(R.viewKey({ model: "res.partner", viewId: false, actionId: undefined }), "list|res.partner|0|0");
    assert.equal(
        R.viewKey({ model: "pmk.metal.product", parentModel: "pmk.metal.spec", fieldName: "product_ids", viewId: 55 }),
        "x2m|pmk.metal.spec|product_ids|55",
    );
    // «Клиенты» и «Поставщики» — один вид, разные действия.
    assert.notEqual(
        R.viewKey({ model: "res.partner", viewId: 5, actionId: 1 }),
        R.viewKey({ model: "res.partner", viewId: 5, actionId: 2 }),
    );
});

t("ключи колонок: поле, повтор поля, кнопки, виджеты", () => {
    const keys = R.columnKeys(cols);
    assert.equal(keys.get("column_1"), "name");
    assert.equal(keys.get("column_3"), "partner_id");
    assert.equal(keys.get("column_6"), "partner_id#2");
    assert.equal(keys.get("column_2"), "btn:column_2");
    assert.equal(keys.get("column_7"), "widget:attach_doc");
    assert.equal(R.isFieldKey("partner_id#2"), true);
    assert.equal(R.isFieldKey("btn:column_2"), false);
    assert.equal(R.isFieldKey("widget:x"), false);
    assert.equal(R.isFieldKey("prop:properties.x"), false);
    const prop = R.columnKeys([f("c_p", "properties.a", { relatedPropertyField: { id: 1 } })]);
    assert.equal(prop.get("c_p"), "prop:properties.a");
});

const arch = ["sequence", "name", "btn:column_2", "partner_id", "amount", "email", "partner_id#2", "widget:attach_doc"];

t("порядок: без настройки — как в разметке", () => {
    assert.deepEqual(R.orderKeys(arch, null), arch);
    assert.deepEqual(R.orderKeys(arch, []), arch);
});

t("порядок: сохранённый, ручка строк всегда первая", () => {
    const order = R.orderKeys(arch, ["amount", "name", "sequence", "partner_id", "email", "partner_id#2"], ["sequence"]);
    assert.equal(order[0], "sequence");
    assert.equal(order[1], "amount");
    assert.equal(order[2], "name");
    // Кнопка — за своим соседом по разметке (name), виджет — за partner_id#2.
    assert.equal(order[3], "btn:column_2");
    assert.equal(order.at(-1), "widget:attach_doc");
    assert.equal(new Set(order).size, arch.length);
});

t("порядок: колонку добавили в код — штатное место; убрали — пропуск", () => {
    const newArch = ["name", "inn", "partner_id", "amount"];
    // «email» убран из вида, «inn» добавлен после name.
    const order = R.orderKeys(newArch, ["amount", "email", "partner_id", "name"]);
    assert.deepEqual(order, ["amount", "partner_id", "name", "inn"]);
    // Новая колонка в самом начале разметки — в начало.
    assert.deepEqual(R.orderKeys(["first", "a", "b"], ["b", "a"]), ["first", "b", "a"]);
    // Две новые подряд держат свой порядок.
    assert.deepEqual(R.orderKeys(["a", "n1", "n2", "b"], ["b", "a"]), ["b", "a", "n1", "n2"]);
});

t("действующая настройка: своя важнее общей", () => {
    const own = { v: 1, order: ["a"] };
    const common = { v: 1, order: ["b"] };
    assert.equal(R.effectivePrefs(own, common), own);
    assert.equal(R.effectivePrefs(null, common), common);
    assert.equal(R.effectivePrefs(null, null), null);
});

t("первая правка — копия общей плюс правка (общий порядок не теряется)", () => {
    const common = { v: 1, order: ["b", "a"], widths: { a: 120 }, visible: { c: false } };
    const next = R.changePrefs(null, common, { widths: { b: 300 } });
    assert.deepEqual(next.order, ["b", "a"]);
    assert.deepEqual(next.widths, { a: 120, b: 300 });
    assert.deepEqual(next.visible, { c: false });
    // Общая не тронута.
    assert.deepEqual(common.widths, { a: 120 });
});

t("первая правка без общей — основа: то, что видно сейчас", () => {
    const seed = { v: 1, order: [], widths: {}, visible: { email: true } };
    const next = R.changePrefs(null, null, { visible: { amount: false } }, seed);
    assert.deepEqual(next.visible, { email: true, amount: false });
});

t("правки: ширина, снятие ширины, сброс ширин, порядок, замена", () => {
    const own = { v: 1, order: ["a", "b"], widths: { a: 100, b: 200 }, visible: {} };
    assert.deepEqual(R.changePrefs(own, null, { widths: { a: null } }).widths, { b: 200 });
    assert.deepEqual(R.changePrefs(own, null, { resetWidths: true }).widths, {});
    assert.deepEqual(R.changePrefs(own, null, { order: ["b", "a"] }).order, ["b", "a"]);
    assert.deepEqual(R.changePrefs(own, null, { widths: { a: 5 } }).widths.a, R.MIN_WIDTH);
    assert.deepEqual(R.changePrefs(own, null, { widths: { a: 99999 } }).widths.a, R.MAX_WIDTH);
    assert.deepEqual(R.changePrefs(own, null, { widths: { a: 123.6 } }).widths.a, 124);
    const replaced = R.changePrefs(own, null, { replace: { order: ["x"], junk: 1 } });
    assert.deepEqual(replaced, { v: 1, order: ["x"], widths: {}, visible: {} });
    // Исходная не тронута.
    assert.deepEqual(own.widths, { a: 100, b: 200 });
});

t("чистка по разметке: исчезнувшие колонки и служебные ключи уходят", () => {
    const prefs = { order: ["a", "gone", "a", "btn:column_2"], widths: { a: 100, gone: 50 }, visible: { gone: false, b: false } };
    const clean = R.prunePrefs(prefs, ["a", "b", "btn:column_2"]);
    assert.deepEqual(clean.order, ["a"]);
    assert.deepEqual(clean.widths, { a: 100 });
    assert.deepEqual(clean.visible, { b: false });
});

t("замки: ручка, название, обязательное в редактируемой", () => {
    assert.equal(R.lockReason(cols[0]), "pinned");
    assert.equal(R.lockReason(cols[1], { isTitle: true }), "pinned");
    assert.equal(R.lockReason(cols[3], { editable: true, required: true }), "required");
    assert.equal(R.lockReason(cols[3], { editable: false, required: true }), null, "в нередактируемой прятать можно");
    assert.equal(R.lockReason(cols[4], { editable: true, required: true }), null, "optional — как у ядра");
    assert.equal(R.lockReason(cols[2]), null);
    assert.equal(R.titleColumnId(cols), "column_1");
    assert.equal(R.titleColumnId([cols[0], cols[3], cols[4]]), "column_3", "нет name — первая не optional");
    assert.equal(R.titleColumnId([cols[0]]), null);
    assert.equal(R.isRequiredExpr("1"), true);
    assert.equal(R.isRequiredExpr("parent.state == 'draft'"), true);
    assert.equal(R.isRequiredExpr("False"), false);
    assert.equal(R.isRequiredExpr(undefined), false);
});

t("видимость: отличия от вида, закреплённая видна всегда", () => {
    assert.equal(R.isVisible(null, "email", false), false);
    assert.equal(R.isVisible({ visible: { email: true } }, "email", false), true);
    assert.equal(R.isVisible({ visible: { name: false } }, "name", true, true), true);
    const rows = [
        { key: "name", visible: true, archDefault: true, lock: "pinned" },
        { key: "amount", visible: false, archDefault: true },
        { key: "email", visible: true, archDefault: false },
        { key: "partner_id", visible: true, archDefault: true },
    ];
    assert.deepEqual(R.visibleDiff(rows), { amount: false, email: true });
});

function info(columns, hideLocked = ["sequence", "name"]) {
    const keys = R.columnKeys(columns);
    const archKeys = columns.map((c) => keys.get(c.id));
    const hideable = new Set(archKeys.filter((k) => R.isFieldKey(k) && !hideLocked.includes(k)));
    return { keys, archKeys, pinnedKeys: ["sequence"], hideable };
}

t("применение: без настройки — колонки ядра как есть", () => {
    const active = cols.filter((c) => c.name !== "email");
    const result = R.applyPrefs(active, null, info(cols));
    assert.equal(result.columns, active);
    assert.equal(result.widths.size, 0);
});

t("применение: порядок, скрытие не optional, ширины только полям", () => {
    const active = cols.filter((c) => c.name !== "email"); // email: optional=hide
    const prefs = {
        order: ["amount", "partner_id#2", "name", "partner_id"],
        visible: { partner_id: false, name: false },
        widths: { amount: 140, "btn:column_2": 50, name: 300 },
    };
    const result = R.applyPrefs(active, prefs, info(cols));
    const ids = result.columns.map((c) => c.id);
    // partner_id спрятан, name закреплён — не прячется; ручка первая;
    // виджет — за своим соседом по разметке (partner_id#2), кнопка — за name.
    assert.deepEqual(ids, ["column_0", "column_4", "column_6", "column_7", "column_1", "column_2"]);
    assert.equal(result.widths.get("column_4"), 140);
    assert.equal(result.widths.get("column_1"), 300);
    assert.equal(result.widths.has("column_2"), false, "кнопкам ширину не ставим");
});

t("применение: optional решает ядро (по computeOptionalActiveFields)", () => {
    const active = cols.filter((c) => c.name !== "email");
    const prefs = { order: [], visible: { amount: false }, widths: {} };
    const result = R.applyPrefs(active, prefs, info(cols));
    assert.ok(result.columns.some((c) => c.name === "amount"), "optional не фильтруем второй раз");
});

t("применение: исчезнувшие колонки в настройке не ломают список", () => {
    const active = [cols[1], cols[3]];
    const prefs = { order: ["gone", "partner_id", "name"], visible: { gone: false }, widths: { gone: 99 } };
    const result = R.applyPrefs(active, prefs, info([cols[1], cols[3]]));
    assert.deepEqual(result.columns.map((c) => c.name), ["partner_id", "name"]);
    assert.equal(result.widths.size, 0);
});

t("перенос колонки: перед другой, в конец, не перед ручкой", () => {
    const order = ["sequence", "name", "partner_id", "amount"];
    assert.deepEqual(R.moveKey(order, "amount", "name", ["sequence"]), ["sequence", "amount", "name", "partner_id"]);
    assert.deepEqual(R.moveKey(order, "name", null, ["sequence"]), ["sequence", "partner_id", "amount", "name"]);
    assert.deepEqual(R.moveKey(order, "amount", "sequence", ["sequence"]), ["sequence", "amount", "name", "partner_id"]);
    assert.deepEqual(R.moveKey(order, "sequence", null, ["sequence"]), order, "ручку не двигаем");
});

t("порядок окна поверх полного: невидимые условием остаются на месте", () => {
    const full = ["a", "hidden", "b", "c"];
    assert.deepEqual(R.mergeOrder(full, ["c", "a", "b"]), ["c", "hidden", "a", "b"]);
    assert.deepEqual(R.mergeOrder(["a", "b"], ["b", "a", "new"]), ["b", "a", "new"]);
});

t("сравнение: строки окна и настройки", () => {
    const rows = [{ key: "a", visible: true, width: null }, { key: "b", visible: false, width: 120 }];
    assert.equal(R.sameRows(rows, rows.map((r) => ({ ...r, label: "x" }))), true);
    assert.equal(R.sameRows(rows, [rows[1], rows[0]]), false);
    assert.equal(R.sameRows(rows, [rows[0], { ...rows[1], width: null }]), false);
    assert.equal(R.samePrefs({ order: ["a"], widths: { a: 1, b: 2 } }, { order: ["a"], widths: { b: 2, a: 1 }, visible: {} }), true);
    assert.equal(R.samePrefs({ order: ["a", "b"] }, { order: ["b", "a"] }), false);
    assert.equal(R.isEmptyPrefs({ v: 1, order: [], widths: {}, visible: {} }), true);
    assert.equal(R.isEmptyPrefs({ order: ["a"] }), false);
});

t("ширина: целое в пределах", () => {
    assert.equal(R.cleanWidth("abc"), null);
    assert.equal(R.cleanWidth(0), null);
    assert.equal(R.cleanWidth(-5), null);
    assert.equal(R.cleanWidth(10), R.MIN_WIDTH);
    assert.equal(R.cleanWidth(250.4), 250);
});

t("название: служебная колонка column_invisible замок не забирает", () => {
    // Таблицы окна «Изделие»: ручка, calc_mode (column_invisible="1"), «Деталь».
    const lines = [
        f("c0", "sequence", { widget: "handle" }),
        f("c1", "calc_mode", { column_invisible: "1" }),
        f("c2", "detail_name"),
        f("c3", "qty", { column_invisible: "1" }),
        f("c4", "weight_total"),
    ];
    const hidden = (c) => R.constBool(c.column_invisible) === true;
    assert.equal(R.titleColumnId(lines, hidden), "c2", "«Деталь», а не calc_mode");
    assert.equal(R.titleColumnId(lines), "c1", "без проверки условия — старая ошибка");
    assert.equal(R.titleColumnId([lines[0], lines[1], lines[3]], hidden), null);
    assert.equal(R.constBool("1"), true);
    assert.equal(R.constBool("True"), true);
    assert.equal(R.constBool(undefined), false);
    assert.equal(R.constBool("0"), false);
    assert.equal(R.constBool("parent.state == 'done'"), null, "от записи — считать");
});

t("последнюю видимую колонку не спрятать", () => {
    const rows = [
        { key: "a", visible: true },
        { key: "b", visible: false },
    ];
    assert.equal(R.canHide(rows, "a"), false);
    assert.equal(R.canHide([...rows, { key: "c", visible: true, lock: "pinned" }], "a"), true);
    assert.equal(R.canHide([{ key: "a", visible: true }, { key: "b", visible: true }], "a"), true);
});

t("пол ширины: минимум ядра и содержимое названия", () => {
    assert.equal(R.widthFloor(80), 80);
    assert.equal(R.widthFloor(0), R.MIN_WIDTH);
    assert.equal(R.widthFloor(80, 112.3), 113, "номер не обрезаем");
    assert.equal(R.widthFloor(80, 900), R.TITLE_FLOOR_CAP, "длинное название сузить можно");
    assert.equal(R.floorWidth(40, 80), 80, "40 px у строки — 80");
    assert.equal(R.floorWidth(150, 80), 150);
    assert.equal(R.floorWidth(null, 80), null);
    assert.equal(R.floorWidth(99999, 80), R.MAX_WIDTH);
});

t("разделы: колонки с итогом всегда правее остальных", () => {
    const line = [
        f("h", "sequence", { widget: "handle" }),
        f("s", "price_subtotal"),
        f("p", "product_id"),
        f("n", "name"),
        f("t", "price_total"),
        f("q", "product_uom_qty"),
    ];
    const ids = R.aggregatesLast(line, ["price_subtotal", "price_total"]).map((c) => c.id);
    assert.deepEqual(ids, ["h", "p", "n", "q", "s", "t"]);
    assert.equal(R.aggregatesLast(line, []), line);
    const ok = [line[0], line[2], line[3], line[1]];
    assert.equal(R.aggregatesLast(ok, ["price_subtotal"]).map((c) => c.id).join(), "h,p,n,s");
});

t("бросили перед кнопкой — место у следующей колонки поля", () => {
    const keys = ["a", "b", "btn:column_9", "c", "widget:x"];
    assert.equal(R.snapDropIndex(keys, 2), 3, "перед кнопкой → перед c");
    assert.equal(R.snapDropIndex(keys, 1), 1);
    assert.equal(R.snapDropIndex(keys, 4), 5, "перед виджетом в конце → в конец");
    assert.equal(R.snapDropIndex(keys, 5), 5);
});

t("окно «Колонки» шлёт серверу только свою правку", () => {
    const before = [
        { key: "a", visible: true, width: 120 },
        { key: "b", visible: true, width: null },
        { key: "n", visible: true, width: null, lock: "pinned" },
    ];
    const same = R.rowsChange(before, before.map((r) => ({ ...r })), ["a", "b", "n"]);
    assert.deepEqual(same, { visible: {}, widths: {} }, "ничего не меняли — пустая правка, без порядка");
    const after = [
        { key: "b", visible: false, width: null },
        { key: "a", visible: true, width: null },
        { key: "n", visible: true, width: null, lock: "pinned" },
    ];
    const change = R.rowsChange(before, after, ["b", "a", "n", "hidden"]);
    assert.deepEqual(change.visible, { b: false });
    assert.deepEqual(change.widths, { a: null }, "× — снять ширину");
    assert.deepEqual(change.order, ["b", "a", "n", "hidden"]);
    // Правка поверх свежей настройки другой вкладки не теряет её ширины.
    const fromOtherTab = { v: 1, order: ["a", "b", "n"], widths: { b: 300, n: 200 }, visible: {} };
    const merged = R.changePrefs(fromOtherTab, null, { visible: { b: false } });
    assert.deepEqual(merged.widths, { b: 300, n: 200 });
});

console.log(`\n${n} проверок пройдено`);
