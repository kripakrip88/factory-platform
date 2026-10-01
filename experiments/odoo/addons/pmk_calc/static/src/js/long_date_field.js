/** @odoo-module **/
// Дата словами в заголовке расчёта: «СМ-00024 от 27 сентября 2026 г.»
// (приёмка 01.10.2026, R3).
//
// Штатное поле даты вне фокуса пишет коротко — «27 сент.» (год текущий
// опускается), хотя рядом много места. Здесь — месяц словом в родительном
// падеже и год полностью: формат Intl «DATE_FULL» для языка пользователя
// (Odoo ставит его luxon'у сам, localization_service.js). Всё остальное —
// штатное поле: по клику поле ввода «27.09.2026» и календарь, подсказка с
// числовой датой, пустое значение, только чтение.

import { registry } from "@web/core/registry";
import { DateTimeField, dateField } from "@web/views/fields/datetime/datetime_field";

export class PmkLongDateField extends DateTimeField {
    /**
     * @override
     * Числовой вид (подсказка, поле ввода) — штатный; словами — только
     * подпись вне фокуса и в режиме чтения.
     */
    getFormattedValue(valueIndex, numeric = this.props.numeric) {
        const value = this.values[valueIndex];
        if (!numeric && value && this.field.type === "date") {
            return value.toLocaleString(luxon.DateTime.DATE_FULL);
        }
        return super.getFormattedValue(valueIndex, numeric);
    }
}

registry.category("fields").add("pmk_long_date", {
    ...dateField,
    component: PmkLongDateField,
});
