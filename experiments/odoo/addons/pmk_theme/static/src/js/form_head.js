/** @odoo-module **/
/**
 * Шапка документа — разбор UX, шаг 48 (06.10.2026).
 *
 * Разметка — xml/form_head.xml, стили — scss/forms_nexus.scss и dark.scss,
 * раздел «Шаг 48». Правила без Odoo — js/form_head_rules.js (их гоняет node).
 *
 * 1. КНОПКИ И ЭТАП — В СТРОКУ ПУТИ (только формы с меткой o_pmk_header_up:
 *    сделка и лид, расчёт, доборка — views/step48_header_up.xml). Строка
 *    кнопок <header> занимала под строкой пути ещё 50 px. Ядро уже переносит
 *    в строку пути кнопки-счётчики: разбирает блок button_box отдельно и
 *    рисует его в слоте layout-actions (form_controller.js/xml ядра). Тем же
 *    приёмом разбираем копию <header> на две части — кнопки и этап (та же
 *    раскладка, что в FormCompiler.compileHeader) — и рисуем кнопки перед
 *    счётчиками, этап — перед стрелками листалки. В листе шапка убирается
 *    условием t-if (патч compileHeader по метке формы), а не стилем: копия
 *    одна — нет двойных горячих клавиш и одинаковых id полей.
 *    От 1200 px (SIZES.XL; почему не 992 — form_head_rules.js,
 *    HEADER_UP_MIN_SIZE). Уже — шапка в листе, как раньше; в окне (лид из
 *    почты) — тоже. Смена ширины: контроллер перерисовывается по
 *    ui.bus «resize», лист — своим onResize (до 200 мс).
 *    XML форм не меняется: xpath наследников и тесты, которые ищут кнопки в
 *    <header>, целы.
 * 2. «СОХРАНИТЬ» И «ОТМЕНИТЬ» — подсказки с клавишей (Alt+S, Alt+J; на Mac
 *    Control). Сами кнопки — xml/form_head.xml.
 * 3. «⚙ ДЕЙСТВИЯ ▾» — подсказка с клавишей Alt+U.
 * 4. ЛИСТАЛКА ФОРМЫ без счётчика «1 / 2»: в подсказке стрелки —
 *    «Следующая — Control+N (2 из 6)». Листалки списков и канбана не
 *    тронуты: подсказка штатная.
 * 5. СТРОКА ПУТИ: номер документа с датой («СД-00001 от 27.09.2026») — тоже
 *    «короткое» звено, не сжимается (xml/breadcrumbs.xml).
 *
 * ⚠️ ПАТЧ ВНУТРЕННОСТЕЙ ЯДРА (FormController.setup и components,
 * FormCompiler.compileHeader, шаблоны web.FormView, FormStatusIndicator,
 * FormCogMenu, Breadcrumbs, Pager) — перепроверять при обновлении Odoo.
 * Узлы ядра, на которые опираемся, сверяет tests/test_step48_header.py.
 */
import { useSubEnv } from "@odoo/owl";
import { isMacOS } from "@web/core/browser/feature_detection";
import { _t } from "@web/core/l10n/translation";
import { Pager } from "@web/core/pager/pager";
import { SIZES } from "@web/core/ui/ui_service";
import { patch } from "@web/core/utils/patch";
import { Breadcrumbs } from "@web/search/breadcrumbs/breadcrumbs";
import { FormCogMenu } from "@web/views/form/form_cog_menu/form_cog_menu";
import { FormCompiler } from "@web/views/form/form_compiler";
import { FormController } from "@web/views/form/form_controller";
import { FormStatusIndicator } from "@web/views/form/form_status_indicator/form_status_indicator";
import { StatusBarButtons } from "@web/views/form/status_bar_buttons/status_bar_buttons";
import { useViewCompiler } from "@web/views/view_compiler";
import {
    HEADER_UP_CLASS,
    headerUpAt,
    hotkeyLabel,
    isAlwaysHidden,
    isShortCrumb,
    isStatusNode,
    pagerTooltip,
} from "@pmk_theme/js/form_head_rules";

// Скомпилированная шапка в строке пути ищет компонент строки кнопок у
// контроллера (как ButtonBox у счётчиков). Наследники без своего static
// components (сделка — pmk_deal, расчёт — pmk_calc) берут его отсюда же.
FormController.components = { ...FormController.components, StatusBarButtons };

