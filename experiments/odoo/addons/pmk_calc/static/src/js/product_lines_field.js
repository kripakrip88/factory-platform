/**
 * Список изделий с составом, который раскрывается и правится прямо под строкой.
 *
 * Odoo не умеет вкладывать таблицу в таблицу, а состав нужен там же, где
 * изделия: заходить в отдельное окно ради одной детали — дорого. Поэтому
 * вклиниваемся в разметку строк списка и после строки каждого изделия рисуем
 * свою — с составом и его редактором.
 *
 * ОТКУДА БЕРУТСЯ ДАННЫЕ. Из памяти формы, как и всё остальное в документе.
 * Раньше состав приходил сюда ПУСТЫМИ ЗАГЛУШКАМИ (поля есть, значения нулевые)
 * и его приходилось дочитывать с сервера отдельным запросом — а несохранённые
 * правки в такой запрос, понятно, не попадали. Причина была не в Odoo, а в
 * нашем описании вида: у вложенных наборов не было своей разметки, и читать
 * было нечего. Разметка добавлена в metal_spec_views.xml — запрос больше не
 * нужен, и состав всегда показывает то же, что форма.
 *
 * ПРАВКА В СТРОКЕ ИЗДЕЛИЯ (разбор UX, шаг 56; Антон 07.10: «Почему нельзя
 * изменить цену за штуку в общем списке расчета металлопроката и
 * количество?»). Причина была в виде, а не в модели: список изделий — <list>
 * без editable, и ядро в таком списке рисует запись только для чтения
 * (ListRenderer.isRecordReadonly: «in a x2many non editable list… displayed
 * in readonly»), а щелчок по ячейке открывает окно изделия. Сделать весь
 * список editable нельзя: «Добавить изделие» заводил бы пустую строку на
 * месте вместо окна, щелчок по названию перестал бы открывать окно, Enter в
 * последней строке заводил бы новое изделие.
 *
 * Поэтому правка в строке — только у колонок pmkInlineFieldNames():
 * «Количество, шт» здесь, «Цена за шт» добавляет мост (pmk_bridge,
 * product_lines_cost.js — поле его). Щелчок по ним открывает строку на
 * правку, и поля ввода — только у них; остальные колонки строки — как были,
 * только чтение. Щелчок по прочим колонкам (название, вес, металл) — окно
 * изделия, как раньше. Запись строки та же, что в окне изделия (окно правит
 * ту же запись набора), поэтому пересчёт тот же: вес изделия, «Сумма», итоги
 * и карточки расчёта — onchange документа; в базе количество изделий гасит
 * раскладку листа (spec_layout.py, MetalSpecProductLayout.write). Esc —
 * отмена правки строки: цена и количество возвращаются к тем, что были до
 * щелчка (pmkCancelInline; ядро у существующей записи x2many Esc ничего не
 * откатывает).
 *
 * ПОЧЕМУ ПРАВКА БЕЗ СОХРАНЕНИЯ НА СЕРВЕР. Строки создаются и меняются в
 * наборе документа (addNewRecord / update / delete), то есть живут в памяти
 * до сохранения спецификации. Создавать их сразу в базе нельзя: нажатие
 * «Отменить» в документе обязано отменить и состав.
 */

import { registry } from "@web/core/registry";
import { useState } from "@odoo/owl";
import { ListRenderer } from "@web/views/list/list_renderer";
import { Field } from "@web/views/fields/field";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";

