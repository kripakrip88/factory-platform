/** @odoo-module **/
// Деньги в списках — без копеек.
//
// Антон, 29.09.2026: «копейки в списке можно убрать». В таблице сумма
// нужна, чтобы сравнить строки на глаз: «9 500 000 руб» читается сразу,
// «9 500 000,00 руб» обрезалось до «9 500 000,…» и забирало ширину у
// соседних колонок. Точная сумма — в самом документе: там копейки остались.
//
// ГДЕ: основные списки (Расчёты, Запросы КП, Заказы…). НЕ трогаем
// вложенные таблицы документов (строки расчёта, заказа — там считают до
// копейки) и формы.
//
// КАК — три места, через которые список показывает деньги:
//   1. итоги колонки и строк групп: ядро берёт число знаков из атрибута
//      колонки digits, если он есть (computeAggregates, formatGroupAggregate) —
//      проставляем его денежным колонкам;
//   2. ячейка без виджета — свой формат в getFormattedValue;
//   3. ячейка с виджетом monetary — число знаков в MonetaryField, только
//      когда поле показано в списке (env.config.viewType === "list": у
//      вложенной таблицы внутри формы там "form").
// Округление — по обычным правилам (…,50 вверх), как округлил бы бухгалтер.

import { patch } from "@web/core/utils/patch";
import { formatMonetary } from "@web/views/fields/formatters";
import { MonetaryField } from "@web/views/fields/monetary/monetary_field";
import { ListRenderer } from "@web/views/list/list_renderer";

const NO_CENTS = [69, 0];

patch(ListRenderer.prototype, {
    pmkIsMoneyColumn(column) {
        if (this.isX2Many || column.type !== "field") {
            return false;
        }
        const field = this.fields[column.name];
        return Boolean(field) && (field.type === "monetary" || column.widget === "monetary");
    },

    getActiveColumns() {
        return super.getActiveColumns(...arguments).map((column) =>
            this.pmkIsMoneyColumn(column) && !column.attrs?.digits
                ? { ...column, attrs: { ...column.attrs, digits: JSON.stringify(NO_CENTS) } }
                : column
        );
    },

    getFormattedValue(column, record) {
        const value = record.data[column.name];
        if (
            this.pmkIsMoneyColumn(column) &&
            this.fields[column.name].type === "monetary" &&
            typeof value === "number" &&
            column.options?.enable_formatting !== false
        ) {
            return formatMonetary(value, {
                ...formatMonetary.extractOptions(column),
                digits: NO_CENTS,
                data: record.data,
                field: this.fields[column.name],
            });
        }
        return super.getFormattedValue(...arguments);
    },
});

patch(MonetaryField.prototype, {
    get currencyDigits() {
        if (this.props.readonly && this.env.config?.viewType === "list") {
            return NO_CENTS;
        }
        return super.currencyDigits;
    },
});
