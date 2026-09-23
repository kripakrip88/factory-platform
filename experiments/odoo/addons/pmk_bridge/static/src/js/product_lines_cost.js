/** @odoo-module **/

/**
 * Стоимость закупки в составе изделия.
 *
 * Шаблон состава расширен отдельным файлом (product_lines_cost.xml), и ему
 * нужен метод costOf. Добавляем его патчем, а не наследником класса: виджет
 * зарегистрирован в реестре полей под именем pmk_product_lines, и подмена
 * класса означала бы вторую регистрацию — кто победит, зависело бы от порядка
 * загрузки файлов.
 */

import { patch } from "@web/core/utils/patch";
import { ProductLinesRenderer } from "@pmk_calc/js/product_lines_field";

patch(ProductLinesRenderer.prototype, {
    /**
     * Сумма закупки строки: столько стоит металл, который придётся купить
     * под эту деталь во всём изделии.
     *
     * Прочерк вместо нуля, когда цены нет. Ноль в денежной колонке читается
     * как «бесплатно» и проходит мимо глаз — именно так КП уходит клиенту с
     * неоплаченным металлом. Прочерк заметен.
     */
    costOf(line) {
        const state = line.data.price_state;
        if (state && state !== "ok") {
            return "—";
        }
        const value = line.data.cost_fact_total || 0;
        if (!value) {
            return "—";
        }
        // Разряды пробелами и запятая в дробной части — как в остальных
        // числах документа.
        return value.toLocaleString("ru-RU", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    },
});
