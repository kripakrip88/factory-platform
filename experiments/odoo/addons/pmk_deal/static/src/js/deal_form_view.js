/** @odoo-module **/
/**
 * Карточка сделки и лида — разбор UX, шаг 48 (06.10.2026).
 *
 * 1. БЕЗ «НОВОЕ». Решение Антона: «Новое» убрать в сделке и лиде (расчёт и
 *    так без него), «потом если что вернём». Создают сделки в воронке
 *    («Новое» и плюсики в колонках), лиды — в списке лидов и кнопкой «Лид» в
 *    почте; лид становится сделкой кнопкой «Конвертировать в сделку».
 *    Флаг canCreate контроллера убирает ровно «Новое» и его клавишу
 *    (form_controller.xml ядра). ⚠️ Не create="0" у формы — он унёс бы и
 *    «Дублировать» в ⚙ (web/views/utils.js: duplicate = create && duplicate).
 *    Не контекстом действия — ядро ставит create="0" ВСЕМ видам пункта меню
 *    (web/views/view.js), и «Новое» пропало бы в воронке и в списке.
 * 2. НОМЕР В СТРОКЕ ПУТИ. У сделки с номером — «СД-00001 от 27.09.2026»
 *    вместо темы письма (models/deal_number.py). display_name записи не
 *    трогаем: его берёт почта темой письма и поле «Сделка» расчёта.
 *    Пара на сервере — controllers/breadcrumbs.py: после перезагрузки
 *    страницы (F5) на расчёте, открытом из сделки, звено сделки ядро
 *    восстанавливает по display_name, и там подпись подменяется так же.
 *
 * ПОВЕРХ crm_form, А НЕ ОБЫЧНОЙ ФОРМЫ. У формы CRM своя модель (CrmFormModel:
 * синхронизация почты и телефона с карточкой клиента, сообщение при
 * «Выиграно»). Вид — копия crm_form с нашим контроллером; регистрацию
 * crm_form подтягивает побочный импорт ниже. Своих static components у
 * контроллера нет — он берёт их у FormController (тема pmk_theme добавляет
 * туда кнопки шапки, form_head.js).
 *
 * Вернуть штатную карточку — снять js_class в views/step48_deal_head.xml.
 */
import "@crm/views/crm_form/crm_form";
import { registry } from "@web/core/registry";
import { FormController } from "@web/views/form/form_controller";
import { dealCrumbLabel } from "@pmk_deal/js/deal_head_rules";

export class PmkCrmFormController extends FormController {
    setup() {
        super.setup();
        this.canCreate = false;
    }

    displayName() {
        return dealCrumbLabel(this.model.root.data) || super.displayName();
    }
}

const views = registry.category("views");

export const pmkCrmFormView = {
    ...views.get("crm_form"),
    Controller: PmkCrmFormController,
};

views.add("pmk_crm_form", pmkCrmFormView);
