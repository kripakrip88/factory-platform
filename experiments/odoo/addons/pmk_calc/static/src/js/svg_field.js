/**
 * Показ готового SVG в ячейке списка.
 *
 * Нужен для эскиза профиля: штатный виджет html в списках Odoo не рисует
 * разметку, а показывает её текстом, а виджет image ждёт растровую картинку
 * в base64 — эскиз же генерируется как SVG на сервере.
 *
 * Содержимое поля собирает наш же генератор (dobor_report.sketch_svg), из
 * снимка профиля, поэтому вставлять его как разметку безопасно: пользователь
 * туда ничего написать не может.
 */

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, useRef, onMounted, onPatched } from "@odoo/owl";

export class PmkSvgField extends Component {
    static template = "pmk_calc.SvgField";
    static props = { ...standardFieldProps };

    setup() {
        this.root = useRef("root");
        const paint = () => {
            if (this.root.el) {
                this.root.el.innerHTML = this.props.record.data[this.props.name] || "";
            }
        };
        onMounted(paint);
        onPatched(paint);
    }
}

registry.category("fields").add("pmk_svg", {
    component: PmkSvgField,
    supportedTypes: ["html", "text"],
});
