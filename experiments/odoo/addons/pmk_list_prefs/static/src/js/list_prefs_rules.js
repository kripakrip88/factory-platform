/** @odoo-module **/
/**
 * Колонки у каждого (разбор UX, шаг 55, 08.10.2026) — правила без импортов
 * Odoo, чтобы прогонять их в node без браузера
 * (static/tests/list_prefs_step55.test.mjs). Использует js/list_prefs.js.
 *
 * НАСТРОЙКА СПИСКА — объект версии 1:
 *   { v: 1, order: [ключ, …], widths: { ключ: px }, visible: { ключ: bool } }
 *   • order   — порядок колонок полей, как его оставил человек;
 *   • widths  — ширина содержимого колонки в пикселях (без отступов ячейки:
 *               так же считает ядро, column_width_hook.js);
 *   • visible — только ОТЛИЧИЯ от вида: нет ключа — колонка как в разметке
 *               (optional="hide" — скрыта, остальные показаны). Поэтому новая
 *               колонка из кода приходит со своим штатным видом, а поменяли
 *               в коде optional — человек без своего выбора видит новое.
 *
 * КЛЮЧ КОЛОНКИ — имя поля; повтор того же поля в виде — «имя#2», «имя#3».
 * Кнопки, виджеты и колонки свойств получают служебные ключи и не
 * настраиваются (их место — за соседней колонкой по разметке).
 *
 * УСТОЙЧИВОСТЬ К ПРАВКАМ КОДА. Колонку добавили в вид — она встаёт на своё
 * штатное место (сразу за ближайшей предыдущей по разметке колонкой);
 * убрали — её ключ в настройке молча пропускается и стирается при
 * следующем сохранении.
 */

export const PREFS_VERSION = 1;
export const MIN_WIDTH = 40;
/** Пол ширины колонки названия по содержимому — не шире этого. */
export const TITLE_FLOOR_CAP = 240;
export const MAX_WIDTH = 2000;
/** Изменение ширины меньше этого — дрожание руки, не пишем. */
export const WIDTH_EPSILON = 2;
/** Имена «названия» записи: такую колонку нельзя скрыть. */
export const TITLE_FIELDS = ["name", "display_name", "complete_name"];

/**
 * Ключ вида в базе (модель pmk.list.prefs, поле view_key).
 *   основной список: list|<модель>|<id вида>|<id действия>;
 *   таблица в форме: x2m|<модель документа>|<поле>|<id вида формы>.
 * Действие в ключе разводит «Клиентов» и «Поставщиков»: у них один вид.
 *
 * @param {{model: string, viewId?: number, actionId?: number,
 *          parentModel?: string, fieldName?: string}} parts
 * @returns {string}
 */
export function viewKey({ model, viewId, actionId, parentModel, fieldName }) {
    const id = (value) => (Number.isInteger(value) && value > 0 ? value : 0);
    if (parentModel && fieldName) {
        return `x2m|${parentModel}|${fieldName}|${id(viewId)}`;
    }
    return `list|${model}|${id(viewId)}|${id(actionId)}`;
}

/**
 * Ключи колонок списка.
 *
 * @param {Object[]} columns все колонки вида (allColumns рендерера)
 * @returns {Map<string, string>} id колонки → ключ
 */
export function columnKeys(columns) {
    const keys = new Map();
    const seen = {};
    const unique = (base) => {
        seen[base] = (seen[base] || 0) + 1;
        return seen[base] === 1 ? base : `${base}#${seen[base]}`;
    };
    for (const column of columns || []) {
        let base;
        if (column.type === "field" && column.relatedPropertyField) {
            base = `prop:${column.name}`;
        } else if (column.type === "field") {
            base = column.name;
        } else if (column.type === "widget") {
            base = `widget:${column.name || (column.widget && column.widget.name) || "?"}`;
        } else {
            base = `btn:${column.id}`;
        }
        keys.set(column.id, unique(base));
    }
    return keys;
}

/** Ключ колонки поля, которую человек может двигать и прятать. */
export function isFieldKey(key) {
    return typeof key === "string" && key.length > 0 && !/^(prop|widget|btn):/.test(key);
}

/**
 * Порядок колонок: сохранённый, но устойчивый к правкам вида.
 *
 * @param {string[]} archKeys ключи всех колонок в порядке разметки
 * @param {string[]} [savedOrder] сохранённый порядок
 * @param {string[]} [pinnedKeys] закреплённые на своём месте (ручка
 *   перетаскивания строк): всегда первыми, в порядке разметки
 * @returns {string[]} все ключи archKeys, каждый ровно один раз
 */
