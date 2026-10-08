/** @odoo-module **/
/**
 * Окно «Колонки» (разбор UX, шаг 55, 08.10.2026) — по макету документа
 * «Разбор удобства», раздел «Колонки в таблицах», и по образцу штатного окна
 * «Экспорт» (тот же useSortable ядра).
 *
 * Список колонок в их порядке: ⋮⋮ — перетащить, галочка — показать или
 * спрятать, ↑ ↓ — переставить с клавиатуры и на телефоне (там перетаскивания
 * нет, как у «Экспорта»). Колонку, которую прятать нельзя, видно серым
 * словом: «всегда видна» (название записи), «обязательная» (в таблице, где
 * строки правят прямо в списке). Ширину задают в самой таблице — потянуть
 * край заголовка; здесь её можно только снять (×).
 *
 * Правки доходят до списка по «Готово» (единственная залитая кнопка окна).
 * «Отмена» и крестик ничего не меняют. Администратору — «Сделать так у
 * всех» (контурная) и «Убрать общую».
 *
 * Правой половины макета («все поля документа с поиском») здесь нет: в окне
 * только колонки, которые уже есть в виде списка. Поле, которого в виде нет,
 * добавляется правкой вида — граница шага 55 (docs/disabled-features.md).
 */
import { Component, useRef, useState } from "@odoo/owl";
import { CheckBox } from "@web/core/checkbox/checkbox";
import { Dialog } from "@web/core/dialog/dialog";
import { useSortable } from "@web/core/utils/sortable_owl";
import { canHide, sameRows } from "@pmk_list_prefs/js/list_prefs_rules";

export const LOCK_WORDS = {
    pinned: "всегда видна",
    required: "обязательная",
};

export const SOURCE_WORDS = {
    own: "ваша настройка",
    common: "общая — для всех",
    // Одно понятие — одно слово: «штатная», как на кнопке «Вернуть штатную».
    view: "штатная",
};

export class ColumnsDialog extends Component {
    static template = "pmk_list_prefs.ColumnsDialog";
    static components = { CheckBox, Dialog };
    static props = {
        title: { type: String, optional: true },
        rows: Array,
        source: String,
        resetLabel: { type: String, optional: true },
        lastColumnWarning: { type: String, optional: true },
        isAdmin: Boolean,
        hasCommon: Boolean,
        isSmall: Boolean,
        onApply: Function,
        onSaveCommon: Function,
        onResetOwn: Function,
        onResetCommon: Function,
        close: Function,
    };

    setup() {
        this.lockWords = LOCK_WORDS;
        this.sourceWords = SOURCE_WORDS;
        this.state = useState({ rows: this.props.rows.map((row) => ({ ...row })) });
        this.listRef = useRef("list");
        useSortable({
            ref: this.listRef,
            elements: ".o_pmk_cols_row",
            handle: ".o_pmk_cols_handle",
            enable: () => !this.props.isSmall,
            cursor: "grabbing",
            followingElementClasses: ["o_pmk_cols_row_dragged"],
            onDrop: ({ element, next }) => {
                this.moveBefore(element.dataset.key, next ? next.dataset.key : null);
            },
        });
    }

    moveBefore(key, beforeKey) {
        const rows = this.state.rows;
        const from = rows.findIndex((row) => row.key === key);
        if (from === -1) {
            return;
        }
        const [row] = rows.splice(from, 1);
        const to = beforeKey ? rows.findIndex((r) => r.key === beforeKey) : -1;
        rows.splice(to === -1 ? rows.length : to, 0, row);
    }

    move(index, delta) {
        const rows = this.state.rows;
        const to = index + delta;
        if (to < 0 || to >= rows.length) {
            return;
        }
        const [row] = rows.splice(index, 1);
        rows.splice(to, 0, row);
    }

    /** Последнюю видимую колонку спрятать нельзя: таблица опустела бы. */
    isLast(row) {
        return row.visible && !canHide(this.state.rows, row.key);
    }

    toggle(row) {
        if (row.lock || this.isLast(row)) {
            return;
        }
        row.visible = !row.visible;
    }

    clearWidth(row) {
        row.width = null;
    }

    get visibleCount() {
        return this.state.rows.filter((row) => row.visible).length;
    }

    snapshot() {
        return this.state.rows.map((row) => ({ ...row }));
    }

    onDone() {
        const rows = this.snapshot();
        if (!sameRows(rows, this.props.rows)) {
            this.props.onApply(rows);
        }
        this.props.close();
    }

    async onSaveCommon() {
        await this.props.onSaveCommon(this.snapshot());
        this.props.close();
    }

    async onResetOwn() {
        await this.props.onResetOwn();
        this.props.close();
    }

    async onResetCommon() {
        await this.props.onResetCommon();
        this.props.close();
    }
}
