/** @odoo-module **/
/**
 * Число связанных документов в заголовке вкладки «Связи» (Антон 25.10.2026):
 * «Связи · 3». Вкладка — страница с name="pmk_flow", число — поле
 * pmk_flow_count документа (models/flow_count.py; в форму его кладёт вид,
 * невидимым). Нет поля в форме или связей нет — «Связи», как было.
 *
 * ⚠️ ПАТЧ ВНУТРЕННОСТЕЙ ЯДРА (FormCompiler.compileNotebook: слот страницы с
 * параметрами title / name) — перепроверять при обновлении Odoo.
 */
import { patch } from "@web/core/utils/patch";
import { FormCompiler } from "@web/views/form/form_compiler";

const COUNT = "__comp__.props.record.data.pmk_flow_count";

patch(FormCompiler.prototype, {
    compileNotebook(el, params) {
        const notebook = super.compileNotebook(...arguments);
        for (const slot of notebook.children) {
            if (slot.getAttribute("name") === "`pmk_flow`") {
                const title = slot.getAttribute("title");
                slot.setAttribute("title", `${title} + (${COUNT} ? \` · \` + ${COUNT} : \`\`)`);
            }
        }
        return notebook;
    },
});
