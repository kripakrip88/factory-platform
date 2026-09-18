/**
 * Список изделий с составом, раскрывающимся под строкой.
 *
 * Odoo не умеет вкладывать таблицу в таблицу, а состав хотелось видеть там же,
 * где изделия. Поэтому вклиниваемся в разметку строк списка: после строки
 * каждого изделия добавляем свою, со составом.
 *
 * ПОЧЕМУ СОСТАВ ГРУЗИТСЯ ОТДЕЛЬНЫМ ЗАПРОСОМ. Сперва я читал вложенные строки
 * из памяти формы — и они приходили ПУСТЫМИ ЗАГЛУШКАМИ: поля есть, значения
 * нулевые (calc_mode: false, qty: 0). Odoo знает о записях, но не читает их
 * содержимое, если колонка скрыта. Счётчик при этом верен — записи посчитаны,
 * а состав пуст. Поэтому содержимое запрашиваем сами, при первом раскрытии.
 *
 * ПОЧЕМУ РИСУЕМ В DOM, А НЕ ШАБЛОНОМ. Ни реактивное состояние, ни явный
 * render() внутри чужого рендерера до экрана не доходили — кнопка нажималась,
 * а состав не появлялся. Три попытки на это ушло, поэтому здесь ничего не
 * ждём от перерисовки: вставляем разметку по месту.
 *
 * Ввод не тронут: добавление, удаление, перетаскивание и открытие изделия
 * работают штатно, мы только дорисовываем строку.
 */

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ListRenderer } from "@web/views/list/list_renderer";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";

const SECTIONS = [
    { mode: "linear", title: "Линейный прокат" },
    { mode: "sheet", title: "Листовой прокат" },
    { mode: "fastener", title: "Метизы" },
    { mode: "paint", title: "Лакокрасочное покрытие" },
];

// Состав правят во вкладках диалога, то есть через ОТФИЛЬТРОВАННЫЕ наборы.
// Общий line_ids при этом не обновляется — для Odoo это разные наборы данных,
// и счётчик показывал бы прежнее число до сохранения документа.
const LINE_FIELDS = ["line_linear_ids", "line_sheet_ids", "line_fastener_ids", "line_paint_ids"];

const READ_FIELDS = [
    "calc_mode", "detail_name", "profile_id", "sheet_id", "fastener_id", "paint_id",
    "length_mm", "a_mm", "b_mm", "area_m2", "paint_thickness_um", "qty", "weight_total",
];

const esc = (value) =>
    String(value === undefined || value === null || value === false ? "—" : value)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

const num = (value) =>
    (value || 0).toLocaleString("ru-RU", { maximumFractionDigits: 3 });

export class ProductLinesRenderer extends ListRenderer {
    static rowsTemplate = "pmk_calc.ProductRows";

    setup() {
        super.setup();
        this.orm = useService("orm");
    }

    get compositionColspan() {
        return this.nbCols;
    }

    /** Строки изделия из всех четырёх наборов — здесь нужны только их id. */
    lineIds(record) {
        const ids = [];
        for (const field of LINE_FIELDS) {
            const list = record.data[field];
            for (const line of (list && list.records) || []) {
                if (typeof line.resId === "number") {
                    ids.push(line.resId);
                }
            }
        }
        return ids;
    }

    countLines(record) {
        let count = 0;
        for (const field of LINE_FIELDS) {
            const list = record.data[field];
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
        const rel = (v) => (Array.isArray(v) ? v[1] : v) || "—";
        if (line.calc_mode === "linear") {
            return [rel(line.profile_id), `${num(line.length_mm)} мм`];
        }
        if (line.calc_mode === "sheet") {
            return [rel(line.sheet_id), `${num(line.a_mm)}×${num(line.b_mm)} мм`];
        }
        if (line.calc_mode === "fastener") {
            return [rel(line.fastener_id), ""];
        }
        // Толщину показываем всегда: именно она объясняет расход краски.
        const thickness = line.paint_thickness_um ? `, ${num(line.paint_thickness_um)} мкм` : "";
        const size = line.area_m2 ? `${num(line.area_m2)} м²${thickness}` : "площадь не задана";
        return [rel(line.paint_id), size];
    }

    buildHtml(lines) {
        const blocks = [];
        for (const section of SECTIONS) {
            const rows = lines.filter((l) => l.calc_mode === section.mode);
            if (!rows.length) {
                continue;
            }
            const body = rows.map((line) => {
                const [what, size] = this.describe(line);
                return `<tr><td>${esc(line.detail_name || "—")}</td><td>${esc(what)}</td>` +
                       `<td>${esc(size)}</td><td class="pmk-num">${line.qty || 0}</td>` +
                       `<td class="pmk-num">${num(line.weight_total)}</td></tr>`;
            }).join("");
            blocks.push(
                `<div class="pmk-prow__section"><h6>${esc(section.title)}</h6>` +
                `<table class="pmk-prow__table"><thead><tr>` +
                `<th>Деталь</th><th>Позиция</th><th>Размеры</th>` +
                `<th class="pmk-num">Кол-во</th><th class="pmk-num">Вес, кг</th>` +
                `</tr></thead><tbody>${body}</tbody></table></div>`
            );
        }
        return blocks.join("") || '<div class="pmk-prow__empty">Состав не заполнен</div>';
    }

    async toggleComposition(ev, record) {
        const row = ev.target.closest("tr");
        if (!row) {
            return;
        }
        const opened = row.classList.toggle("pmk-prow--open");
        const icon = row.querySelector(".pmk-prow__toggle .fa");
        if (icon) {
            icon.classList.toggle("fa-angle-right", !opened);
            icon.classList.toggle("fa-angle-down", opened);
        }
        const button = row.querySelector(".pmk-prow__toggle");
        if (button) {
            button.setAttribute("aria-expanded", opened ? "true" : "false");
        }
        if (!opened) {
            return;
        }

        const wrap = row.querySelector(".pmk-prow__wrap");
        if (!wrap) {
            return;
        }
        // Перечитываем при каждом раскрытии: состав могли поправить, пока
        // строка была свёрнута, и показать устаревшее хуже, чем подождать.
        wrap.innerHTML = '<div class="pmk-prow__empty">Загружаем состав…</div>';
        const ids = this.lineIds(record);
        if (!ids.length) {
            wrap.innerHTML = '<div class="pmk-prow__empty">Состав не заполнен</div>';
            return;
        }
        try {
            const lines = await this.orm.read("pmk.metal.spec.line", ids, READ_FIELDS);
            wrap.innerHTML = this.buildHtml(lines);
        } catch {
            wrap.innerHTML = '<div class="pmk-prow__empty">Не удалось загрузить состав</div>';
        }
    }
}

export class ProductLinesField extends X2ManyField {
    static components = { ...X2ManyField.components, ListRenderer: ProductLinesRenderer };
}

registry.category("fields").add("pmk_product_lines", {
    ...x2ManyField,
    component: ProductLinesField,
});
