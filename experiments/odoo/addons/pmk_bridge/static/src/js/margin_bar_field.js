/** @odoo-module **/
// Полоска маржи в списке «Расчётов».
//
// «Оживить таблицы», приём 4 (Антон, 29.09.2026: «делай всё из
// предложения»). Рядом с суммой — короткая полоска: сколько маржи над
// металлом, и хорошая ли она. Число остаётся главным, полоска — чтобы
// глаз цеплялся за плохие строки без чтения.
//
// ⚠️ МАРЖА ЗДЕСЬ — НАД МЕТАЛЛОМ, а не прибыль: работа и переделы ещё не
// вычтены (подсказка поля margin_pct). Отсюда высокие пороги.
//
// ⚠️ ТРИ СЛУЧАЯ, КОГДА ЧИСЛО ВРЁТ, — полоска их не скрывает:
//   • цены клиенту нет вообще: margin_pct = 0, margin_amount = −металл.
//     Это не «плохая маржа», её ещё не назначили — прочерк, без полоски;
//   • расчёт неполный (есть позиции без цены закупки): металл занижен,
//     маржа ЗАВЫШЕНА. Полоска КРАСНАЯ, число с «≤» — это верхняя граница.
//     Антон, 29.09.2026: «если неполный расчёт — поставь красный, пусть
//     даёт сигнал» (сначала была серая штриховка — «не знаем точно»).
//     Пример: СМ-00024 показывал 63,9 %, а без цены был рифлёный лист —
//     30 % веса расчёта;
//   • обычный случай — цвет по порогам ниже.

import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { formatFloat } from "@web/views/fields/formatters";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

// ЕДИНСТВЕННОЕ место с порогами. ПРЕДЛОЖЕНИЕ от 29.09.2026, ждёт решения
// Антона (вопрос 10 разбора — «пороги сигналов»):
//   good — от 40 % и выше, low — от 20 до 40 %, ниже 20 % — bad;
//   scaleMax — сколько процентов соответствует полной полоске.
export const MARGIN_BAR = { good: 40, low: 20, scaleMax: 60 };

export class MarginBarField extends Component {
    static template = "pmk_bridge.MarginBarField";
    static props = {
        ...standardFieldProps,
        incompleteField: { type: String, optional: true },
        baseField: { type: String, optional: true },
        missingField: { type: String, optional: true },
    };

    get data() {
        return this.props.record.data;
    }

    get value() {
        return this.data[this.props.name] || 0;
    }

    get state() {
        if (this.props.baseField && !(this.data[this.props.baseField] > 0)) {
            return "none";
        }
        if (this.props.incompleteField && this.data[this.props.incompleteField]) {
            return "incomplete";
        }
        if (this.value >= MARGIN_BAR.good) {
            return "good";
        }
        return this.value >= MARGIN_BAR.low ? "low" : "bad";
    }

    get width() {
        return Math.max(0, Math.min(100, (this.value / MARGIN_BAR.scaleMax) * 100));
    }

    get label() {
        if (this.state === "none") {
            return "—";
        }
        const text = `${formatFloat(this.value, { digits: [6, 1] })} %`;
        return this.state === "incomplete" ? `≤ ${text}` : text;
    }

    get title() {
        if (this.state === "none") {
            return _t("Цена клиенту не назначена — маржи ещё нет");
        }
        if (this.state === "incomplete") {
            const missing = this.props.missingField ? this.data[this.props.missingField] : "";
            return _t(
                "Без цены закупки позиций: %s. Металл посчитан не весь — маржа завышена, это верхняя граница.",
                missing
            );
        }
        return _t("Маржа над металлом: работа и переделы ещё не вычтены");
    }
}

registry.category("fields").add("pmk_margin_bar", {
    component: MarginBarField,
    displayName: _t("Полоска маржи"),
    supportedTypes: ["float"],
    // Ширина колонки: полоска 48 px + «≤ 63,9 %». Без неё Odoo давал колонке
    // ширину числа по умолчанию, и подпись обрезалась до «≤ 6».
    listViewWidth: [130, 160],
    extractProps: ({ options }) => ({
        incompleteField: options.incomplete_field,
        baseField: options.base_field,
        missingField: options.missing_field,
    }),
});
