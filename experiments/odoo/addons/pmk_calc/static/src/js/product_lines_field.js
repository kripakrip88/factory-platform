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
// со справочником, ему нужна ширина; остальные числовые и узкие.
const SECTIONS = [
    {
        mode: "linear",
        field: "line_linear_ids",
        title: "Линейный прокат",
        short: "Прокат",
        accent: "#6bb6f5",
        inputs: [
            { name: "detail_name", label: "Деталь", wide: true },
            { name: "type_id", label: "Вид проката", wide: true },
            { name: "profile_id", label: "Типоразмер", wide: true },
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
            { name: "sheet_id", label: "Лист", wide: true },
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
            { name: "fastener_id", label: "Метиз", wide: true },
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
            { name: "paint_id", label: "Покрытие", wide: true },
            { name: "area_m2", label: "Площадь, м²" },
            { name: "paint_thickness_um", label: "Толщина, мкм" },
        ],
    },
];

const num = (value) => (value || 0).toLocaleString("ru-RU", { maximumFractionDigits: 3 });

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

    isOpen(record) {
        return !!this.pmk.open[record.id];
    }

    toggleComposition(record) {
        this.pmk.open[record.id] = !this.pmk.open[record.id];
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
        if (!n) {
            return "состав не заполнен";
        }
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
        return num(line.data.weight_total);
    }

    isEditing(line) {
        return this.pmk.editing === line.id;
    }

    editLine(line) {
        this.pmk.editing = line.id;
    }

    stopEdit() {
        this.pmk.editing = null;
    }

    /**
     * Новая строка состава — сразу в редакторе.
     *
     * Вид детали передаём контекстом: он обязателен, и без него строка
     * попала бы не в тот раздел. Запись создаётся в наборе документа, а не
     * в базе — сохранится вместе со спецификацией.
     */
    async addLine(record, section) {
        const list = record.data[section.field];
        const line = await list.addNewRecord({
            position: "bottom",
            mode: "edit",
            context: { default_calc_mode: section.mode },
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