export function orderKeys(archKeys, savedOrder, pinnedKeys = []) {
    const arch = [...new Set(archKeys || [])];
    if (!Array.isArray(savedOrder) || !savedOrder.length) {
        return arch;
    }
    const inArch = new Set(arch);
    const pinned = new Set((pinnedKeys || []).filter((key) => inArch.has(key)));
    const result = arch.filter((key) => pinned.has(key));
    const placed = new Set(result);
    for (const key of savedOrder) {
        if (inArch.has(key) && !placed.has(key)) {
            result.push(key);
            placed.add(key);
        }
    }
    // Новые колонки и колонки без сохранённого места (кнопки, виджеты) —
    // за ближайшей предыдущей по разметке; предыдущей нет — в начало.
    arch.forEach((key, index) => {
        if (placed.has(key)) {
            return;
        }
        let at = 0;
        for (let i = index - 1; i >= 0; i--) {
            const pos = result.indexOf(arch[i]);
            if (pos !== -1) {
                at = pos + 1;
                break;
            }
        }
        result.splice(at, 0, key);
        placed.add(key);
    });
    return result;
}

/**
 * Какая настройка действует: своя важнее общей; нет ни той, ни другой —
 * null (список как у ядра, со старым выбором браузера).
 */
export function effectivePrefs(own, common) {
    return own || common || null;
}

/** Пустая настройка. */
export function emptyPrefs() {
    return { v: PREFS_VERSION, order: [], widths: {}, visible: {} };
}

/** Копия настройки без лишних ключей (исходную не меняет). */
export function copyPrefs(prefs) {
    const source = prefs || {};
    return {
        v: PREFS_VERSION,
        order: Array.isArray(source.order) ? [...source.order] : [],
        widths: { ...(source.widths || {}) },
        visible: { ...(source.visible || {}) },
    };
}

/** Ширина: целое в пределах MIN_WIDTH…MAX_WIDTH или null. */
export function cleanWidth(px) {
    const value = Math.round(Number(px));
    if (!Number.isFinite(value) || value <= 0) {
        return null;
    }
    return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, value));
}

/**
 * Новая настройка человека после правки.
 *
 * Копирование при записи: у человека без своей настройки первая правка
 * создаёт свою как КОПИЮ общей плюс правку — иначе потянул одну ширину и
 * потерял общий порядок. Нет и общей — основа seed: то, что человек видит
 * сейчас (старый выбор колонок в браузере), чтобы первая галочка не
 * вернула молча остальные колонки к виду.
 *
 * @param {Object|null} own своя настройка
 * @param {Object|null} common общая
 * @param {{visible?: Object, widths?: Object, order?: string[],
 *          resetWidths?: boolean, replace?: Object}} change
 *   visible / widths — слить (ширина null — снять); order — заменить;
 *   resetWidths — снять все ширины; replace — заменить всё целиком.
 * @param {Object} [seed] основа, когда нет ни своей, ни общей
 * @returns {Object}
 */
export function changePrefs(own, common, change, seed) {
    const base = copyPrefs(own || common || seed || emptyPrefs());
    if (change.replace) {
        return copyPrefs(change.replace);
    }
    if (change.order) {
        base.order = [...change.order];
    }
    if (change.resetWidths) {
        base.widths = {};
    }
    for (const [key, value] of Object.entries(change.widths || {})) {
        const width = value === null ? null : cleanWidth(value);
        if (width === null) {
            delete base.widths[key];
        } else {
            base.widths[key] = width;
        }
    }
    for (const [key, value] of Object.entries(change.visible || {})) {
        base.visible[key] = Boolean(value);
    }
    return base;
}

/**
 * Чистка перед сохранением: только колонки из разметки вида. Чистим по
 * разметке, а не по тому, что сейчас видно: колонка, спрятанная условием
 * (column_invisible от состояния документа), свой выбор не теряет.
 *
 * @param {Object} prefs
 * @param {string[]} archKeys
 * @returns {Object}
 */
export function prunePrefs(prefs, archKeys) {
    const known = new Set((archKeys || []).filter(isFieldKey));
    const result = copyPrefs(prefs);
    result.order = [...new Set(result.order)].filter((key) => known.has(key));
    for (const name of ["widths", "visible"]) {
        for (const key of Object.keys(result[name])) {
            if (!known.has(key)) {
                delete result[name][key];
            }
        }
    }
    return result;
}

