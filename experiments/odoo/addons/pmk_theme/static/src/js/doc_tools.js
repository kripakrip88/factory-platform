/** @odoo-module **/
/**
 * «История» кнопкой в строке пути, лента из формы убрана — разбор UX,
 * шаг 65 (11.10.2026).
 *
 * Антон 11.10 (после шага 52 и «Ленты документа в рамке»): «может, блок
 * история вообще уведём в отдельную кнопку в шапке документа? Иконка между
 * статусом и стрелками переключения между документами. История открывается в
 * окне, как рисование доборки сейчас. Отправить сообщение можно убрать,
 * внутренняя заметка тоже пока не нужна, задача — можно перенести в
 * выпадашку действия. Иконка поиск — не понимаю, как работает; файлы —
 * можно перенести во вкладку, где стоят Заметки и Связи (добавить
 * счётчик); показать подписчиков — тоже непонятный функционал».
 *
 * ЧТО ДЕЛАЕТ (только формы основного окна, у которых есть лента <chatter>):
 *   1. Ленты под формой (и справа на широком экране, шаг 49Б) больше нет:
 *      условие контейнера ленты .o-mail-Form-chatter дополняется
 *      «!env.pmkHideChatter» (патч FormCompiler.compile поверх mail). Раскладку
 *      ленты (FormRenderer.mailLayout) не трогаем — превью вложения у счетов
 *      (COMBO) живёт как жило.
 *   2. В строке пути — значок «История» (fa-history) МЕЖДУ этапом (шаг 48) и
 *      стрелками листалки; число — запланированные задачи, просроченные —
 *      значком ⚠ и словом «просрочено» на кнопке (на телефоне слово
 *      прячется, остаётся подсказка). Щелчок — окно «История»
 *      (js/doc_history.js). У несохранённой записи значок погашен: «История
 *      появится после сохранения». Значок в строке пути всегда — и у форм без
 *      метки шага 48, и уже 1200 px, и на телефоне.
 *   3. У форм без вкладки «Файлы» рядом — скрепка с числом файлов, щелчок —
 *      окно «Файлы» (js/doc_files.js).
 *   4. «Задача» (запланировать, mail.activity) — пунктом «⚙ Действия»:
 *      штатное окно планирования; задачи видны в окне «История».
 * Окна-диалоги (лид из почты, строки) не меняются: ленты в окне ядро и так
 * не рисует, значков там нет.
 *
 * ВЫКЛЮЧАТЕЛЬ: группа «Убранное (показать)» (pmk_theme.group_pmk_removed).
 * Человеку в группе — всё как было: лента под формой, без значков, без
 * вкладки «Файлы» и без «Задачи» в «Действиях» (session_info
 * pmk_chatter_in_form — models/doc_history.py). После смены группы —
 * перезагрузить страницу.
 *
 * ⚠️ ПАТЧ ВНУТРЕННОСТЕЙ ЯДРА: FormCompiler.compile (класс
 * o-mail-Form-chatter и его t-if из mail/chatter/web/form_compiler.js),
 * FormController.setup / className, шаблоны web.FormView и трёх
 * primary-копий (xml/doc_tools.xml), реестр cogMenu,
 * store.scheduleActivity. Сверяет tests/test_step65_history.py —
 * перепроверять при обновлении Odoo.
 */
import { Component, onMounted, onWillUpdateProps, useState, useEffect, useSubEnv } from "@odoo/owl";
import { router } from "@web/core/browser/router";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { registry } from "@web/core/registry";
import { useBus } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";
import { FormCompiler } from "@web/views/form/form_compiler";
import { FormController } from "@web/views/form/form_controller";
import { TodoFormCogMenu } from "@project_todo/views/todo_form/todo_form_cog_menu";
import {
    activityCounts,
    chatterAttrs,
    chatterNodeOf,
    countLabel,
    dialogTitle,
    FILES_PAGE,
    filesTooltip,
    hasFilesPage,
    hideChatterIf,
    historyTooltip,
    shouldFetchAttachments,
    shouldMoveChatter,
} from "@pmk_theme/js/doc_tools_rules";
import { PmkFilesDialog, saveThenLoad, threadOf } from "@pmk_theme/js/doc_files";
import { PmkHistoryDialog } from "@pmk_theme/js/doc_history";