/** Верхняя шапка формы — прямой ребёнок <form> (не шапка вложенного вида). */
function topHeader(formEl) {
    for (const child of formEl?.children || []) {
        if (child.tagName.toLowerCase() === "header") {
            return child;
        }
    }
    return null;
}

/** Копия шапки, разобранная на кнопки и этап; пустая часть — null. */
function splitHeader(header) {
    const buttons = header.cloneNode(false);
    const status = header.cloneNode(false);
    for (const child of header.children) {
        if (isAlwaysHidden(child.getAttribute("invisible"))) {
            continue;
        }
        const target = isStatusNode(child.tagName, child.classList) ? status : buttons;
        target.append(child.cloneNode(true));
    }
    return {
        buttons: buttons.children.length ? buttons : null,
        status: status.children.length ? status : null,
    };
}

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        this.pmkHeaderButtonsTemplate = null;
        this.pmkHeaderStatusTemplate = null;
        const formEl = this.archInfo.xmlDoc;
        const marked = Boolean(formEl?.classList?.contains(HEADER_UP_CLASS));
        const header =
            marked && !this.env.inDialog && this.display.controlPanel ? topHeader(formEl) : null;
        if (header) {
            const parts = splitHeader(header);
            const templates = {};
            if (parts.buttons) {
                templates.PmkHeaderButtons = parts.buttons;
            }
            if (parts.status) {
                templates.PmkHeaderStatus = parts.status;
            }
            if (Object.keys(templates).length) {
                const compiled = useViewCompiler(this.props.Compiler || FormCompiler, templates, {
                    isSubView: true,
                });
                this.pmkHeaderButtonsTemplate = compiled.PmkHeaderButtons || null;
                this.pmkHeaderStatusTemplate = compiled.PmkHeaderStatus || null;
            }
        }
        // Флаг для листа (compileHeader ниже): шапка сейчас в строке пути.
        // Без шапки наверху — null, и вложенная форма не унаследует флаг
        // внешней.
        const up = Boolean(this.pmkHeaderButtonsTemplate || this.pmkHeaderStatusTemplate);
        useSubEnv({ pmkHeaderUp: up ? () => this.pmkHeaderInPanel() : null });
    },

    /** Шапка рисуется в строке пути: она разобрана и экран от 1200 px. */
    pmkHeaderInPanel() {
        return (
            Boolean(this.pmkHeaderButtonsTemplate || this.pmkHeaderStatusTemplate) &&
            headerUpAt(this.ui.size, SIZES.XL)
        );
    },
});

patch(FormCompiler.prototype, {
    /**
     * Шапка формы с меткой — в листе только когда она не в строке пути.
     * Части шапки для строки пути компилируются отдельно, без формы-предка
     * (el.closest("form") пусто) — им условие не ставится. Своё invisible
     * шапки ядро потом сложит с этим условием (applyInvisible).
     */
    compileHeader(el, params) {
        const compiled = super.compileHeader(...arguments);
        if (compiled && el.closest?.("form")?.classList.contains(HEADER_UP_CLASS)) {
            compiled.setAttribute(
                "t-if",
                "!(__comp__.env.pmkHeaderUp and __comp__.env.pmkHeaderUp())"
            );
        }
        return compiled;
    },
});

patch(FormStatusIndicator.prototype, {
    get pmkSaveTip() {
        return `Сохранить — ${hotkeyLabel("s", isMacOS())}`;
    },
    get pmkDiscardTip() {
        return `Отменить все изменения — ${hotkeyLabel("j", isMacOS())}`;
    },
});

patch(FormCogMenu.prototype, {
    get pmkCogTip() {
        return `Действия — ${hotkeyLabel("u", isMacOS())}`;
    },
});

patch(Pager.prototype, {
    /** Подсказка стрелки: у листалки формы — клавиша и «N из M». */
    pmkTooltip(dir) {
        const { limit, withAccessKey, offset, total } = this.props;
        if (limit === 1 && withAccessKey) {
            return pagerTooltip(dir, offset, total, isMacOS());
        }
        return dir > 0 ? _t("Next") : _t("Previous");
    },
});

patch(Breadcrumbs.prototype, {
    pmkShortCrumb(name) {
        return isShortCrumb(name);
    },
});