/** Настройка пустая — хранить нечего. */
export function isEmptyPrefs(prefs) {
    return (
        !prefs ||
        (!(prefs.order || []).length &&
            !Object.keys(prefs.widths || {}).length &&
            !Object.keys(prefs.visible || {}).length)
    );
}

/** Две настройки одинаковы (для «Готово» без правок). */
export function samePrefs(a, b) {
    const norm = (prefs) => {
        const p = copyPrefs(prefs);
        return JSON.stringify([
            p.order,
            Object.entries(p.widths).sort(),
            Object.entries(p.visible).sort(),
        ]);
    };
    return norm(a) === norm(b);
}

/**
 * Почему колонку нельзя скрыть.
 *   "pinned"   — ручка перетаскивания строк или название записи: без них
 *                список не открыть и не переставить;
 *   "required" — обязательное поле в редактируемой таблице: спрячешь —
 *                новую строку не сохранить. Колонку optional ядро скрывать
 *                разрешает — там не мешаем.
 * Двигать такие колонки можно (кроме ручки: она всегда первая).
 *
 * @returns {"pinned"|"required"|null}
 */
export function lockReason(column, { isTitle = false, editable = false, required = false } = {}) {
    if (!column || column.type !== "field") {
        return null;
    }
    if (column.widget === "handle") {
        return "pinned";
    }
    if (column.optional) {
        // optional="…" — ядро и так даёт его скрыть; не отнимаем.
        return null;
    }
    if (isTitle) {
        return "pinned";
    }
    if (editable && required) {
        return "required";
    }
    return null;
}

/**
 * Колонка-«название» списка: поле name / display_name / complete_name, а
 * если их нет — первая колонка поля по разметке (не ручка). Колонки с
 * optional не берём: их ядро разрешает прятать. Колонки, спрятанные
 * условием column_invisible, тоже не берём: замок на невидимой колонке
 * ничего не держит, а настоящая колонка названия («Деталь» в таблицах
 * изделия, перед ней служебная calc_mode) осталась бы без замка.
 *
 * @param {Object[]} columns колонки полей, которые можно настраивать
 * @param {(column: Object) => boolean} [isHidden] спрятана ли условием
 * @returns {string|null} id колонки
 */
export function titleColumnId(columns, isHidden = () => false) {
    const fields = (columns || []).filter(
        (column) =>
            column.type === "field" &&
            column.widget !== "handle" &&
            !column.optional &&
            !column.relatedPropertyField &&
            !isHidden(column)
    );
    for (const name of TITLE_FIELDS) {
        const found = fields.find((column) => column.name === name);
        if (found) {
            return found.id;
        }
    }
    return fields.length ? fields[0].id : null;
}

/**
 * Постоянное значение условия column_invisible / required: true / false,
 * а для выражения, которое зависит от записи, — null.
 */
export function constBool(value) {
    if (value === true || value === false) {
        return value;
    }
    if (value === undefined || value === null || value === "") {
        return false;
    }
    const text = String(value).trim();
    if (["1", "True", "true"].includes(text)) {
        return true;
    }
    if (["0", "False", "false", ""].includes(text)) {
        return false;
    }
    return null;
}

/**
 * Можно ли спрятать колонку: последняя видимая колонка поля остаётся
 * всегда. Без неё таблица — одна ручка, а в редактируемой таблице ядро
 * падает на «Добавить строку» (onPatched берёт columns[0]).
 *
 * @param {{key: string, visible: boolean}[]} rows строки меню / окна
 * @param {string} key что прячем
 */
export function canHide(rows, key) {
    return (rows || []).some((row) => row.key !== key && row.visible);
}

/**
 * Ширина, ниже которой колонку не сохраняем и не рисуем: минимум ядра для
 * типа поля (FIELD_WIDTHS: строка 80, дата — по замеру, число 71/93…) и,
 * для колонки названия, ширина её содержимого (номер СМ-, ДОБ-, ЛР-, РК-
 * не обрезаем), но не больше TITLE_FLOOR_CAP: длинное название клиента
 * сузить можно.
 *
 * @param {number} coreMin минимум ядра
 * @param {number} [contentWidth] ширина содержимого (только название)
 * @returns {number}
 */
