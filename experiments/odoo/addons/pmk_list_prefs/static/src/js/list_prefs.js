/** @odoo-module **/
/**
 * Колонки у каждого (разбор UX, шаг 55, 08.10.2026) — во всех списках
 * основного окна и в таблицах внутри форм.
 *
 * Антон, 07.10: «Попробовал изменить размеры колонок в таблице, но после
 * перезагрузки всё вернулось обратно… Чтобы каждый мог донастроить систему
 * для себя»; «нужно сделать возможность менять местами колонки, а так же
 * включать/отключать колонки, которые мы дополнительно создали».
 *
 * ЧТО ДЕЛАЕТ. Настройка списка хранится на сервере у человека (модель
 * pmk.list.prefs) и переезжает с ним на любой компьютер:
 *   1. ширина — потянул край заголовка, отпустил: ширина этой колонки
 *      запомнилась; двойной щелчок по краю — все ширины списка сняты;
 *   2. порядок — окно «Колонки» (⚙ → «Настроить колонки…») или
 *      перетаскивание заголовка мышью;
 *   3. видимость — галочки в ⚙ для ВСЕХ колонок полей, не только optional.
 *      Нельзя спрятать ручку строк, название записи и обязательное поле
 *      таблицы, которую правят прямо в списке;
 *   4. администратор — «Сделать так у всех» в окне «Колонки»: у кого нет
 *      своей настройки, видят общую; своя всегда важнее.
 * Нет ни своей, ни общей — список ровно как у ядра (старый выбор колонок в
 * браузере тоже действует). Есть настройка — выбор браузера не действует:
 * иначе он молча перебивал бы её («Прайс от» в «Поставщиках прайсов»).
 *
 * КАК. Только патч прототипа ListRenderer, без правки шаблонов: в Odoo 19
 * расширение шаблона web.ListRenderer не доходит до первичных наследников,
 * зарегистрированных раньше (account, stock, pmk_calc.ProductRows…).
 * Штатное меню ⚙ рисует то, что отдают optionalFieldGroups и
 * displayOptionalFields, и по нажатию зовёт toggleOptionalField /
 * toggleOptionalFieldGroup — их и подменяем. Порядок и скрытие — в
 * getActiveColumns: от this.columns ядро считает шапку, строки, группы и
 * итоги. Ширина — атрибут колонки width (его ядро и так соблюдает,
 * column_width_hook.js, getWidthSpecs).
 *
 * ⚠️ Скрываем убиранием из this.columns, НЕ column_invisible: поле остаётся
 * в activeFields и грузится как было (column_invisible у вложенной таблицы
 * режет загрузку её наборов — грабля из памяти).
 *
 * ГРАНИЦА. Колонки свойств (properties) — как у ядра: выбор в браузере,
 * без перестановки. На телефоне ширины не применяются (раскладка ядра),
 * перетаскивания нет — порядок стрелками в окне. Поле, которого нет в виде
 * списка, окном не добавить — правкой вида.
 *
 * Выключить: убрать модуль pmk_list_prefs (все настройки — в его таблице)
 * или HEADER_DRAG = false — только перетаскивание заголовка.
 */
import { status, useEffect, onWillUnmount } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { user } from "@web/core/user";
import { patch } from "@web/core/utils/patch";
import { AGGREGATABLE_FIELD_TYPES } from "@web/model/relational_model/utils";
import { ListController } from "@web/views/list/list_controller";
import { ListRenderer } from "@web/views/list/list_renderer";
import { FIELD_WIDTHS } from "@web/views/list/column_width_hook";
import { ColumnsDialog } from "@pmk_list_prefs/js/columns_dialog";
import { listPrefsStore } from "@pmk_list_prefs/js/list_prefs_store";
import {
    WIDTH_EPSILON,
    aggregatesLast,
    applyPrefs,
    canHide,
    changePrefs,
    cleanWidth,
    columnKeys,
    constBool,
    copyPrefs,
    effectivePrefs,
    emptyPrefs,
    floorWidth,
    isFieldKey,
    isRequiredExpr,
    isVisible,
    lockReason,
    mergeOrder,
    moveKey,
    orderKeys,
    prunePrefs,
    rowsChange,
    samePrefs,
    snapDropIndex,
    titleColumnId,
    viewKey,
    visibleDiff,
    widthFloor,
} from "@pmk_list_prefs/js/list_prefs_rules";

