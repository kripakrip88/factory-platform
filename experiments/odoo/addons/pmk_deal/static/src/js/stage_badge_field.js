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

    setup() {
        super.setup();
        // Шаг 31: «N дн», а не штатное «N д.» в правке строки — там рисует
        // шаблон ядра mail.Many2OneFieldRotting, и берёт он этот dayCount
        // (плашку вне правки рисует наш шаблон). Одно слово с кнопкой стадии
        // в сделке (pmk_theme/statusbar_compact.js) и карточкой воронки.
        // Считается один раз при создании поля — как и у ядра.
        this.dayCount = `${this.props.record.data.rotting_days} дн`;
    }
}

// Ширина колонки (разбор UX, шаг 24, 01.10.2026). Ядро даёт колонке
// many2one не меньше 80 px (FIELD_WIDTHS в column_width_hook.js), ячейка
// режет содержимое троеточием, и «КП отправлено · 8 дн» обрезалось до
// «КП отпр…» — ни стадии, ни сигнала «зависла». 170 px — самая длинная
// плашка «КП отправлено» и «12 дн» рядом (плашка 0,75 em: около 97 и 49 px,
// между ними 8 px) плюс отступы ячейки 8 + 8 px. Это минимум: при свободном
// месте колонка шире, ядро раздаёт его само. Прецедент — полоска маржи
// pmk_bridge (margin_bar_field.js, listViewWidth [150, 190]).
registry.category("fields").add("list.pmk_stage_badge", {
    ...buildM2OFieldDescription(PmkStageBadgeField),
    listViewWidth: [170],
});
