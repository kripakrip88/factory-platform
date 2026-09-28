/** @odoo-module **/
// Полоса стадий — одной аккуратной кнопкой со списком вместо ряда стрелок.
//
// Разбор UX, шаг 4 (Антон, 28.09.2026): «кнопки этапов переделал на более
// аккуратные и выпадашкой, очень много места занимают и отвлекают внимание».
//
// Было: ряд стрелок во всю ширину, текущая — ярко-оранжевая, самое кричащее
// пятно на экране; пройденные и будущие выглядят одинаково.
// Стало: одна кнопка «▰▰▱▱ Расчёт · 2 дн ▾». Деления — сколько пути пройдено,
// дальше название текущей стадии и срок в ней. По щелчку — список стадий:
// пройденные с галочкой, текущая выделена, следующие обычным текстом.
//
// Фон кнопки — цвет стадии, мягким тоном (Антон, 28.09.2026: «лайм слишком
// ярко, может сделаем фон кнопки цветом этапа?»). У стадий сделки цвет свой,
// его выбирают палитрой в «Настройки CRM → Этапы». У документов, где цвета
// стадий нет (закупка, производство, доборка), цвет — по смыслу стадии:
// начало пути серое, дальше голубое, конец пути зелёный, тупик (отменено,
// ошибка, лом) розовый, прочее вне пути («К согласованию») жёлтое.
//
// ⚠️ ПОЧЕМУ ПАТЧ ПРОТОТИПА, А НЕ СВОЙ ВИДЖЕТ. Режим «одна кнопка со списком»
// в Odoo уже есть — так полоса выглядит на телефоне (ветка env.isSmall в
// adjustVisibleItems). Мы включаем его и на широком экране. Патч прототипа
// StatusBarField доходит до всех его наследников: время в стадии (mail),
// сделка CRM (rotting_statusbar_duration), проводка счёта (account). Свой
// виджет пришлось бы прописывать в каждый вид каждого модуля. У проводки
// счёта надпись кнопки рисует свой шаблон (название и замок), делений там
// нет — эта полоса видна только группе «защищённого» учёта, в ней никого.
//
// Исключение — hr.VersionsTimeline (история договоров в карточке
// сотрудника): там кнопки обёрнуты в свои блоки и есть кнопка «+», в одну
// кнопку это не сворачивается.
//
// Шаблонная часть (кнопка открывается и там, где стадию руками не меняют) —
// в xml/statusbar_compact.xml. Оформление — scss/forms_nexus.scss, раздел
// «Полоса стадий».

import { markup } from "@odoo/owl";
import { htmlSprintf } from "@web/core/utils/html";
import { patch } from "@web/core/utils/patch";
import { StatusBarField } from "@web/views/fields/statusbar/statusbar_field";

const NOT_COMPACT = new Set(["hr.VersionsTimeline"]);

// Больше шести делений не читаются как «шаги» — тогда только название.
const MAX_STEPS = 6;

// Палитра Odoo (номер цвета → наш мягкий тон, scss/forms_nexus.scss).
const TONES = [
    "grey",
    "red",
    "orange",
    "yellow",
    "cyan",
    "purple",
    "almond",
    "teal",
    "blue",
    "raspberry",
    "green",
    "violet",
];

// Модели стадий, у которых есть поле цвета. Список закрытый: запросить
// поле, которого у модели нет, — ошибка чтения, и полоса не загрузится.
const COLORED_STAGES = new Set(["crm.stage"]);

// Тупиковые исходы — не шаг пути, даже если вид перечислил их в
// statusbar_visible. У служебных писем Odoo путь «В очереди → Отправлено →
// Получено → Ошибка → Отменено»: без этого списка 115 отменённых писем
// показали бы полную полосу и галочки у «Отправлено» и «Получено».
const OFF_PATH = new Set([
    "cancel",
    "canceled",
    "cancelled",
    "error",
    "exception",
    "rejected",
    "scrap",
    "lost",
]);