export function widthFloor(coreMin, contentWidth = 0) {
    const core = Number.isFinite(coreMin) && coreMin > 0 ? coreMin : MIN_WIDTH;
    const content = Number.isFinite(contentWidth) && contentWidth > 0
        ? Math.min(contentWidth, TITLE_FLOOR_CAP)
        : 0;
    return Math.min(MAX_WIDTH, Math.ceil(Math.max(MIN_WIDTH, core, content)));
}

/** Сохранённая ширина не ниже пола (null — ширины нет). */
export function floorWidth(px, floor) {
    const width = cleanWidth(px);
    if (width === null) {
        return null;
    }
    return Math.min(MAX_WIDTH, Math.max(width, Math.ceil(floor || 0)));
}

/**
 * Таблица с разделами (строки счёта и заказа, account
 * SectionAndNoteListRenderer.getSectionColumns): строка раздела — ручка,
 * название на всю ширину и итоги раздела по своим колонкам В ТЕКУЩЕМ
 * ПОРЯДКЕ. Колонку с итогом поставили левее другой — итог раздела встал бы
 * под чужим заголовком. Поэтому колонки с итогом всегда правее остальных,
 * между собой — в порядке человека.
 *
 * @param {Object[]} columns
 * @param {string[]} aggregated имена полей с итогом раздела
 * @returns {Object[]}
 */
export function aggregatesLast(columns, aggregated) {
    const names = new Set(aggregated || []);
    if (!names.size) {
        return columns;
    }
    const isAgg = (column) => column.type === "field" && names.has(column.name);
    const rest = columns.filter((column) => !isAgg(column));
    if (rest.length === columns.length) {
        return columns;
    }
    return [...rest, ...columns.filter(isAgg)];
}

/**
 * Куда встаёт колонка, брошенная перетаскиванием заголовка: перед
 * служебной колонкой (кнопка, виджет) встать нельзя — у неё нет своего
 * места, она идёт за соседней колонкой поля по разметке. Тогда место —
 * перед следующей колонкой поля (или в конец), и черта рисуется там же.
 *
 * @param {string[]} cellKeys ключи колонок шапки слева направо
 * @param {number} at куда указывает мышь
 * @returns {number}
 */
export function snapDropIndex(cellKeys, at) {
    let index = at;
    while (index < cellKeys.length && !isFieldKey(cellKeys[index])) {
        index++;
    }
    return index;
}

/**
 * Правка по окну «Колонки»: только то, что человек поменял в окне, —
 * сервер сливает её с хранимой настройкой (другая вкладка браузера могла
 * сохранить своё, и полная запись из этой вкладки затёрла бы его).
 *
 * @param {Object[]} before строки окна при открытии
 * @param {Object[]} after строки по «Готово»
 * @param {string[]|null} order полный порядок, если он поменялся
 * @returns {{visible: Object, widths: Object, order?: string[]}}
 */
export function rowsChange(before, after, order = null) {
    const was = new Map((before || []).map((row) => [row.key, row]));
    const change = { visible: {}, widths: {} };
    for (const row of after || []) {
        const old = was.get(row.key);
        if (!old) {
            continue;
        }
        if (!row.lock && Boolean(row.visible) !== Boolean(old.visible)) {
            change.visible[row.key] = Boolean(row.visible);
        }
        if ((old.width || null) !== (row.width || null)) {
            change.widths[row.key] = row.width || null;
        }
    }
    const keys = (rows) => (rows || []).map((row) => row.key).join("\n");
    if (order && keys(before) !== keys(after)) {
        change.order = [...order];
    }
    return change;
}

/**
 * Видна ли колонка по настройке. Для закреплённой — всегда да.
 *
 * @param {Object|null} prefs действующая настройка
 * @param {string} key
 * @param {boolean} archDefault видна ли по разметке вида
 * @param {boolean} [locked]
 */
export function isVisible(prefs, key, archDefault, locked = false) {
    if (locked) {
        return true;
    }
    if (prefs && prefs.visible && key in prefs.visible) {
        return Boolean(prefs.visible[key]);
    }
    return archDefault;
}

/**
 * Отличия от вида — основа (seed) первой своей настройки и запись окна
 * «Колонки»: в visible идут только колонки, видимые не так, как в разметке.
 *
 * @param {{key: string, visible: boolean, archDefault: boolean,
 *          lock?: string|null}[]} rows
 * @returns {Object} visible
 */
export function visibleDiff(rows) {
    const visible = {};
    for (const row of rows || []) {
        if (!row.lock && Boolean(row.visible) !== Boolean(row.archDefault)) {
            visible[row.key] = Boolean(row.visible);
        }
    }
    return visible;
}