// ─── 1. Лента — не в форме ──────────────────────────────────────────────
// Имя вкладки в скомпилированном слоте — строкой-шаблоном (toStringExpression
// ядра, web/views/utils.js).
const FILES_SLOT_NAME = "`" + FILES_PAGE + "`";

patch(FormCompiler.prototype, {
    compile(node, params) {
        const res = super.compile(...arguments);
        // Все контейнеры: под листом / сбоку, в подложке (COMBO), в листе.
        for (const hook of res.querySelectorAll(".o-mail-Form-chatter")) {
            hook.setAttribute("t-if", hideChatterIf(hook.getAttribute("t-if")));
        }
        // Слот вкладки «Файлы» несёт запись своей формы — число в ярлыке
        // (doc_files.js, Notebook.pmkFilesRecord) и в окне строки, где у
        // окружения нет env.model. Имя параметра — строчными: атрибут.
        for (const slot of res.querySelectorAll("[t-set-slot]")) {
            if (slot.getAttribute("name") === FILES_SLOT_NAME) {
                slot.setAttribute("pmk_record", "__comp__.props.record");
            }
        }
        return res;
    },
});

// ─── Ссылка на сообщение (уведомление «Входящих») ───────────────────────
// Раньше открывала документ и подсвечивала сообщение в ленте. Теперь —
// открывает окно «История» с подсветкой, один раз на сообщение.
const HIGHLIGHT_DONE = new Set();

/** Значки «История» и «Файлы» в строке пути. */
export class PmkDocTools extends Component {
    static template = "pmk_theme.DocTools";
    static props = {
        resModel: String,
        resId: { optional: true },
        record: Object,
        filesTab: Boolean,
        hasActivities: Boolean,
        chatterAttrs: Object,
        saveRecord: Function,
    };

    setup() {
        this.store = this.env.services["mail.store"];
        this.dialog = this.env.services.dialog;
        this.state = useState({ thread: threadOf(this.store, this.props.resModel, this.props.resId) });
        onWillUpdateProps((next) => {
            if (next.resModel !== this.props.resModel || next.resId !== this.props.resId) {
                this.state.thread = threadOf(this.store, next.resModel, next.resId);
            }
        });
        // Числа на значках: задачи и файлы документа. Лента под формой их
        // больше не загружает — спрашиваем сами при каждом открытии
        // документа (fresh): нить в хранилище почты живёт всю сессию, и
        // список с прошлого открытия мог устареть.
        useEffect(
            (thread) => this.fetchCounts(thread, { fresh: true }),
            () => [this.state.thread]
        );
        // Документ перечитан (сохранение, «Отправить КП», кнопка шапки) —
        // mail шлёт это событие (chatter/web/form_controller.js); задачи и
        // файлы могли измениться.
        useBus(this.env.bus, "MAIL:RELOAD-THREAD", ({ detail }) => {
            const thread = this.state.thread;
            if (thread && detail?.model === thread.model && detail?.id === thread.id) {
                this.fetchCounts(thread, { force: true });
            }
        });
        onMounted(() => this.openHighlighted());
    }

    /**
     * fresh — открытие документа: вложения перечитать, если их уже не
     * грузит вкладка или ярлык (один запрос на всех — doc_files.js);
     * force — документ перечитан (сохранение, кнопка): спросить в любом
     * случае, идущий запрос мог уйти до изменения.
     */
    fetchCounts(thread, { fresh = false, force = false } = {}) {
        if (!thread) {
            return;
        }
        // Одним запросом: задачи и (если нужно) вложения.
        const list = this.props.hasActivities ? ["activities"] : [];
        if (force || shouldFetchAttachments(thread, { fresh })) {
            list.push("attachments");
        }
        if (list.length) {
            thread.fetchThreadData(list);
        }
    }

