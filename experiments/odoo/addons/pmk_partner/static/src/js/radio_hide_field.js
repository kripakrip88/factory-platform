/** @odoo-module **/
/**
 * Переключатель без лишних вариантов — виджет pmk_radio_hide (разбор UX,
 * шаг 29, 02.10.2026).
 *
 * ЗАЧЕМ. «Тип адреса» в окне контактного лица — штатный переключатель
 * (widget="radio") с вариантами Контакт · Счет · Доставка · Прочее ·
 * Директор · Бухгалтер (последние два — российская локализация). «Счет» и
 * «Прочее» на заводе не нужны (адресов с ними в базе 0 из 85 на 02.10.2026),
 * а сами варианты — значения поля модели: убрать их из поля значило бы
 * ломать данные и чужой код.
 *
 * КАК. Наследник штатного RadioField: тот же шаблон и то же поведение,
 * только геттер items отдаёт варианты без перечисленных в опции pmk_hide.
 * Текущее значение записи видно всегда (js/radio_hide_rules.js).
 * Подключение — в виде: widget="pmk_radio_hide"
 * options="{'horizontal': true, 'pmk_hide': ['invoice', 'other']}"
 * (views/step29_partner_hide.xml).
 *
 * ВЕРНУТЬ: в виде снова widget="radio" — или удалить вид
 * view_partner_form_address_type_step29. Таблица —
 * docs/disabled-features.md, раздел «шаг 29».
 */
import { registry } from "@web/core/registry";
import { RadioField, radioField } from "@web/views/fields/radio/radio_field";
import { visibleItems } from "@pmk_partner/js/radio_hide_rules";

export class PmkRadioHideField extends RadioField {
    static props = {
        ...RadioField.props,
        hiddenValues: { type: Array, optional: true },
    };

    get items() {
        return visibleItems(super.items, this.props.hiddenValues, this.value);
    }
}

export const pmkRadioHideField = {
    ...radioField,
    component: PmkRadioHideField,
    extractProps: (fieldInfo, dynamicInfo) => ({
        ...radioField.extractProps(fieldInfo, dynamicInfo),
        hiddenValues: fieldInfo.options.pmk_hide || [],
    }),
};

registry.category("fields").add("pmk_radio_hide", pmkRadioHideField);