patch(StatusBarField.prototype, {
    get pmkCompact() {
        return !NOT_COMPACT.has(this.constructor.template);
    },

    // Путь задан видом: у стадий-записей — полем свёртки (fold_field), у
    // списка значений — statusbar_visible. Без этого все значения выглядят
    // одной цепочкой, хотя часть из них — взаимоисключающие исходы: обрезок
    // лазера из «Предложен» сразу уходит в «Оказался ломом», минуя
    // «Подтверждён». Нарисовали бы галочку у «Подтверждён» и полную полосу —
    // неправда. Поэтому без заданного пути — только название и срок.
    get pmkHasPath() {
        return this.field.type === "many2one"
            ? Boolean(this.props.foldField)
            : Boolean(this.props.visibleSelection?.length);
    },

    // Стадия «на пути»: не свёрнута и, для списка значений, входит в
    // statusbar_visible. «Отменён», «Потерян» и другие стадии вне пути
    // показываются, только когда документ в них, — деления и галочки для
    // них не рисуем: отменённая закупка не «прошла» стадию «Заказ».
    pmkOnPath(item) {
        if (!this.pmkHasPath || item.isFolded) {
            return false;
        }
        const { visibleSelection } = this.props;
        if (this.field.type === "selection") {
            return visibleSelection.includes(item.value) && !OFF_PATH.has(item.value);
        }
        return true;
    },

    // У стадий сделки дочитываем их цвет (ядро берёт только название).
    getFieldNames(props) {
        const names = super.getFieldNames(...arguments);
        const { relation } = props.record.fields[props.name];
        if (this.pmkCompact && COLORED_STAGES.has(relation) && !names.includes("color")) {
            return [...names, "color"];
        }
        return names;
    },

    pmkTone(item) {
        if (Number.isInteger(item.pmkColor)) {
            return TONES[item.pmkColor] || "grey";
        }
        if (!this.pmkHasPath || item.isFolded) {
            return "grey";
        }
        if (!this.pmkOnPath(item)) {
            return OFF_PATH.has(item.value) ? "red" : "yellow";
        }
        const path = this.getAllItems().filter((i) => this.pmkOnPath(i));
        const index = path.findIndex((i) => i.value === item.value);
        if (index === path.length - 1) {
            return "green";
        }
        return index === 0 ? "grey" : "blue";
    },

    // Тон кнопки — по текущей стадии. Шаблон кладёт его в data-pmk-tone.
    get pmkCurrentTone() {
        const current = this.getAllItems().find((item) => item.isSelected);
        return current ? this.pmkTone(current) : "grey";
    },

    // Всегда ветка «узкого экрана» из ядра: видна только кнопка со списком.
    adjustVisibleItems() {
        if (!this.pmkCompact || !this.items.inline?.length || !this.dropdownRef.el) {
            return super.adjustVisibleItems(...arguments);
        }
        this.items.before = [];
        this.items.after = [...this.items.folded];
        const itemEls = this.rootRef.el.querySelectorAll(
            ".o_arrow_button:not(.dropdown-toggle)"
        );
        for (const el of [this.beforeRef.el, this.afterRef.el, ...itemEls]) {
            el?.classList.add("d-none");
        }
        this.dropdownRef.el.classList.remove("d-none");
    },

    getAllItems() {
        const items = super.getAllItems(...arguments);
        if (!this.pmkCompact) {
            return items;
        }
        if (this.field.type === "many2one") {
            const colors = new Map(
                (this.specialData.data || []).map((option) => [option.id, option.color])
            );
            for (const item of items) {
                item.pmkColor = colors.get(item.value);
            }
        }
        const path = items.filter((item) => this.pmkOnPath(item));
        const current = path.findIndex((item) => item.isSelected);
        path.forEach((item, index) => {
            item.pmkPassed = current > -1 && index < current;
        });
        return items;
    },

    getDropdownItemClassNames(item) {
        const classNames = super.getDropdownItemClassNames(...arguments);
        if (!this.pmkCompact) {
            return classNames;
        }
        // dropdown-item_active_noarrow — отказ от галочки ядра у выбранного
        // пункта (webclient.scss): она стоит абсолютом и сдвигала бы нашу
        // точку текущей стадии из строки.
        return [
            classNames,
            "o_pmk_stage_item",
            "dropdown-item_active_noarrow",
            item.pmkPassed && "o_pmk_stage_passed",
            item.isFolded && "o_pmk_stage_folded",
            item.isSelected && `o_pmk_tone_${this.pmkTone(item)}`,
        ]
            .filter(Boolean)
            .join(" ");
    },

    // Надпись кнопки: деления, название, срок в стадии.
    getCurrentLabel() {
        if (!this.pmkCompact) {
            return super.getCurrentLabel(...arguments);
        }
        const items = this.getAllItems();
        const current = items.find((item) => item.isSelected);
        if (!current) {
            return super.getCurrentLabel(...arguments);
        }
        let steps = "";
        const path = items.filter((item) => this.pmkOnPath(item));
        if (this.pmkOnPath(current) && path.length > 1 && path.length <= MAX_STEPS) {
            const done = path.indexOf(current) + 1;
            steps = path
                .map((_, index) =>
                    index < done
                        ? '<i class="o_pmk_step o_pmk_step_done"></i>'
                        : '<i class="o_pmk_step"></i>'
                )
                .join("");
            steps = htmlSprintf(
                markup('<span class="o_pmk_stage_steps" aria-hidden="true">%s</span>'),
                markup(steps)
            );
        }
        // Сделка «залежалась» (у стадии задан срок rotting_threshold_days и он
        // вышел): вместо срока — красная плашка «N дн», как на стрелке ядра.
        // Плашку ядро рисует только на стрелках, а их в компактном виде нет.
        // Сейчас сроки у стадий не заданы, но настройка одна галочка.
        const { is_rotting: isRotting, rotting_days: rottingDays } = this.props.record.data;
        if (isRotting && current.isSelected && this.constructor.template === "mail.RottingStatusBarDurationField") {
            return htmlSprintf(
                markup(
                    '%s<span class="o_pmk_stage_name" title="%s">%s</span><span class="badge rounded-pill o_mail_resource_rotting_bg" title="%s">%s дн</span>'
                ),
                steps,
                current.label,
                current.label,
                this.title || "",
                rottingDays
            );
        }
        const time = current.shortTimeInStage
            ? htmlSprintf(
                  markup('<span class="o_pmk_stage_time" title="%s">%s</span>'),
                  current.fullTimeInStage || "",
                  current.shortTimeInStage
              )
            : "";
        return htmlSprintf(
            markup('%s<span class="o_pmk_stage_name" title="%s">%s</span>%s'),
            steps,
            current.label,
            current.label,
            time
        );
    },

    // Кнопка теперь открывается и там, где стадию руками не меняют (закупка,
    // производство, счёт): список показывает путь. Пункты там помечены
    // disabled, но это только вид — клавиатурой (стрелки + Enter) пункт всё
    // равно «нажимается». Без этой проверки Enter записал бы состояние
    // документа в обход его кнопок: например, «Заказ» у закупки без
    // подтверждения. То же с текущей стадией: Enter на ней сохранил бы
    // форму с недописанными правками, хотя стадию никто не менял.
    async selectItem(item) {
        if (this.pmkCompact && (this.props.isDisabled || item?.isSelected)) {
            return;
        }
        return super.selectItem(...arguments);
    },
});
