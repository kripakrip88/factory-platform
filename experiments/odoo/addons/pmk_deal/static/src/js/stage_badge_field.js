/** @odoo-module **/
// Стадия в списке сделок: плашкой в цвете стадии, а при правке строки —
// обычный выбор стадии.
//
// «Оживить таблицы» (29.09.2026). Штатный виджет badge рисует плашку, но
// только для чтения: стадию нельзя было бы сменить прямо в списке, в том
// числе сразу у нескольких сделок (у списка multi_edit). Поэтому свой
// виджет: пока строка не в правке — плашка с цветом стадии (цвет из
// «Настройки CRM → Этапы», поле stage_id_color в списке уже есть); в правке —
// штатный редактор ядра (badge_rotting), со всем его поведением.
// Бледный вид плашки — тема (forms_nexus.scss, «Плашки статусов»).

import { Many2OneFieldRotting } from "@mail/js/rotting_mixin/rotting_widget";
import { registry } from "@web/core/registry";
import { buildM2OFieldDescription } from "@web/views/fields/many2one/many2one_field";

export class PmkStageBadgeField extends Many2OneFieldRotting {
    static template = "pmk_deal.StageBadgeField";
}

registry.category("fields").add("list.pmk_stage_badge", {
    ...buildM2OFieldDescription(PmkStageBadgeField),
});