    get isNew() {
        return !this.props.resId;
    }

    get counts() {
        const thread = this.state.thread;
        const acts = this.props.hasActivities ? activityCounts(thread?.activities) : activityCounts([]);
        return { ...acts, files: thread?.attachments?.length || 0 };
    }

    get historyTip() {
        return historyTooltip({ isNew: this.isNew, ...this.counts });
    }

    get filesTip() {
        return filesTooltip({ isNew: this.isNew, count: this.counts.files });
    }

    countLabel(n) {
        return countLabel(n);
    }

    get docName() {
        const fromPath = this.env.config?.getDisplayName?.();
        return fromPath || this.props.record?.data?.display_name || "";
    }

    get chatterProps() {
        const { record, resModel, resId, saveRecord, hasActivities, chatterAttrs: attrs } = this.props;
        return {
            threadModel: resModel,
            threadId: resId,
            record,
            saveRecord,
            has_activities: hasActivities,
            hasParentReloadOnActivityChanged: attrs.reloadOnActivity,
            hasParentReloadOnAttachmentsChanged: attrs.reloadOnAttachment,
            hasParentReloadOnFollowersUpdate: attrs.reloadOnFollower,
            hasParentReloadOnMessagePosted: attrs.reloadOnPost,
            isChatterAside: false,
            isInFormSheetBg: false,
        };
    }

    openHistory({ highlightMessageId } = {}) {
        if (this.isNew) {
            return;
        }
        const chatterProps = this.chatterProps;
        if (highlightMessageId) {
            chatterProps.highlightMessageId = highlightMessageId;
        }
        this.dialog.add(PmkHistoryDialog, {
            title: dialogTitle("История", this.docName),
            chatterProps,
        });
    }

    openFiles() {
        if (this.isNew) {
            return;
        }
        const { record, chatterAttrs: attrs } = this.props;
        this.dialog.add(PmkFilesDialog, {
            name: this.docName,
            resModel: this.props.resModel,
            resId: this.props.resId,
            // Как reloadParentView ленты: сохранить, потом перечитать.
            reloadRecord: attrs.reloadOnAttachment
                ? () => saveThenLoad(record, this.props.saveRecord)
                : undefined,
        });
    }

    openHighlighted() {
        const id = router.current?.highlight_message_id;
        if (!id || this.isNew) {
            return;
        }
        const key = `${this.props.resModel},${this.props.resId},${id}`;
        if (HIGHLIGHT_DONE.has(key)) {
            return;
        }
        HIGHLIGHT_DONE.add(key);
        this.openHistory({ highlightMessageId: id });
    }
}

// ─── 2. Контроллер формы: флаг, класс, значки ───────────────────────────
patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        const formEl = this.archInfo.xmlDoc;
        const node = chatterNodeOf(formEl);
        this.pmkHideChatter = shouldMoveChatter({
            chatterInForm: Boolean(session.pmk_chatter_in_form),
            inDialog: Boolean(this.env.inDialog),
            controlPanel: Boolean(this.display?.controlPanel),
            hasChatter: Boolean(node),
            hasStore: Boolean(this.env.services["mail.store"]),
            template: this.constructor.template,
        });
        this.pmkChatterAttrs = chatterAttrs(node);
        this.pmkFilesTab = hasFilesPage(formEl);
        this.pmkSaveRecord = () => this.save();
        // Флаг — всегда явно: форма в окне не унаследует true внешней формы.
        useSubEnv({
            pmkHideChatter: this.pmkHideChatter,
            pmkHasActivities: Boolean(this.pmkHideChatter && this.archInfo.has_activities),
            pmkChatterAttrs: this.pmkChatterAttrs,
            pmkSaveRecord: this.pmkHideChatter ? this.pmkSaveRecord : null,
        });
    },

    /**
     * Класс корня формы: ленты нет — лист в один поток (forms_nexus.scss,
     * «Шаг 65»): на XXL ядро ставит лист и ленту в ряд, и лист без соседа
     * получил бы свою прокрутку.
     */
    get className() {
        const result = super.className;
        if (this.pmkHideChatter) {
            result.o_pmk_chatter_out = true;
        }
        return result;
    },

    get pmkDocToolsOn() {
        return Boolean(this.pmkHideChatter);
    },

    get pmkDocToolsCls() {
        return PmkDocTools;
    },

    get pmkDocToolsProps() {
        const root = this.model.root;
        return {
            resModel: root.resModel,
            resId: root.resId || false,
            record: root,
            filesTab: this.pmkFilesTab,
            hasActivities: Boolean(this.archInfo.has_activities),
            chatterAttrs: this.pmkChatterAttrs,
            saveRecord: this.pmkSaveRecord,
        };
    },
});