// Разделы состава. Цвет метки у каждого свой — глаз находит нужный блок
// раньше, чем прочитает заголовок. Цвет не единственный признак: есть подпись
// и постоянный порядок разделов (правило color-not-only).
//
// inputs — что показывает редактор строки. Порядок тот же, что в диалоге
// изделия, чтобы привычка работала в обоих местах. wide — поле текстовое или
// со справочником, ему нужна ширина; xwide — справочник с длинными именами
// («Труба профильная прямоугольная 100x50x3»); остальные числовые и узкие.
// placeholder — подсказка пустого поля.
//
// Типоразмер одним полем (разбор UX, шаг 34): поля «Вид проката» больше
// нет — вид подставляется сам из типоразмера (metal_spec.py, type_id), а
// поиск понимает сокращения вида: «уг 50х5», «двут 20ш», «тр 57х3,5»
// (models/size_search.py). Порядок разделов — тот же, что у вкладок окна
// изделия: Прокат · Лист · Метизы · Покрытие.
const SECTIONS = [
    {
        mode: "linear",
        field: "line_linear_ids",
        title: "Линейный прокат",
        short: "Прокат",
        accent: "#6bb6f5",
        inputs: [
            { name: "detail_name", label: "Деталь", wide: true },
            {
                ref: true,
                name: "profile_id",
                label: "Типоразмер",
                xwide: true,
                placeholder: "уг 50х5, двут 20ш, тр 57х3,5",
            },
            { name: "length_mm", label: "Длина, мм" },
            { name: "qty", label: "Кол-во" },
        ],
    },
    {
        mode: "sheet",
        field: "line_sheet_ids",
        title: "Листовой прокат",
        short: "Лист",
        accent: "#4dd0b1",
        inputs: [
            { name: "detail_name", label: "Деталь", wide: true },
            {
                ref: true,
                name: "sheet_id",
                label: "Лист",
                wide: true,
                placeholder: "лист 4, оц 0,5, риф 5",
            },
            { name: "a_mm", label: "A, мм" },
            { name: "b_mm", label: "B, мм" },
            { name: "qty", label: "Кол-во" },
        ],
    },
    {
        mode: "fastener",
        field: "line_fastener_ids",
        title: "Метизы",
        short: "Метизы",
        accent: "#9aa9bd",
        inputs: [
            { name: "detail_name", label: "Деталь", wide: true },
            { ref: true, name: "fastener_id", label: "Метиз", wide: true },
            { name: "qty", label: "Кол-во" },
        ],
    },
    {
        mode: "paint",
        field: "line_paint_ids",
        title: "Лакокрасочное покрытие",
        short: "Покрытие",
        accent: "#f08fb0",
        inputs: [
            { name: "detail_name", label: "Участок", wide: true },
            { ref: true, name: "paint_id", label: "Покрытие", wide: true },
            { name: "area_m2", label: "Площадь, м²" },
            { name: "paint_thickness_um", label: "Толщина, мкм" },
        ],
    },
];

const num = (value) => (value || 0).toLocaleString("ru-RU", { maximumFractionDigits: 3 });