/** Перетаскивание заголовка колонки мышью (шаг 55.2). */
export const HEADER_DRAG = true;
/** Сдвиг мыши, после которого нажатие на заголовок — перенос, а не сортировка. */
const DRAG_THRESHOLD = 6;
const MENU_GROUP = "pmk_columns";
/** Минимум ядра для колонки без своего (column_width_hook.js). */
const DEFAULT_MIN_WIDTH = 80;
/** Сколько строк мерить, когда ищем ширину содержимого названия. */
const MEASURE_ROWS = 80;
const LAST_COLUMN =
    "Хотя бы одна колонка должна остаться видимой — эту спрятать нельзя.";

// Колонка с шириной — новый объект; запоминаем его, чтобы поля не
// перерисовывались на каждую отрисовку (как withRowDigits шага 24).
const withWidth = new WeakMap();

function horizontalPadding(el) {
    const style = getComputedStyle(el);
    return parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
}

patch(ListRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        this.pmkKey = this.pmkComputeKey();
        this.pmkWidthsDirty = false;

        // Объект хука ширин — обычный литерал; свойства подменяем до первой
        // отрисовки, шаблон берёт их при отрисовке.
        const widthsApi = this.columnWidths;
        const coreStartResize = widthsApi.onStartResize;
        const coreResetWidths = widthsApi.resetWidths;
        widthsApi.onStartResize = (ev) => {
            coreStartResize(ev);
            this.pmkWatchResize(ev);
        };
        widthsApi.resetWidths = (...args) => {
            if (!this.pmkDropWidths()) {
                coreResetWidths(...args);
            }
        };
        // Ширины из настройки сменились без смены колонок (окно «Колонки»,
        // сброс): ядро держит замороженные ширины, пока набор колонок тот
        // же, — пересчитать после отрисовки. Эффект зарегистрирован после
        // эффекта ядра и идёт следом за ним.
        useEffect(() => {
            if (!this.pmkWidthsDirty) {
                return;
            }
            this.pmkWidthsDirty = false;
            if (this.tableRef.el && this.constructor.useMagicColumnWidths) {
                coreResetWidths();
            }
        });
        if (HEADER_DRAG) {
            this.pmkSetupHeaderDrag();
        }
    },

    // ─── Ключи и настройка ─────────────────────────────────────────────────
    pmkComputeKey() {
        const config = this.env.config || {};
        const nested = this.props.nestedKeyOptionalFieldsData;
        if (nested && nested.model && nested.field) {
            return viewKey({
                parentModel: nested.model,
                fieldName: nested.field,
                viewId: config.viewId,
            });
        }
        return viewKey({
            model: this.props.list.resModel,
            viewId: config.viewId,
            actionId: config.actionId,
        });
    },

    pmkPrefs() {
        return effectivePrefs(
            listPrefsStore.own(this.pmkKey),
            listPrefsStore.common(this.pmkKey)
        );
    },

    pmkSource() {
        if (listPrefsStore.own(this.pmkKey)) {
            return "own";
        }
        return listPrefsStore.common(this.pmkKey) ? "common" : "view";
    },

    /** Ключи, замки и штатная видимость колонок; на одну отрисовку. */
    pmkInfo() {
        const columns = this.allColumns || [];
        const fieldColumns = columns.filter(
            (column) => column.type === "field" && !column.relatedPropertyField
        );
        // column_invisible от состояния документа меняется без смены колонок:
        // такие условия входят в ключ кэша (постоянные «1» — нет, их много).
        const hiddenNow = new Map();
        let signature = "";
        for (const column of fieldColumns) {
            const fixed = constBool(column.column_invisible);
            const hidden = fixed === null ? Boolean(this.evalColumnInvisible(column.column_invisible)) : fixed;
            hiddenNow.set(column.id, hidden);
            if (fixed === null) {
                signature += hidden ? "1" : "0";
            }
        }
        if (
            this.pmkInfoCache &&
            this.pmkInfoCache.columns === columns &&
            this.pmkInfoCache.signature === signature
        ) {
            return this.pmkInfoCache.info;
        }
        const keys = columnKeys(columns);
        const archKeys = columns.map((column) => keys.get(column.id));
        const titleId = titleColumnId(fieldColumns, (column) => hiddenNow.get(column.id));
        const editable = Boolean(this.props.editable);
        const byKey = new Map();
        const pinnedKeys = [];
        const hideable = new Set();
        for (const column of fieldColumns) {
            const key = keys.get(column.id);
            const field = (this.fields && this.fields[column.name]) || {};
            const lock = lockReason(column, {
                isTitle: column.id === titleId,
                editable,
                required: Boolean(field.required) || isRequiredExpr(column.required),
            });
            const handle = column.widget === "handle";
            byKey.set(key, {
                key,
                column,
                lock,
                handle,
                dup: key !== column.name,
                archDefault: column.optional ? column.optional === "show" : true,
            });
            if (handle) {
                pinnedKeys.push(key);
            }
            if (!lock) {
                hideable.add(key);
            }
        }
        const info = { keys, archKeys, pinnedKeys, hideable, byKey, titleId };
        this.pmkInfoCache = { columns, signature, info };
        return info;
    },

    pmkOrderedKeys() {
        const info = this.pmkInfo();
        const prefs = this.pmkPrefs();
        return orderKeys(info.archKeys, prefs && prefs.order, info.pinnedKeys);
    },

    pmkIsShown(meta) {
        if (meta.lock) {
            return true;
        }
        const prefs = this.pmkPrefs();
        if (prefs) {
            return isVisible(prefs, meta.key, meta.archDefault);
        }
        if (meta.column.optional) {
            return Boolean(this.optionalActiveFields[meta.column.name]);
        }
        return true;
    },

    pmkLabel(column) {
        const field = (this.fields && this.fields[column.name]) || {};
        return String(column.label || field.string || column.name);
    },

    /** Минимум ширины колонки у ядра — тот же расчёт, что getWidthSpecs. */
    pmkCoreMinWidth(column) {
        if (!column || column.type !== "field") {
            return 0;
        }
        let width;
        try {
            if (column.field && column.field.listViewWidth) {
                width = column.field.listViewWidth;
                if (typeof width === "function") {
                    width = width({
                        type: column.fieldType,
                        hasLabel: column.hasLabel,
                        options: column.options,
                    });
                }
            } else {
                width = FIELD_WIDTHS[column.widget || column.fieldType];
            }
        } catch {
            width = null;
        }
        const min = Array.isArray(width) ? width[0] : width;
        return Number.isFinite(min) && min > 0 ? min : DEFAULT_MIN_WIDTH;
    },

    /** Ширина содержимого колонки по строкам на экране (без отступов). */
    pmkContentWidth(cellIndex) {
        const table = this.tableRef.el;
        if (!table) {
            return 0;
        }
        let widest = 0;
        const head = table.querySelector(":scope > thead > tr");
        const width = head ? head.children.length : 0;
        const rows = table.querySelectorAll(":scope > tbody > tr.o_data_row");
        for (let i = 0; i < rows.length && i < MEASURE_ROWS; i++) {
            // Строки разделов и заметок (ячейка на несколько колонок) не меряем.
            if (rows[i].children.length !== width) {
                continue;
            }
            const cell = rows[i].children[cellIndex];
            if (cell && !cell.classList.contains("o_hidden")) {
                widest = Math.max(widest, cell.scrollWidth - horizontalPadding(cell));
            }
        }
        return widest;
    },

    /** Колонки для меню ⚙ и окна — в действующем порядке. */
    pmkRows() {
        const info = this.pmkInfo();
        const prefs = this.pmkPrefs();
        const rows = [];
        for (const key of this.pmkOrderedKeys()) {
            const meta = info.byKey.get(key);
            if (!meta || meta.handle || this.evalColumnInvisible(meta.column.column_invisible)) {
                continue;
            }
            rows.push({
                key,
                label: this.pmkLabel(meta.column),
                visible: this.pmkIsShown(meta),
                archDefault: meta.archDefault,
                lock: meta.lock,
                width: prefs && prefs.widths ? cleanWidth(prefs.widths[key]) : null,
            });
        }
        return rows;
    },

    /** Есть что настраивать — показать ⚙. Один раз на отрисовку: шаблон
     *  спрашивает displayOptionalFields у каждой строки. */
    get pmkMenuAvailable() {
        const info = this.pmkInfo();
        if (info.menuAvailable === undefined) {
            const rows = this.pmkRows();
            info.menuAvailable = rows.length >= 2 || rows.some((row) => !row.lock);
        }
        return info.menuAvailable;
    },

    /**
     * Правка своей настройки: копия своей / общей / того, что видно сейчас,
     * плюс правка; чистка по разметке; запись в фоне. Возвращает false, если
     * ничего не поменялось.
     */
    pmkChange(change) {
        const own = listPrefsStore.own(this.pmkKey);
        const common = listPrefsStore.common(this.pmkKey);
        const seed = own || common ? null : { ...emptyPrefs(), visible: visibleDiff(this.pmkRows()) };
        const next = prunePrefs(changePrefs(own, common, change, seed), this.pmkInfo().archKeys);
        if (own && samePrefs(own, next)) {
            return false;
        }
        this.pmkSave(next, change);
        return true;
    },

    /**
     * Запись своей настройки. Вместе с ней уходит сама правка: если в базе
     * своя настройка уже есть (её могла сохранить другая вкладка браузера,
     * а кэш этой вкладки старый), сервер сливает правку с хранимой, а не
     * затирает её целиком. Ответ сервера — то, что теперь хранится; не
     * совпало с экраном — перерисовать.
     */
    pmkSave(next, change) {
        listPrefsStore
            .saveOwn(this.env, this.pmkKey, this.props.list.resModel, next, change)
            .then((saved) => {
                if (saved && saved !== next && !samePrefs(saved, next)) {
                    this.pmkRerender(true);
                }
            });
    },

    /** Настройка по строкам окна «Колонки». */
    pmkPrefsFromRows(rows) {
        const base = copyPrefs(this.pmkPrefs() || emptyPrefs());
        const inRows = new Set(rows.map((row) => row.key));
        const keep = (map) =>
            Object.fromEntries(Object.entries(map).filter(([key]) => !inRows.has(key)));
        const visible = { ...keep(base.visible), ...visibleDiff(rows) };
        const widths = keep(base.widths);
        for (const row of rows) {
            const width = cleanWidth(row.width);
            if (width) {
                widths[row.key] = width;
            }
        }
        const full = this.pmkOrderedKeys().filter(isFieldKey);
        const order = mergeOrder(full, rows.map((row) => row.key));
        return prunePrefs({ order, widths, visible }, this.pmkInfo().archKeys);
    },

    pmkRerender(widthsChanged = false) {
        if (status(this) === "destroyed") {
            return;
        }
        if (widthsChanged) {
            this.pmkWidthsDirty = true;
        }
        this.render();
    },

    // ─── Видимость: меню ⚙ ─────────────────────────────────────────────────
    computeOptionalActiveFields() {
        const result = super.computeOptionalActiveFields(...arguments);
        const prefs = this.pmkPrefs();
        for (const meta of this.pmkInfo().byKey.values()) {
            if (meta.dup) {
                continue;
            }
            const name = meta.column.name;
            if (meta.column.optional) {
                if (prefs) {
                    result[name] = isVisible(prefs, meta.key, meta.archDefault, Boolean(meta.lock));
                }
            } else {
                // Не optional: false — спрятана нашей настройкой (итоги и
                // «Экспорт» её пропускают, как спрятанную optional).
                result[name] = isVisible(prefs, meta.key, true, Boolean(meta.lock));
            }
        }
        return result;
    },

    getActiveColumns() {
        const columns = super.getActiveColumns(...arguments);
        const prefs = this.pmkPrefs();
        if (!prefs) {
            return columns;
        }
        const applied = applyPrefs(columns, prefs, this.pmkInfo());
        const widths = applied.widths;
        let arranged = applied.columns;
        if (typeof this.getSectionColumns === "function" && Array.isArray(this.props.aggregatedFields)) {
            arranged = aggregatesLast(arranged, this.props.aggregatedFields);
        }
        if (this.env.isSmall || !this.constructor.useMagicColumnWidths || !widths.size) {
            return arranged;
        }
        return arranged.map((column) => {
            const saved = widths.get(column.id);
            // Не уже минимума ядра: со старой записью или после «Сделать так
            // у всех» номер и дата не обрезаются (ширина из настройки снимает
            // минимум ядра, getWidthSpecs).
            const width = saved ? floorWidth(saved, this.pmkCoreMinWidth(column)) : null;
            if (!width) {
                return column;
            }
            let entry = withWidth.get(column);
            if (!entry || entry.width !== width) {
                entry = {
                    width,
                    column: { ...column, attrs: { ...(column.attrs || {}), width: `${width}px` } },
                };
                withWidth.set(column, entry);
            }
            return entry.column;
        });
    },

    /**
     * Строка группы: название группы занимает колонки до первой колонки с
     * итогом. Человек поставил колонку с итогом первой — ядро отдало бы
     * названию группы только узкую колонку галочек («…» вместо названия).
     * Тогда в строках групп итог первой колонки не показываем (в итоговой
     * строке таблицы он остаётся). Без настройки — как у ядра.
     */
    getFirstAggregateIndex(group) {
        const index = super.getFirstAggregateIndex(...arguments);
        if (index !== 0 || !group || !this.pmkPrefs()) {
            return index;
        }
        const aggregates = group.aggregates || {};
        return this.columns.findIndex(
            (column, i) =>
                i > 0 &&
                column.name in aggregates &&
                column.widget !== "handle" &&
                AGGREGATABLE_FIELD_TYPES.includes((this.fields[column.name] || {}).type)
        );
    },

    getLastAggregateIndex(group) {
        const index = super.getLastAggregateIndex(...arguments);
        if (index === 0 && group && this.pmkPrefs()) {
            return -1;
        }
        return index;
    },

    get displayOptionalFields() {
        return super.displayOptionalFields || this.pmkMenuAvailable;
    },

    get optionalFieldGroups() {
        const groups = super.optionalFieldGroups;
        if (!this.pmkMenuAvailable) {
            return groups;
        }
        const ours = this.pmkRows()
            .filter((row) => !row.lock)
            .map((row) => ({ label: row.label, name: row.key, value: row.visible }));
        // Группы свойств ядра (у них есть id) — без изменений.
        const propertyGroups = groups.filter((group) => group.id !== undefined);
        const result = ours.length ? [{ optionalFields: ours }] : [];
        result.push(...propertyGroups);
        result.push({ id: MENU_GROUP, displayName: "Настроить колонки…", optionalFields: [] });
        return result;
    },

    async toggleOptionalField(name) {
        const meta = this.pmkInfo().byKey.get(name);
        if (!meta || meta.column.relatedPropertyField) {
            return super.toggleOptionalField(...arguments);
        }
        if (meta.lock) {
            return;
        }
        const shown = this.pmkIsShown(meta);
        if (shown && !canHide(this.pmkRows(), name)) {
            this.env.services.notification.add(LAST_COLUMN, { type: "warning" });
            return;
        }
        if (this.pmkChange({ visible: { [name]: !shown } })) {
            this.pmkRerender();
        }
    },

    toggleOptionalFieldGroup(groupId) {
        if (groupId === MENU_GROUP) {
            // Пункты меню ⚙ ядро держит открытым (closingMode none), а меню
            // лежит выше окон по z-index — закрыть его своей же кнопкой.
            const toggler =
                this.tableRef.el &&
                this.tableRef.el.querySelector(":scope > thead .o_optional_columns_dropdown button");
            if (
                toggler &&
                (toggler.getAttribute("aria-expanded") === "true" ||
                    toggler.classList.contains("show"))
            ) {
                toggler.click();
            }
            return this.pmkOpenColumns();
        }
        return super.toggleOptionalFieldGroup(...arguments);
    },

    // ─── Окно «Колонки» ────────────────────────────────────────────────────
    async pmkOpenColumns() {
        const list = this.props.list;
        if (list.editedRecord) {
            const left = await list.leaveEditMode();
            if (!left) {
                return;
            }
        }
        const dialog = this.env.services && this.env.services.dialog;
        if (!dialog || status(this) === "destroyed") {
            return;
        }
        const source = this.pmkSource();
        const hasCommon = Boolean(listPrefsStore.common(this.pmkKey));
        const widthsOf = () => JSON.stringify((this.pmkPrefs() || {}).widths || {});
        const rowsBefore = this.pmkRows();
        dialog.add(ColumnsDialog, {
            rows: rowsBefore,
            source,
            resetLabel:
                source === "own" ? (hasCommon ? "Вернуть общую" : "Вернуть штатную") : undefined,
            lastColumnWarning: LAST_COLUMN,
            isAdmin: Boolean(user.isSystem),
            hasCommon,
            isSmall: Boolean(this.env.isSmall),
            onApply: (rows) => {
                const before = widthsOf();
                const next = this.pmkPrefsFromRows(rows);
                // Серверу — и правка окна: другая вкладка могла сохранить
                // своё, полная запись отсюда затёрла бы его.
                const change = rowsChange(rowsBefore, rows, next.order);
                this.pmkSave(next, change);
                this.pmkRerender(widthsOf() !== before);
            },
            onSaveCommon: async (rows) => {
                const next = this.pmkPrefsFromRows(rows);
                const result = await listPrefsStore.saveCommon(
                    this.env,
                    this.pmkKey,
                    list.resModel,
                    next
                );
                if (result) {
                    const count = result.users_on_common || 0;
                    this.env.services.notification.add(
                        `Сохранено для всех. Без своей настройки этот список так увидят: ${count} чел.`,
                        { type: "success" }
                    );
                }
                this.pmkRerender(true);
            },
            onResetOwn: async () => {
                await listPrefsStore.resetOwn(this.env, this.pmkKey);
                // Штатная — значит и без старого выбора браузера.
                try {
                    browser.localStorage.removeItem(this.keyOptionalFields);
                } catch {
                    // хранилище закрыто — выбор браузера и так не читается
                }
                this.pmkRerender(true);
            },
            onResetCommon: async () => {
                await listPrefsStore.resetCommon(this.env, this.pmkKey);
                this.pmkRerender(true);
            },
        });
    },

    // ─── Ширина: край заголовка ────────────────────────────────────────────
    /**
     * Ядро уже начало растягивание (onStartResize). После того как человек
     * отпустил мышь, меряем заголовок так же, как ядро (ширина минус отступы
     * ячейки), и пишем ширину только этой колонки. Esc или правая кнопка —
     * ядро оставляет ширину до перезагрузки, мы не пишем.
     */
    pmkWatchResize(ev) {
        if (this.env.isSmall || !this.constructor.useMagicColumnWidths) {
            return;
        }
        const th = ev.target.closest("th");
        if (!th || !this.tableRef.el) {
            return;
        }
        const index = [...th.parentNode.children].indexOf(th) - (this.hasSelectors ? 1 : 0);
        const column = this.columns[index];
        const key = column && this.pmkInfo().keys.get(column.id);
        if (!key || !isFieldKey(key)) {
            return;
        }
        const before = th.getBoundingClientRect().width;
        const events = ["pointerup", "pointerdown", "keydown"];
        const stop = (event) => {
            if (event.type === "pointerdown" && event.button === 0) {
                return;
            }
            for (const type of events) {
                window.removeEventListener(type, stop);
            }
            if (event.type !== "pointerup" || status(this) === "destroyed") {
                return;
            }
            const after = th.getBoundingClientRect().width;
            if (Math.abs(after - before) < WIDTH_EPSILON) {
                return;
            }
            const measured = after - horizontalPadding(th);
            // Уже минимума ядра не пишем; колонку названия — не уже её
            // содержимого (номер документа не обрезаем), правило 4.
            const isTitle = column.id === this.pmkInfo().titleId;
            const cellIndex = index + (this.hasSelectors ? 1 : 0);
            const floor = widthFloor(
                this.pmkCoreMinWidth(column),
                isTitle ? this.pmkContentWidth(cellIndex) : 0
            );
            const width = floorWidth(measured, floor);
            this.pmkChange({ widths: { [key]: width } });
            if (width > measured + 1) {
                // Сузили ниже пола — сразу показать, какой ширина стала.
                this.pmkRerender(true);
            }
        };
        for (const type of events) {
            window.addEventListener(type, stop);
        }
    },

    /** Двойной щелчок по краю: снять все ширины этого списка. */
    pmkDropWidths() {
        const prefs = this.pmkPrefs();
        if (!prefs || !Object.keys(prefs.widths || {}).length) {
            return false;
        }
        this.pmkChange({ resetWidths: true });
        this.pmkRerender(true);
        return true;
    },

    // ─── Порядок: перетаскивание заголовка (55.2) ──────────────────────────
    pmkSetupHeaderDrag() {
        let drag = null;

        const headerCells = () => {
            const table = this.tableRef.el;
            const row = table && table.querySelector(":scope > thead > tr");
            if (!row) {
                return [];
            }
            const offset = this.hasSelectors ? 1 : 0;
            return this.columns.map((column, i) => ({
                column,
                th: row.children[i + offset],
            }));
        };

        const cleanup = () => {
            window.removeEventListener("pointermove", onMove, true);
            window.removeEventListener("pointerup", onUp, true);
            window.removeEventListener("keydown", onKey, true);
            if (drag) {
                drag.th.classList.remove("o_pmk_col_dragged");
                if (drag.line) {
                    drag.line.remove();
                }
            }
            document.body.classList.remove("o_pmk_col_dragging");
            drag = null;
        };

        const targetIndex = (clientX) => {
            const cells = drag.cells;
            let at = cells.length;
            for (let i = 0; i < cells.length; i++) {
                const rect = cells[i].th.getBoundingClientRect();
                if (clientX < rect.left + rect.width / 2) {
                    at = i;
                    break;
                }
            }
            // Перед ручкой строк (она всегда первая) ставить нельзя.
            const info = this.pmkInfo();
            const cellKeys = cells.map((cell) => info.keys.get(cell.column.id));
            let firstFree = 0;
            while (firstFree < cells.length && info.pinnedKeys.includes(cellKeys[firstFree])) {
                firstFree++;
            }
            // Перед кнопкой или виджетом — нельзя: у них нет своего места,
            // они идут за соседней колонкой поля. Место и черта — перед
            // следующей колонкой поля.
            return snapDropIndex(cellKeys, Math.max(at, firstFree));
        };

        const onMove = (ev) => {
            if (!drag) {
                return;
            }
            if (!drag.started) {
                if (Math.abs(ev.clientX - drag.startX) < DRAG_THRESHOLD) {
                    return;
                }
                drag.started = true;
                drag.cells = headerCells();
                drag.th.classList.add("o_pmk_col_dragged");
                document.body.classList.add("o_pmk_col_dragging");
                drag.line = document.createElement("div");
                drag.line.className = "o_pmk_col_drop";
                document.body.appendChild(drag.line);
            }
            ev.preventDefault();
            drag.at = targetIndex(ev.clientX);
            const cells = drag.cells;
            const table = this.tableRef.el.getBoundingClientRect();
            const head = drag.th.getBoundingClientRect();
            const x =
                drag.at < cells.length
                    ? cells[drag.at].th.getBoundingClientRect().left
                    : cells[cells.length - 1].th.getBoundingClientRect().right;
            const bottom = Math.min(table.bottom, window.innerHeight);
            Object.assign(drag.line.style, {
                left: `${Math.round(x) - 1}px`,
                top: `${Math.round(head.top)}px`,
                height: `${Math.max(head.height, Math.round(bottom - head.top))}px`,
            });
        };

        const onKey = (ev) => {
            if (ev.key === "Escape") {
                cleanup();
            }
        };

        const onUp = (ev) => {
            if (!drag) {
                return;
            }
            const { started, th, key, at, cells } = drag;
            cleanup();
            if (!started || at === undefined || status(this) === "destroyed") {
                return;
            }
            // Отпустили над тем же заголовком — щелчок по нему не сортирует.
            if (th.contains(ev.target)) {
                this.preventReorder = true;
            }
            const from = cells.findIndex((cell) => cell.th === th);
            if (from === -1 || at === from || at === from + 1) {
                return;
            }
            const info = this.pmkInfo();
            const before = at < cells.length ? info.keys.get(cells[at].column.id) : null;
            const current = this.pmkOrderedKeys();
            const full = moveKey(current, key, before, info.pinnedKeys);
            const order = full.filter(isFieldKey);
            if (order.join("\n") === current.filter(isFieldKey).join("\n")) {
                return; // место то же — настройку не заводим
            }
            if (this.pmkChange({ order })) {
                this.pmkRerender();
            }
        };

        const onDown = (ev) => {
            if (
                ev.button !== 0 ||
                ev.pointerType !== "mouse" ||
                this.env.isSmall ||
                this.props.list.model.useSampleModel ||
                this.props.list.editedRecord
            ) {
                return;
            }
            const th = ev.target.closest("th");
            const table = this.tableRef.el;
            if (
                !th ||
                !table ||
                th.parentElement.parentElement.tagName !== "THEAD" ||
                th.closest("table") !== table ||
                ev.target.closest(".o_resize, .o_optional_columns_dropdown, input, button")
            ) {
                return;
            }
            const index = [...th.parentNode.children].indexOf(th) - (this.hasSelectors ? 1 : 0);
            const column = this.columns[index];
            const info = this.pmkInfo();
            const key = column && info.keys.get(column.id);
            const meta = key && info.byKey.get(key);
            if (!meta || meta.handle) {
                return;
            }
            drag = { th, key, startX: ev.clientX, started: false };
            window.addEventListener("pointermove", onMove, true);
            window.addEventListener("pointerup", onUp, true);
            window.addEventListener("keydown", onKey, true);
        };

        useEffect(
            (table) => {
                if (!table) {
                    return;
                }
                table.addEventListener("pointerdown", onDown);
                return () => table.removeEventListener("pointerdown", onDown);
            },
            () => [this.tableRef.el]
        );
        onWillUnmount(cleanup);
    },
});

// «Экспорт» берёт видимые колонки списка (ядро: не column_invisible и
// включённые optional). Колонка, спрятанная нашей настройкой, — тоже не видна.
patch(ListController.prototype, {
    getExportableFields() {
        return super
            .getExportableFields(...arguments)
            .filter((field) => this.optionalActiveFields[field.name] !== false);
    },
});