// ─── 3. «Задача» в «⚙ Действия» ─────────────────────────────────────────
export class PmkScheduleTask extends Component {
    static template = "pmk_theme.ScheduleTaskItem";
    static components = { DropdownItem };
    static props = {};

    /**
     * Как кнопка «Задача» ленты (mail chatter_patch.js, scheduleActivity):
     * несохранённое — сохранить, потом штатное окно планирования; после
     * него — задачи документа заново (число на «Истории») и документ, если
     * у ленты стоял reload_on_activity. Пункт закрывается вместе с
     * выпадашкой — дальше работаем только с захваченными ссылками.
     */
    async onSelected() {
        const env = this.env;
        const root = env.model?.root;
        const store = env.services["mail.store"];
        if (!root || !store) {
            return;
        }
        if (root.isNew || root.dirty) {
            const saved = await (env.pmkSaveRecord ? env.pmkSaveRecord() : root.save());
            if (!saved || !root.resId) {
                return;
            }
        }
        const { resModel, resId } = root;
        await store.scheduleActivity(resModel, [resId]);
        threadOf(store, resModel, resId)?.fetchThreadData(["activities"]);
        if (env.pmkChatterAttrs?.reloadOnActivity) {
            await root.load();
        }
    }
}

// Документы, где «Задача» есть в «Создать ▾» (pmk_deal, pmk_orders: пункт
// action_pmk_doc_task) — в «⚙» её не дублируем (Антон 25.10.2026: «в
// шестерёнке можно создать задачу — это глупость»).
const TASK_IN_CREATE_MENU = ["crm.lead", "sale.order"];

export const pmkScheduleTaskItem = {
    Component: PmkScheduleTask,
    // Первой группой, над штатными пунктами (у них 1 и 100).
    groupNumber: 0,
    isDisplayed: (env) =>
        env.config?.viewType === "form" &&
        Boolean(env.pmkHideChatter) &&
        Boolean(env.pmkHasActivities) &&
        !TASK_IN_CREATE_MENU.includes(env.model?.root?.resModel),
};

registry.category("cogMenu").add("pmk-schedule-task", pmkScheduleTaskItem, { sequence: 5 });

// «Список дел» (project_todo) берёт из реестра cogMenu ничего: его меню
// возвращает пустой список (личные дела). Сегодня это ничего не меняет — у
// формы дела нет <chatter> (своя панель todo_chatter_panel), лента не
// убирается и пункт не нужен; но если узел ленты у дел появится, «Задача»
// пропала бы вместе с лентой. Поэтому наш пункт — и в их меню, при том же
// условии.
patch(TodoFormCogMenu.prototype, {
    async _registryItems() {
        const items = await super._registryItems(...arguments);
        if (pmkScheduleTaskItem.isDisplayed(this.env)) {
            items.push({
                Component: PmkScheduleTask,
                groupNumber: pmkScheduleTaskItem.groupNumber,
                key: PmkScheduleTask.name,
            });
        }
        return items;
    },
});
