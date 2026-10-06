/** @odoo-module **/
/**
 * Подпись строки пути у сделки — разбор UX, шаг 48 (06.10.2026).
 *
 * Чистая функция без импортов Odoo: её гоняет node
 * (static/tests/deal_head_step48.test.mjs). Использует deal_form_view.js.
 *
 * У сделки с номером — «СД-00001 от 27.09.2026» (поле pmk_number_label,
 * models/deal_number.py). У лида, новой несохранённой сделки и сделки без
 * номера — пусто: тогда подпись штатная (тема письма или «Новое»).
 */
export function dealCrumbLabel(data) {
    if (!data || data.type !== "opportunity") {
        return "";
    }
    const label = data.pmk_number_label;
    return typeof label === "string" ? label.trim() : "";
}
