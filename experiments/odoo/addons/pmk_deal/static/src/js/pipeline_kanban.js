/** @odoo-module **/
// Воронка сделок: колонки этапов раздельно (приёмка 01.10.2026, R10,
// вариант Б по макету). Владелец: «Можем визуально разделить этапы? сейчас
// слито, хотя цвет этапов в системе можно назначать. Под названием этапа есть
// непонятная полоска».
//
//   • над названием этапа — полоса 3 px цвета этапа («Настройки CRM →
//     Этапы», поле «Цвет»; штатная палитра Odoo, цвет 0 — без полосы);
//   • полоски задач под названием (зелёный / жёлтый / красный по задачам —
//     задачи на заводе не ведутся) — нет;
//   • сумма в шапке колонки — как на карточке сделки: «9,5 млн ₽», ноль —
//     прочерк (было штатное «9 500к руб»);
//   • число сделок «(N)» — всегда: без полоски задач ядро его прятало.
// Фон колонок и зазор — scss/pipeline_kanban.scss. Значок зависших сделок в
// шапке и «N дн» на карточках — штатные (rotting), не тронуты.
//
// КАК УСТРОЕНО. Канбан воронки — js_class="crm_kanban": рендерер
// CrmKanbanRenderer → шапка колонки CrmKanbanHeader (шаблон
// mail.RottingKanbanHeader) → ColumnProgress (crm.ColumnProgress: полоска
// задач, значок зависших, сумма AnimatedNumber). Подменяем шапку у рендерера
// воронки (patch его components — так делает и ядро, sms/phone_field.js);
// прогнозный канбан (ForecastKanbanRenderer) скопировал components при
// объявлении и остаётся штатным. Узел <progressbar> в виде остаётся: только
// с ним в шапке есть сумма.
//
// ⚠️ ТОЛЬКО ВОРОНКА. Тот же рендерер (js_class="crm_kanban") рисует и канбан
// лидов (crm.view_crm_lead_kanban). У него полоска задач БЕЗ суммы, и число
// справа в шапке — КОЛИЧЕСТВО лидов (ядро, progress_bar_hook.js
// getAggregateValue: нет sum_field — значит, счёт): наш денежный формат
// написал бы «5 ₽» вместо «5». Поэтому всё наше включается признаком
// env.pmkPipeline — класс o_opportunity_kanban в разметке вида воронки
// (crm.crm_case_kanban_view_leads); у канбана лидов его нет, там шапка
// штатная: полоска задач, счёт, без полосы этапа.

import { onWillStart, toRaw, useSubEnv } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { AnimatedNumber } from "@web/views/view_components/animated_number";
import { CrmColumnProgress } from "@crm/views/crm_kanban/crm_column_progress";
import { CrmKanbanRenderer } from "@crm/views/crm_kanban/crm_kanban_renderer";
import { rubShort } from "./money_short";

/** Вид — воронка сделок, а не другой канбан с js_class="crm_kanban". */
export function isPipelineArch(archInfo) {
    return (archInfo?.className || "").split(/\s+/).includes("o_opportunity_kanban");
}

/** Сумма колонки воронки — «9,5 млн ₽» вместо «9 500к руб». Вне воронки —
 *  штатно: там это может быть счёт записей, а не деньги. */
export class PmkColumnSum extends AnimatedNumber {
    format(value) {
        return this.env.pmkPipeline ? rubShort(value) : super.format(value);
    }
}

export class PmkColumnProgress extends CrmColumnProgress {
    static template = "pmk_deal.ColumnProgress";
    static components = { ...CrmColumnProgress.components, AnimatedNumber: PmkColumnSum };
}

// Шапка колонки ядра CRM не экспортирована — берём её у рендерера.
const CrmKanbanHeader = CrmKanbanRenderer.components.KanbanHeader;

// Цвета этапов — одним запросом на открытый канбан, а не на каждую колонку:
// ключ — модель вида (у каждого открытия своя). Сменили цвет в настройках —
// новый виден при следующем открытии воронки.
//
// ⚠️ ЗАПРОС — ЧЕРЕЗ env.services.orm, А НЕ this.orm ШАПКИ. this.orm — служба,
// «защищённая» компонентом (useService): если компонент уничтожен до ответа,
// его промис НЕ разрешается никогда — так ядро бережёт мёртвые компоненты от
// обновления. Промис здесь общий для всех шапок. Ядро может пересоздать
// колонки до показа (на живой базе так и было), шапка, начавшая запрос,
// погибала, а остальные ждали её ответ вечно: воронка не появлялась совсем,
// без единой ошибки в консоли (живой стенд 01.10.2026, v1.17.0; на копии с
// другими данными не проявлялось). Незащищённая служба отвечает всегда.
const stageColorsByModel = new WeakMap();
const noModel = {};

function loadStageColors(orm, model) {
    const key = toRaw(model) || noModel;
    if (!stageColorsByModel.has(key)) {
        const request = orm.silent
            .searchRead("crm.stage", [], ["color"])
            .then((stages) => Object.fromEntries(stages.map((s) => [s.id, s.color || 0])))
            .catch(() => ({}));
        stageColorsByModel.set(key, request);
    }
    return stageColorsByModel.get(key);
}

export class PmkKanbanHeader extends CrmKanbanHeader {
    static template = "pmk_deal.KanbanHeader";
    static components = { ...CrmKanbanHeader.components, ColumnProgress: PmkColumnProgress };

    setup() {
        super.setup();
        this.pmkStageColors = {};
        onWillStart(async () => {
            if (this.env.pmkPipeline && this.pmkGroupedByStage) {
                this.pmkStageColors = await loadStageColors(
                    this.env.services.orm, this.props.list.model);
            }
        });
    }

    /** Колонки — этапы сделок (а не менеджеры, месяцы, теги…). */
    get pmkGroupedByStage() {
        return this.group.groupByField?.relation === "crm.stage";
    }

    /** Номер цвета этапа в палитре Odoo; 0 — без цвета, полосы нет. */
    get pmkStageColor() {
        if (!this.env.pmkPipeline || !this.pmkGroupedByStage || !this.group.value) {
            return 0;
        }
        return this.pmkStageColors[this.group.value] || 0;
    }
}

patch(CrmKanbanRenderer, {
    components: { ...CrmKanbanRenderer.components, KanbanHeader: PmkKanbanHeader },
});

// Признак «это воронка» — шапкам колонок и сумме, через окружение рендерера.
patch(CrmKanbanRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        useSubEnv({ pmkPipeline: isPipelineArch(this.props.archInfo) });
    },
});
