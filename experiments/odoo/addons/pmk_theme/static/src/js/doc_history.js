/** @odoo-module **/
/**
 * Окно «История» — разбор UX, шаг 65 (11.10.2026).
 *
 * Антон 11.10: «история открывается в окне, как рисование доборки сейчас.
 * Отправить сообщение можно убрать, внутренняя заметка тоже пока не нужно;
 * иконка поиск — непонятно, какой от неё смысл; показать подписчиков — тоже
 * непонятный функционал».
 *
 * Окно во весь экран (Dialog size="fullscreen" — как позиция доборки,
 * pmk_calc/static/src/js/dobor_dialog_fullscreen.js), внутри — ШТАТНАЯ лента
 * документа (mail Chatter) той же записи: письма (в т.ч. привязанные к
 * сделке и лиду почтовым клиентом pmk_mail_ui), заметки, изменения полей
 * (по-русски — tracking_manager и наш перевод), запланированные задачи
 * (отметить выполненной, изменить, отменить — штатно), запланированные
 * письма. Без верхней полосы ленты: нет «Отправить сообщение»,
 * «Внутренней заметки», «Задачи» (она — в «⚙ Действия», js/doc_tools.js),
 * поиска, скрепки (файлы — вкладкой «Файлы», js/doc_files.js), подписчиков и
 * нашей кнопки сворачивания. Горячие клавиши m / shift+m / shift+a уходят
 * вместе с кнопками.
 *
 * Шаблон — primary-копия mail.Chatter (xml/doc_tools.xml). Копия собирается
 * с расширениями mail.Chatter, зарегистрированными РАНЬШЕ неё (в т.ч. нашим
 * xml/chatter.xml: признак модели, сворачивание) — поэтому doc_tools.xml в
 * манифесте после chatter.xml; полосу копия затем убирает целиком.
 *
 * ⚠️ ВНУТРЕННОСТИ mail: класс o-mail-Chatter-topbar, свойства Chatter
 * (has_activities, hasParentReloadOn*, isChatterAside, isInFormSheetBg,
 * record, saveRecord, highlightMessageId). Сверяет tests/test_step65_history.py.
 */
import { Component } from "@odoo/owl";
import { Chatter } from "@mail/chatter/web_portal/chatter";
import { Dialog } from "@web/core/dialog/dialog";

/** Лента в окне: только просмотр истории, всегда развёрнута. */
export class PmkHistoryChatter extends Chatter {
    static template = "pmk_theme.HistoryChatter";

    // Сворачивание ленты (js/chatter_inline.js) — для ленты под формой. В
    // окне история всегда развёрнута, выбор «свёрнуто» не читается и не
    // пишется.
    pmkInitialCollapsed() {
        return false;
    }

    get pmkCollapsedNow() {
        return false;
    }
}

export class PmkHistoryDialog extends Component {
    static template = "pmk_theme.HistoryDialog";
    static components = { Dialog, PmkHistoryChatter };
    static props = {
        close: Function,
        title: String,
        chatterProps: Object,
    };
}