// Вес — с одним знаком (разбор UX, шаг 24): «66,7 кг», а не «66,725 кг».
// Так же, как колонки веса в списке изделий и в окне изделия (digits
// [12,1] в metal_spec_views.xml) и карточка веса над таблицей — одно
// число на экране не расходится в точности.
const kg = (value) =>
    (value || 0).toLocaleString("ru-RU", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

// Ссылка на справочник приходит объектом {id, display_name}. Старый вид —
// пара [id, name] — встречается в ответах сервера, поэтому держим оба.
const relName = (value) => {
    if (!value) {
        return "—";
    }
    if (Array.isArray(value)) {
        return value[1] || "—";
    }
    return value.display_name || "—";
};

export class ProductLinesRenderer extends ListRenderer {
    static rowsTemplate = "pmk_calc.ProductRows";
    static components = { ...ListRenderer.components, Field };

    setup() {
        super.setup();
        // open — какие изделия раскрыты, editing — какая строка состава сейчас
        // в редакторе. Раскрытие держим сами: браузерный <details> внутри
        // таблицы Odoo не открывается, клик перехватывает список.
        this.pmk = useState({ open: {}, editing: null });
        // Изделия, раскрытые сами, потому что были единственными (разбор UX,
        // шаг 32). Обычный Set, НЕ реактивный: пишется во время отрисовки,
        // а запись в useState оттуда вызвала бы повторную отрисовку.
        this.pmkAutoOpen = new Set();
        // Строка изделия открыта на правку В СТРОКЕ (шаг 56), а не окном.
        // Обычное свойство, не реактивное: читается при отрисовке
        // (isInlineEditable), меняется через pmkSetInline — та сама
        // перерисовывает список, если запись уже «на правке» (например,
        // осталась такой после окна изделия) и сама отрисовку не вызовет.
        this.pmkInline = false;
        // «Как было» у цены и количества до правки строки — для Esc (шаг
        // 56): id записи → {поле: значение}. Ядро Esc у существующей записи
        // x2many ничего не откатывает (StaticList.leaveEditMode: discard
        // отбрасывает только новые записи), поэтому отмена — своя.
        this.pmkInlineBefore = new Map();
    }

    // ─── Правка цены и количества в строке изделия (шаг 56) ────────────────

    /**
     * Колонки, которые правятся в строке. Мост дописывает «Цену за шт»
     * (pmk_bridge, product_lines_cost.js): поле его, без моста калькулятор
     * работает как раньше. Вернуть прежнее поведение — вернуть [].
     */
    pmkInlineFieldNames() {
        return ["qty"];
    }

    pmkSetInline(value) {
        if (this.pmkInline !== value) {
            this.pmkInline = value;
            if (!value) {
                this.pmkInlineBefore.clear();
            }
            this.render();
        }
    }

    /**
     * Запомнить цену и количество строк, которые сейчас НЕ на правке: это
     * «как было» для Esc. Строка на правке не перезаписывается — её «как
     * было» снято до входа в правку. Зовётся перед каждым действием, которое
     * может открыть строку на правку: щелчок, Enter, Tab/Shift+Tab, Enter
     * на правке (переход на соседнюю строку).
     */
    pmkRememberBefore() {
        for (const record of this.props.list.records) {
            if (record.isInEdition) {
                continue;
            }
            const values = {};
            for (const name of this.pmkInlineFieldNames()) {
                if (name in record.data) {
                    values[name] = record.data[name];
                }
            }
            this.pmkInlineBefore.set(record.id, values);
        }
    }

    /**
     * Esc в строке на правке: вернуть цену и количество, какими они были до
     * правки строки, и закрыть правку. Сначала выходим из правки — ядро при
     * выходе забирает набранное из поля ввода (_askChanges); верни мы
     * значение раньше, поле записало бы набранное поверх. Пересчёт «Суммы» и
     * итогов — тот же onchange, что и при правке.
     */
    async pmkCancelInline(record) {
        const list = this.props.list;
        const before = this.pmkInlineBefore.get(record.id);
        if (list.editedRecord) {
            await list.leaveEditMode();
        }
        if (before) {
            const changes = {};
            for (const [name, value] of Object.entries(before)) {
                // Неверный ввод (не число) в запись не попал, но держит
                // строку на правке — значение пишем заново, ядро снимет
                // отметку об ошибке.
                if (record.data[name] !== value || record.isFieldInvalid(name)) {
                    changes[name] = value;
                }
            }
            if (Object.keys(changes).length) {
                await record.update(changes);
            }
        }
        if (list.editedRecord) {
            await list.leaveEditMode();
        }
        this.pmkSetInline(false);
        // Как ядро после Esc: курсор — на «Добавить изделие».
        const addButton = this.tableRef.el?.querySelector(".o_field_x2many_list_row_add a");
        if (addButton) {
            this.focus(addButton);
        }
    }

    pmkIsInline(column) {
        return !!(
            column &&
            column.type === "field" &&
            !this.props.readonly &&
            this.pmkInlineFieldNames().includes(column.name)
        );
    }

    /**
     * Список изделий по-прежнему «не редактируемый»: правится только
     * строка, открытая щелчком по цене или количеству. Строка за окном
     * изделия остаётся только для чтения — признак гасится до открытия окна.
     */
    isInlineEditable(_record) {
        return this.pmkInline;
    }

    /** В строке на правке поля ввода — только у цены и количества. */
    isCellReadonly(column, record) {
        if (this.pmkInline && record.isInEdition && !this.pmkIsInline(column)) {
            return true;
        }
        return super.isCellReadonly(column, record);
    }

    /** Намёк стилям: эти ячейки правятся щелчком (scss/spec_form.scss). */
    getCellClass(column, record) {
        const classNames = super.getCellClass(column, record);
        return this.pmkIsInline(column) ? `${classNames} pmk-inline-cell` : classNames;
    }

    getCellTitle(column, record) {
        if (this.pmkIsInline(column) && !record.isInEdition) {
            return "Щёлкните, чтобы изменить";
        }
        return super.getCellTitle(column, record);
    }

    /** Закрыть редакторы деталей под всеми изделиями (одна правка за раз). */
    async pmkCloseLineEditors() {
        if (!this.pmk.editing) {
            return;
        }
        for (const product of this.props.list.records) {
            for (const section of SECTIONS) {
                const lines = product.data[section.field];
                if (lines && lines.editedRecord) {
                    await lines.leaveEditMode();
                }
            }
        }
        this.pmk.editing = null;
    }

    /**
     * Выйти из правки строки изделия. false — не вышли: в строке ошибка
     * (ядро подсветит поле), действие не продолжаем.
     */
    async pmkLeaveProductEdit() {
        const list = this.props.list;
        if (list.editedRecord) {
            const left = await list.leaveEditMode();
            if (!left) {
                return false;
            }
        }
        this.pmkSetInline(false);
        return true;
    }

    /**
     * Щелчок по ячейке изделия: цена и количество — правка в строке,
     * остальное — окно изделия, как раньше.
     */
    async onCellClicked(record, column, ev, newWindow) {
        if (ev.target.special_click) {
            return;
        }
        if (this.pmkIsInline(column)) {
            await this.pmkCloseLineEditors();
            this.pmkRememberBefore();
            this.pmkSetInline(true);
            // Ядро само откроет строку на правку (enterEditMode) и поставит
            // курсор в эту ячейку; строка уже на правке — только курсор.
            return super.onCellClicked(record, column, ev, newWindow);
        }
        if (!(await this.pmkLeaveProductEdit())) {
            return;
        }
        if (!this.props.archInfo.noOpen) {
            this.props.openRecord(record, { newWindow });
        }
    }

    /** Enter на ячейке без правки: у цены и количества — правка в строке. */
    onCellKeydownReadOnlyMode(hotkey, cell, group, record) {
        if (hotkey === "enter" && record && cell) {
            const column = this.columns.find((c) => c.name === cell.getAttribute("name"));
            this.pmkRememberBefore();
            this.pmkSetInline(this.pmkIsInline(column));
        }
        return super.onCellKeydownReadOnlyMode(hotkey, cell, group, record);
    }

    /**
     * Enter в последней строке — закончить правку. Ядро здесь заводит новую
     * запись (add), а у этого списка это окно «нового изделия».
     */
    editNextRecord(record, group) {
        const list = this.props.list;
        if (this.pmkInline && list.records.indexOf(record) === list.records.length - 1) {
            list.leaveEditMode({ validate: true });
            return;
        }
        return super.editNextRecord(record, group);
    }

    /**
     * Tab за последней ячейкой последней строки — то же: без нового изделия.
     * Esc — отмена правки строки: цена и количество — как до правки.
     */
    onCellKeydownEditMode(hotkey, cell, group, record) {
        const list = this.props.list;
        if (this.pmkInline && record && hotkey === "escape") {
            this.pmkCancelInline(record);
            return true;
        }
        if (this.pmkInline) {
            // Tab, Enter переводят правку на соседнюю строку — её «как было»
            // снимаем до перехода.
            this.pmkRememberBefore();
        }
        if (
            this.pmkInline &&
            record &&
            hotkey === "tab" &&
            list.records.indexOf(record) === list.records.length - 1
        ) {
            if (this.applyCellKeydownEditModeStayOnRow(hotkey, cell, group, record)) {
                return true;
            }
            list.leaveEditMode();
            return true;
        }
        return super.onCellKeydownEditMode(hotkey, cell, group, record);
    }

    /** «Добавить изделие» — окно, как раньше; правку строки сперва закрываем. */
    async add(params) {
        if (!(await this.pmkLeaveProductEdit())) {
            return;
        }
        return super.add(params);
    }

    /**
     * Без пустых строк-распорок под «Добавить изделие» (разбор UX, шаг 32).
     * Штатный список дорисовывает пустые строки до четырёх: под составом
     * изделия они читались как два незаполненных изделия.
     */
    get getEmptyRowIds() {
        return [];
    }

    get compositionColspan() {
        return this.nbCols;
    }

    get allSections() {
        return SECTIONS;
    }

    /** Формат чисел для шаблона: разряды и запятая, как принято в документах. */
    num(value) {
        return num(value);
    }

    /** Вес для шаблона: один знак после запятой, как в колонках веса. */
    kg(value) {
        return kg(value);
    }

    /**
     * Раскрыт ли состав изделия.
     *
     * Выбор пользователя — главнее всего. Не выбирал: единственное изделие
     * раскрыто сразу (разбор UX, шаг 32) — щёлкать ради него лишнее, а
     * расчёт на одно изделие — частый случай (СМ-00024: «весь объём КМ1»).
     * Раскрывшееся само остаётся раскрытым и когда добавили второе
     * изделие: иначе состав, в котором работали, схлопнулся бы под рукой.
     */
    isOpen(record) {
        if (record.id in this.pmk.open) {
            return !!this.pmk.open[record.id];
        }
        if (this.props.list.records.length === 1) {
            this.pmkAutoOpen.add(record.id);
            return true;
        }
        return this.pmkAutoOpen.has(record.id);
    }

    async toggleComposition(record) {
        const open = !this.isOpen(record);
        if (!open && this.pmk.editing) {
            // Свернули с открытым редактором — закрываем его по-настоящему,
            // иначе строка осталась бы «в правке» без видимого редактора.
            for (const section of SECTIONS) {
                await record.data[section.field].leaveEditMode();
            }
            this.pmk.editing = null;
        }
        this.pmk.open[record.id] = open;
    }

    /** Непустые разделы изделия — с итогом по каждому. */
    compositionSections(record) {
        const out = [];
        for (const section of SECTIONS) {
            const list = record.data[section.field];
            const lines = (list && list.records) || [];
            if (!lines.length) {
                continue;
            }
            out.push({
                ...section,
                lines,
                weight: lines.reduce((sum, line) => sum + (line.data.weight_total || 0), 0),
            });
        }
        return out;
    }

    countLines(record) {
        let count = 0;
        for (const section of SECTIONS) {
            const list = record.data[section.field];
            count += ((list && list.records) || []).length;
        }
        return count;
    }

    /** «1 деталь», «3 детали», «7 деталей» — иначе счётчик читается коряво. */
    linesLabel(record) {
        const n = this.countLines(record);
        const last = n % 10;
        const teen = n % 100 >= 11 && n % 100 <= 14;
        if (!teen && last === 1) {
            return `${n} деталь`;
        }
        if (!teen && last >= 2 && last <= 4) {
            return `${n} детали`;
        }
        return `${n} деталей`;
    }

    /** Что показывать в «позиции» и «размерах» — зависит от вида детали. */
    describe(line) {
        const d = line.data;
        if (d.calc_mode === "linear") {
            return [relName(d.profile_id), `${num(d.length_mm)} мм`];
        }
        if (d.calc_mode === "sheet") {
            return [relName(d.sheet_id), `${num(d.a_mm)}×${num(d.b_mm)} мм`];
        }
        if (d.calc_mode === "fastener") {
            return [relName(d.fastener_id), ""];
        }
        // Толщину показываем всегда: именно она объясняет расход краски.
        const thickness = d.paint_thickness_um ? `, ${num(d.paint_thickness_um)} мкм` : "";
        const size = d.area_m2 ? `${num(d.area_m2)} м²${thickness}` : "площадь не задана";
        return [relName(d.paint_id), size];
    }

    detailOf(line) {
        return line.data.detail_name || "—";
    }

    qtyOf(line) {
        return line.data.qty || 0;
    }

    weightOf(line) {
        return kg(line.data.weight_total);
    }

    isEditing(line) {
        return this.pmk.editing === line.id;
    }

    /**
     * Контекст поля-справочника в редакторе строки (разбор UX, шаг 34).
     *
     * Типоразмеру — вид строки: его позиции первыми в подсказке
     * (name_search справочника, ключ pmk_prefer_type_id). Передаём сами:
     * поле здесь рисуется без разметки (<Field> без fieldInfo), и контекст
     * из вида до него не доходит (web, Field.fieldComponentProps).
     */
    refContext(line, input) {
        if (input.name !== "profile_id") {
            return {};
        }
        const type = line.data.type_id;
        return { pmk_prefer_type_id: (type && type.id) || false };
    }

    /**
     * Открыть строку в редакторе.
     *
     * Через enterEditMode, а не своим признаком: поле Odoo рисуется
     * редактируемым, только когда сама запись в режиме правки. Иначе редактор
     * открывался бы, но ввести в него ничего было нельзя.
     *
     * Переход заодно закрывает предыдущую строку, и пустая только что
     * добавленная при этом исчезает сама — как в обычных списках Odoo.
     */
    async editLine(record, section, line) {
        // Строка изделия на правке (шаг 56) — сперва закрываем: правка одна.
        if (!(await this.pmkLeaveProductEdit())) {
            return;
        }
        await record.data[section.field].enterEditMode(line);
        this.pmk.editing = line.id;
    }

    async stopEdit(record, section) {
        await record.data[section.field].leaveEditMode();
        this.pmk.editing = null;
    }

    /**
     * Новая строка состава — сразу в редакторе.
     *
     * Вид детали передаём контекстом: он обязателен, и без него строка
     * попала бы не в тот раздел. Запись создаётся в наборе документа, а не
     * в базе — сохранится вместе со спецификацией.
     *
     * Новая строка проката берёт вид проката предыдущей (разбор UX, шаг 34):
     * двутавры вводят подряд, и подсказка типоразмера показывает их первыми.
     * Предыдущая — последняя строка раздела, у которой вид есть. Так же
     * делает окно изделия (next_type_id изделия, metal_spec.py).
     */
    async addLine(record, section) {
        const list = record.data[section.field];
        if (!(await this.pmkLeaveProductEdit())) {
            return;
        }
        if (this.pmk.editing) {
            for (const other of SECTIONS) {
                await record.data[other.field].leaveEditMode();
            }
        }
        const context = { default_calc_mode: section.mode };
        if (section.mode === "linear") {
            const typed = list.records.filter((line) => line.data.type_id);
            const last = typed[typed.length - 1];
            if (last) {
                context.default_type_id = last.data.type_id.id;
            }
        }
        const line = await list.addNewRecord({
            position: "bottom",
            mode: "edit",
            context,
        });
        this.pmk.open[record.id] = true;
        this.pmk.editing = line.id;
    }

    async removeLine(record, section, line) {
        if (this.pmk.editing === line.id) {
            this.pmk.editing = null;
        }
        await record.data[section.field].delete(line);
    }
}

export class ProductLinesField extends X2ManyField {
    static components = { ...X2ManyField.components, ListRenderer: ProductLinesRenderer };
}

registry.category("fields").add("pmk_product_lines", {
    ...x2ManyField,
    component: ProductLinesField,
});
