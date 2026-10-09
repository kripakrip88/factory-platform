/**
 * «Нет в справочнике — завести новую…» в выпадашке позиции детали
 * (разбор UX, шаг З-10, 09.10.2026).
 *
 * Вопрос Антона 08.10: «как быть инженеру, если он не нашёл нужную
 * номенклатуру в справочнике?». В поле «Типоразмер» / «Лист» / «Метиз» детали
 * — в окне изделия (views/metal_spec_views.xml) и в редакторе состава под
 * строкой изделия (product_lines_field.xml) — последняя строка выпадашки
 * заводит позицию «на разнос»: короткое окно (views/pending_views.xml,
 * *_pending_form), позиция сразу выбрана в детали. Позиции «на разнос» в
 * выпадашке — с жёлтой меткой «на разнос».
 *
 * ГДЕ ДЕЙСТВУЕТ. Только у поля, в контексте которого есть ключ
 * pmk_pending_create, и только на трёх справочниках. Остальные выпадашки
 * системы — как были.
 *
 * ПОЧЕМУ ШТАТНАЯ «Создать и изменить…», А НЕ СВОЙ ПУНКТ. Механизм ядра уже
 * умеет главное: окно формы на модель поля (FormViewDialog), после записи —
 * позиция выбрана в поле. Меняем подпись, условие показа (и при пустом
 * вводе), контекст окна (своя короткая форма — form_view_ref, метка «на
 * разнос», название из набранного) и заголовок окна. Заведение по набранному
 * тексту без окна (quick create) выключено: no_quick_create в виде,
 * canQuickCreate="false" в редакторе состава.
 *
 * Тот же контекст и у «Новое» в окне «Искать ещё…» — оно зовёт то же
 * this.openMany2X, его и оборачиваем.
 */
import { markup } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { htmlJoin } from "@web/core/utils/html";
import { patch } from "@web/core/utils/patch";
import { escape } from "@web/core/utils/strings";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";

// Короткие окна «Новая позиция на разнос» по справочникам.
export const PENDING_FORMS = {
    "pmk.metal.profile": "pmk_calc.view_metal_profile_pending_form",
    "pmk.metal.sheet": "pmk_calc.view_metal_sheet_pending_form",
    "pmk.metal.fastener": "pmk_calc.view_metal_fastener_pending_form",
};

patch(Many2XAutocomplete.prototype, {
    setup() {
        super.setup(...arguments);
        const open = this.openMany2X;
        this.openMany2X = (params = {}, ...rest) =>
            open(this.pmkPendingParams(params), ...rest);
    },

    /** Поле с заведением «на разнос»? */
    get pmkPendingCreate() {
        return Boolean(this.props.context?.pmk_pending_create) &&
            this.props.resModel in PENDING_FORMS;
    },

    /** Параметры окна заведения: своя форма, метка, заголовок. */
    pmkPendingParams(params) {
        if (!this.pmkPendingCreate || params.resId) {
            return params;
        }
        const context = {
            ...(params.context || {}),
            form_view_ref: PENDING_FORMS[this.props.resModel],
            default_pmk_pending: true,
        };
        const prefer = this.props.context.pmk_prefer_type_id;
        if (this.props.resModel === "pmk.metal.profile" && prefer && !context.default_type_id) {
            context.default_type_id = prefer;
        }
        return { ...params, context, title: _t("Новая позиция на разнос") };
    },

    /** Метка «на разнос» у позиции в выпадашке — нужен её признак. */
    get searchSpecification() {
        const spec = super.searchSpecification;
        return this.pmkPendingCreate ? { ...spec, pmk_pending: {} } : spec;
    },

    addCreateEditSuggestion(params) {
        if (this.pmkPendingCreate) {
            // Всегда, и при пустом вводе: «не нашёл» бывает и до набора.
            return Boolean(this.activeActions.createEdit ?? this.activeActions.create);
        }
        return super.addCreateEditSuggestion(params);
    },

    buildCreateEditSuggestion(request) {
        const suggestion = super.buildCreateEditSuggestion(request);
        if (this.pmkPendingCreate) {
            suggestion.label = _t("Нет в справочнике — завести новую…");
            suggestion.cssClass = `${suggestion.cssClass || ""} pmk-m2o-pending-create`;
        }
        return suggestion;
    },

    buildRecordSuggestion(request, record) {
        const suggestion = super.buildRecordSuggestion(request, record);
        if (this.pmkPendingCreate && record.pmk_pending) {
            // Метка — перед названием: пункт выпадашки режет текст
            // многоточием (text-truncate), и метку в конце длинного названия
            // из чертежа обрезало бы первой. htmlJoin: подпись ядра — уже
            // разметка (подсветка набранного), её оставляет как есть, а
            // простой текст экранирует.
            const badge = markup(
                `<span class="pmk-pending-badge pmk-pending-badge--lead">${escape(_t("на разнос"))}</span>`
            );
            suggestion.label = htmlJoin([badge, suggestion.label ?? ""]);
        }
        return suggestion;
    },

    getCreationContext(value) {
        const context = super.getCreationContext(value);
        if (!this.pmkPendingCreate) {
            return context;
        }
        // Набранный текст — в «Название как в чертеже», а не в name поля
        // (у проката и листа его нет, у метиза имя берётся из названия).
        delete context[`default_${this.props.nameCreateField}`];
        if (value) {
            context.default_pmk_pending_name = value;
        }
        return context;
    },
});
