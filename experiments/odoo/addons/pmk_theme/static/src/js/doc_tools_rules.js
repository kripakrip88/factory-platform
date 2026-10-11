/** @odoo-module **/
/**
 * «История» кнопкой в строке пути — разбор UX, шаг 65 (11.10.2026): правила
 * без Odoo.
 *
 * Чистые функции без импортов Odoo — их гоняет node
 * (static/tests/doc_tools_step65.test.mjs). Используют doc_tools.js,
 * doc_history.js, doc_files.js.
 *
 * Антон 11.10: «блок история вообще уведём в отдельную кнопку в шапке
 * документа — иконка между статусом и стрелками переключения между
 * документами; история открывается в окне как рисование доборки».
 */

/**
 * Шаблоны контроллеров формы, в которые встаёт значок «История». Только у
 * них есть место под значок в строке пути (xml/doc_tools.xml): web.FormView
 * и три primary-копии, собранные ДО нашего бандла (правка web.FormView до них
 * не доходит — core/templates.js, blockId). У формы с другим шаблоном лента
 * остаётся под формой: история не теряется.
 */
export const TOOL_TEMPLATES = Object.freeze([
    "web.FormView",
    "resource.FormViewWithHtmlExpander",
    "project.ProjectTaskFormView",
    "project.ProjectFormView",
]);

/** Имя вкладки «Файлы» (models/doc_history.py, FILES_PAGE). */
export const FILES_PAGE = "pmk_files";

/** Выражение, которым лента убирается из скомпилированной формы. */
export const HIDE_FLAG_EXPR = "__comp__.env.pmkHideChatter";

/**
 * Условие t-if контейнера ленты (.o-mail-Form-chatter): прежнее условие mail
 * И «лента не вынесена в окно». Пустое прежнее — true.
 */
export function hideChatterIf(tIf) {
    const prev = (tIf || "").trim() || "true";
    return `(${prev}) and !${HIDE_FLAG_EXPR}`;
}

/**
 * Убирать ли ленту из формы в окно «История».
 *   chatterInForm — выключатель: человек в группе «Убранное (показать)»
 *                   (session_info.pmk_chatter_in_form) — лента под формой;
 *   inDialog      — форма в окне: ленты там и так нет (mail), значка тоже;
 *   controlPanel  — без строки пути значку негде стоять;
 *   hasChatter    — в разметке есть <chatter>;
 *   hasStore      — почта загружена (сервис mail.store);
 *   template      — шаблон контроллера из TOOL_TEMPLATES.
 */
export function shouldMoveChatter({
    chatterInForm = false,
    inDialog = false,
    controlPanel = false,
    hasChatter = false,
    hasStore = false,
    template = "",
} = {}) {
    return Boolean(
        !chatterInForm &&
            !inDialog &&
            controlPanel &&
            hasChatter &&
            hasStore &&
            TOOL_TEMPLATES.includes(template)
    );
}

function tag(node) {
    return String(node?.tagName || "").toLowerCase();
}

function childrenOf(node) {
    return Array.from(node?.children || []);
}

/**
 * Узел <chatter> формы: прямо в <form> или в <sheet> (как ищет mail —
 * form_compiler.js). Вложенные формы строк (внутри <field>) не считаются.
 */
export function chatterNodeOf(formEl) {
    for (const child of childrenOf(formEl)) {
        if (tag(child) === "chatter") {
            return child;
        }
        if (tag(child) === "sheet") {
            const inSheet = childrenOf(child).find((n) => tag(n) === "chatter");
            if (inSheet) {
                return inSheet;
            }
        }
    }
    return null;
}

/** Атрибуты узла <chatter> — как их читает mail (form_compiler.js). */
export function chatterAttrs(node) {
    const has = (name) => Boolean(node?.getAttribute?.(name));
    return {
        reloadOnActivity: has("reload_on_activity"),
        reloadOnAttachment: has("reload_on_attachment"),
        reloadOnFollower: has("reload_on_follower"),
        reloadOnPost: has("reload_on_post"),
    };
}

/** Есть ли у формы вкладка «Файлы» (её ставит сервер): sheet/notebook/page. */
export function hasFilesPage(formEl) {
    for (const sheet of childrenOf(formEl).filter((n) => tag(n) === "sheet")) {
        for (const notebook of childrenOf(sheet).filter((n) => tag(n) === "notebook")) {
            const found = childrenOf(notebook).some(
                (page) => tag(page) === "page" && page.getAttribute?.("name") === FILES_PAGE
            );
            if (found) {
                return true;
            }
        }
    }
    return false;
}

/** Число на значке: 0 — пусто (ничего не рисуем), больше 99 — «99+». */
export function countLabel(n) {
    const v = Number(n) || 0;
    if (v <= 0) {
        return "";
    }
    return v > 99 ? "99+" : String(v);
}

/**
 * Подсказка значка «История». Цвет просрочки повторён словом.
 *   isNew — запись не сохранена: истории ещё нет.
 */
export function historyTooltip({ isNew = false, activities = 0, overdue = 0 } = {}) {
    if (isNew) {
        return "История появится после сохранения";
    }
    if (!activities) {
        return "История";
    }
    const tail = overdue ? `, просрочено: ${overdue}` : "";
    return `История · задач: ${activities}${tail}`;
}

/** Подсказка скрепки (формы без вкладок). */
export function filesTooltip({ isNew = false, count = 0 } = {}) {
    if (isNew) {
        return "Файлы появятся после сохранения";
    }
    return count ? `Файлы · ${count}` : "Файлы";
}

/** Заголовок окна: «История · СМ-00025» (номер не обрезается). */
export function dialogTitle(word, name) {
    const n = String(name || "").trim();
    return n ? `${word} · ${n}` : word;
}

/**
 * Спрашивать ли вложения документа у сервера.
 *   fresh — первый показ документа (открытие формы, вкладки, окна): нить в
 *           хранилище почты живёт всю сессию, и «уже загружено» может быть
 *           списком часовой давности — почта (pmk_mail_ui) или коллега могли
 *           добавить файл. Штатная лента под формой тоже перечитывала
 *           вложения при каждом открытии (env.chatter.fetchThreadData).
 * Запрос уже идёт — второй не нужен: значок, ярлык вкладки и сама вкладка
 * открываются разом, ответ один на всех.
 */
export function shouldFetchAttachments(thread, { fresh = false } = {}) {
    if (!thread || thread.isLoadingAttachments) {
        return false;
    }
    return Boolean(fresh || !thread.areAttachmentsLoaded);
}

/** Сколько задач и сколько просрочено (state — поле mail.activity). */
export function activityCounts(activities) {
    const list = Array.from(activities || []).filter(Boolean);
    return {
        activities: list.length,
        overdue: list.filter((a) => a?.state === "overdue").length,
    };
}