/**
 * Применить настройку к колонкам, которые отдало ядро (и патчи шага 24).
 *
 * @param {Object[]} columns активные колонки (уже без column_invisible и
 *   скрытых optional)
 * @param {Object|null} prefs действующая настройка
 * @param {{keys: Map<string,string>, archKeys: string[], pinnedKeys: string[],
 *          hideable: Set<string>}} info
 * @returns {{columns: Object[], widths: Map<string, number>}} колонки в
 *   новом порядке без скрытых настройкой; ширины по id колонки
 */
export function applyPrefs(columns, prefs, info) {
    const widths = new Map();
    if (!prefs) {
        return { columns, widths };
    }
    const keyOf = (column) => info.keys.get(column.id);
    const kept = columns.filter((column) => {
        const key = keyOf(column);
        if (!key || !info.hideable.has(key) || column.optional) {
            // optional ядро уже отфильтровало по нашей видимости
            // (computeOptionalActiveFields), служебные не прячем.
            return true;
        }
        return !(prefs.visible && prefs.visible[key] === false);
    });
    const order = orderKeys(info.archKeys, prefs.order, info.pinnedKeys);
    const position = new Map(order.map((key, index) => [key, index]));
    const sorted = kept
        .map((column, index) => ({ column, index }))
        .sort((a, b) => {
            const pa = position.has(keyOf(a.column)) ? position.get(keyOf(a.column)) : Infinity;
            const pb = position.has(keyOf(b.column)) ? position.get(keyOf(b.column)) : Infinity;
            return pa - pb || a.index - b.index;
        })
        .map(({ column }) => column);
    for (const column of sorted) {
        const key = keyOf(column);
        const width = key && prefs.widths ? cleanWidth(prefs.widths[key]) : null;
        if (width && column.type === "field" && isFieldKey(key)) {
            widths.set(column.id, width);
        }
    }
    return { columns: sorted, widths };
}

/**
 * Перенос колонки (окно «Колонки», перетаскивание заголовка).
 *
 * @param {string[]} order полный порядок ключей
 * @param {string} key что переносим
 * @param {string|null} beforeKey перед какой колонкой; null — в конец
 * @param {string[]} [pinnedKeys] перед ними ставить нельзя
 * @returns {string[]}
 */
export function moveKey(order, key, beforeKey, pinnedKeys = []) {
    const pinned = new Set(pinnedKeys);
    if (pinned.has(key) || !order.includes(key)) {
        return [...order];
    }
    const result = order.filter((k) => k !== key);
    let at = beforeKey && result.includes(beforeKey) ? result.indexOf(beforeKey) : result.length;
    let lastPinned = -1;
    result.forEach((k, i) => {
        if (pinned.has(k)) {
            lastPinned = i;
        }
    });
    at = Math.max(at, lastPinned + 1);
    result.splice(at, 0, key);
    return result;
}

/**
 * Порядок из окна «Колонки» поверх полного порядка: колонки окна встают в
 * новом порядке на места, которые они занимали; остальные (спрятанные
 * условием column_invisible, их в окне нет) остаются на своих местах.
 *
 * @param {string[]} full полный порядок ключей полей
 * @param {string[]} rowOrder ключи строк окна в новом порядке
 * @returns {string[]}
 */
export function mergeOrder(full, rowOrder) {
    const inRows = new Set(rowOrder);
    const queue = rowOrder.filter((key) => full.includes(key));
    let next = 0;
    const result = full.map((key) => (inRows.has(key) ? queue[next++] : key));
    for (const key of rowOrder) {
        if (!result.includes(key)) {
            result.push(key);
        }
    }
    return result;
}

/** Строки окна «Колонки» не поменялись (порядок, галочки, ширины). */
export function sameRows(a, b) {
    const norm = (rows) =>
        JSON.stringify((rows || []).map((row) => [row.key, Boolean(row.visible), row.width || null]));
    return norm(a) === norm(b);
}

/**
 * Обязательное ли поле в разметке: required="1" / "True" или выражение
 * (условие считаем обязательностью — осторожно: спрятанную обязательную
 * колонку нельзя заполнить в строке).
 */
export function isRequiredExpr(value) {
    if (value === true) {
        return true;
    }
    if (typeof value !== "string") {
        return false;
    }
    const text = value.trim();
    return Boolean(text) && !["0", "False", "false"].includes(text);
}
