/** @odoo-module **/
// Форма расчёта металлопроката без кнопки «Новое» (приёмка 01.10.2026, R6).
//
// Владелец: «Есть смысл от кнопки НОВОЕ? если понадобится новый расчёт, то
// создавать его будут из вкладки Калькулятор металлопроката». В списке
// расчётов «Новое» остаётся — у списка свой контроллер.
//
// ⚠️ ПОЧЕМУ НЕ create="0" У ФОРМЫ. В Odoo 19 «Дублировать» в ⚙ доступно,
// только когда разрешено создание (web/views/utils.js, getActiveActions:
// duplicate = create && duplicate), — create="0" унёс бы и «Дублировать», а
// его владелец оставил. Флаг canCreate контроллера формы управляет ровно
// двумя кнопками «Новое» (form_controller.xml) и их горячей клавишей; ни
// «Дублировать», ни открытие формы нового расчёта без записи (кнопка «Расчёт
// и КП» на сделке, pmk_deal: action_open_specs) от него не зависят.
//
// Вернуть «Новое» — убрать js_class="pmk_spec_form" в views/metal_spec_views.xml.

import { registry } from "@web/core/registry";
import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";

export class PmkSpecFormController extends FormController {
    setup() {
        super.setup();
        this.canCreate = false;
    }
}

export const pmkSpecFormView = {
    ...formView,
    Controller: PmkSpecFormController,
};

registry.category("views").add("pmk_spec_form", pmkSpecFormView);
