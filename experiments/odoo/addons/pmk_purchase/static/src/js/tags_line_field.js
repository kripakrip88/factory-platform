/** @odoo-module **/
// Метки в одну строку: первая — целиком, остальные — «+N», а их названия —
// в подсказке при наведении на «+N» (разбор UX, шаг 26, 01.10.2026).
//
// Где: «Что возит» в «Поставщиках прайсов» и «Закупки → Поставщики»
// (views/res_partner_views.xml, view_price_supplier_list). Штатный виджет
// many2many_tags выкладывал все метки столбиком: у поставщика с шестью
// группами строка была высотой 124 px, и на экран влезали три поставщика.
//
// Счётчик «+N» и подсказку рисует само ядро (web/core/tags_list, проп
// visibleItemsLimit), здесь его только включаем: при двух метках видны обе,
// при трёх и больше — первая и «+N». Чтобы две длинные метки не переносились
// на вторую строку, они сжимаются с многоточием — стиль
// scss/price_supplier_list.scss (полное название — в подсказке метки).
//
// Вернуть штатное: в виде widget="many2many_tags" вместо pmk_tags_line.

import { registry } from "@web/core/registry";
import {
    Many2ManyTagsField,
    many2ManyTagsField,
} from "@web/views/fields/many2many_tags/many2many_tags_field";

export class PmkTagsLineField extends Many2ManyTagsField {
    static template = "pmk_purchase.TagsLineField";
}

export const pmkTagsLineField = {
    ...many2ManyTagsField,
    component: PmkTagsLineField,
};

registry.category("fields").add("pmk_tags_line", pmkTagsLineField);
