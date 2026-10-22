/** @odoo-module **/
/**
 * №312 (Антон 23.10.2026: «зачем в доборах стрелочки? это же неудобно»): ручка ⠿ перетаскивания
 * для списков ТОЛЬКО ДЛЯ ЧТЕНИЯ — вкладки «Доборные элементы» и «Вентзонты» расчёта (строки
 * калькуляторов, собранные в расчёт). Штатная ручка Odoo там не сохранит порядок: список не правится.
 *
 * Ячейка-ручка вешает перетаскивание на свою строку таблицы. Бросили на другую строку — сервер
 * переставляет (action_pmk_move_to у строки калькулятора, models/spec_move.py), форма перечитывается.
 * Виджет поля: <field name="sequence" widget="pmk_row_grip"/>.
 */
import { Component, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

let dragged = null; // {model, id}

export class PmkRowGrip extends Component {
    static template = "pmk_calc.RowGrip";
    static props = { ...standardFieldProps };

    setup() {
        this.root = useRef("root");
        this.armed = false;
        const on = (tr, type, fn) => {
            tr.addEventListener(type, fn);
            this.cleanup.push(() => tr.removeEventListener(type, fn));
        };
        this.cleanup = [];
        onMounted(() => {
            const tr = this.root.el?.closest("tr");
            if (!tr) {
                return;
            }
            this.tr = tr;
            tr.setAttribute("draggable", "true");
            on(tr, "dragstart", (ev) => this.onDragStart(ev));
            on(tr, "dragend", () => this.onDragEnd());
            on(tr, "dragover", (ev) => this.onDragOver(ev));
            on(tr, "dragleave", () => tr.classList.remove("o_pmk_grip_over"));
            on(tr, "drop", (ev) => this.onDrop(ev));
        });
        onWillUnmount(() => this.cleanup.forEach((fn) => fn()));
    }

    get record() {
        return this.props.record;
    }

    arm() {
        this.armed = true;
    }

    onDragStart(ev) {
        if (!this.armed) {
            ev.preventDefault();
            return;
        }
        dragged = { model: this.record.resModel, id: this.record.resId };
        ev.dataTransfer.effectAllowed = "move";
        ev.dataTransfer.setData("text/plain", String(this.record.resId));
        this.tr.classList.add("o_pmk_grip_dragging");
    }

    onDragEnd() {
        this.armed = false;
        dragged = null;
        this.tr?.classList.remove("o_pmk_grip_dragging");
        document.querySelectorAll(".o_pmk_grip_over").forEach((el) => el.classList.remove("o_pmk_grip_over"));
    }

    onDragOver(ev) {
        if (dragged && dragged.model === this.record.resModel && dragged.id !== this.record.resId) {
            ev.preventDefault();
            this.tr.classList.add("o_pmk_grip_over");
        }
    }

    async onDrop(ev) {
        ev.preventDefault();
        this.tr.classList.remove("o_pmk_grip_over");
        const from = dragged;
        dragged = null;
        if (!from || from.model !== this.record.resModel || from.id === this.record.resId) {
            return;
        }
        // Ниже строки, если тащили сверху вниз (как в таблицах расчёта).
        const rows = [...this.tr.parentElement.querySelectorAll("tr")];
        const fromRow = rows.find((r) => r.classList.contains("o_pmk_grip_dragging"));
        const below = fromRow ? rows.indexOf(fromRow) < rows.indexOf(this.tr) : false;
        const root = this.record.model.root;
        if (await root.isDirty()) {
            await root.save();
        }
        await this.env.services.orm.call(from.model, "action_pmk_move_to", [[from.id], this.record.resId, below]);
        await root.load();
    }
}

registry.category("fields").add("pmk_row_grip", { component: PmkRowGrip, supportedTypes: ["integer"] });
