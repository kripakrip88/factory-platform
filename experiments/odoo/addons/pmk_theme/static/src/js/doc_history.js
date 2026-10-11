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
import { Message } from "@mail/core/common/message";
import { Thread } from "@mail/core/common/thread";
import { Dialog } from "@web/core/dialog/dialog";
import { createElementWithContent } from "@web/core/utils/html";
import {
    TABLE_HEAD,
    actionWord,
    authorLabel,
    headLine,
    plainText,
    stampText,
    subtypeLine,
    tmRows,
    tmTree,
    trackingRows,
} from "@pmk_theme/js/history_rules";

/**
 * Событие окна «История» — разбор UX, шаг 66 (11.10.2026): как «История
 * изменений» МоегоСклада. Заголовок «Карнеев А., изменено 08.10.2026 22:48»,
 * под ним таблица «Поле | Было | Стало» (изменения полей и строк
 * tracking_manager — по одной позиции на строку), текст заметок и писем — как
 * есть. Без значков действий (реакция, звёздочка, ссылка, ответ), без правки
 * сообщения, без разделителей дат (дата — в заголовке).
 *
 * Свой шаблон pmk_theme.HistoryMessage (xml/doc_history.xml), НЕ расширение
 * mail.Message: ни одного xpath в шаблон ядра, у Discuss, почтового клиента,
 * чата и ленты под формой (выключатель «Убранное (показать)») — штатное
 * сообщение по построению. Логика Message (тень письма, подсветка сообщения
 * по ссылке, ссылки в тексте, значок доставки) наследуется как есть.
 *
 * ⚠️ ВНУТРЕННОСТИ mail: Message.formatTracking (core/web/message_patch.js),
 * prepareMessageBody, onClickNotification, onClickAttachmentUnlink, ссылки
 * t-ref root / body / shadowBody, шаблон mail.Message.notification; свойства
 * Thread showDates и messageActions. Сверяет tests/test_step66_history_view.py.
 */
export class PmkHistoryMessage extends Message {
    static template = "pmk_theme.HistoryMessage";

    /** Значков действий нет — долгое нажатие на телефоне ничего не открывает. */
    openMobileActions() {}

    get pmkRootClass() {
        return this.props.className || "";
    }

    get pmkIsEmail() {
        const type = this.message.message_type;
        return Boolean(type && type.includes("email"));
    }

    get pmkAuthor() {
        const message = this.message;
        const author = message.author;
        const odoobot = this.store.odoobot;
        return authorLabel({
            hasAuthor: Boolean(author),
            isSystem: Boolean(author && odoobot && message.author_id?.eq?.(odoobot)),
            // Письмо от контрагента-организации: название как есть, не «Фамилия И.»
            // (is_company ядро присылает с автором — res.partner._to_store_defaults).
            isCompany: Boolean(message.author_id?.is_company),
            name: author ? message.authorName : "",
            emailFrom: message.email_from,
        });
    }

    get pmkBodyText() {
        return plainText(String(this.message.body || ""));
    }

    get pmkAction() {
        const message = this.message;
        return actionWord({
            messageType: message.message_type,
            isNote: Boolean(message.isNote),
            isDiscussion: Boolean(message.isDiscussion),
            hasTracking: message.trackingValues.length > 0,
            hasX2m: this.pmkIsTm,
            bodyText: this.pmkBodyText,
            bodyHtml: String(message.body || ""),
            subtypeDescription: message.subtype_id?.description,
        });
    }

    get pmkStamp() {
        return stampText(this.message.datetime);
    }

    get pmkHead() {
        return headLine({ author: this.pmkAuthor, action: this.pmkAction, stamp: this.pmkStamp });
    }

    get pmkSubtype() {
        return subtypeLine({
            action: this.pmkAction,
            description: this.message.subtype_id?.description,
            bodyText: this.pmkBodyText,
        });
    }

    /** Разбор записи tracking_manager — один раз на тело сообщения. */
    get pmkTm() {
        const body = String(this.message.body || "");
        if (this._pmkTmBody !== body) {
            this._pmkTmBody = body;
            this._pmkTm = body && !this.pmkIsEmail ? tmTree(createElementWithContent("div", this.message.body)) : null;
        }
        return this._pmkTm;
    }

    get pmkIsTm() {
        return Boolean(this.pmkTm);
    }

    get pmkHeadCells() {
        return TABLE_HEAD;
    }

    /** Строки «Поле | Было | Стало»: изменения полей, затем строки tracking_manager. */
    get pmkRows() {
        const items = this.message.trackingValues.map((value) => {
            const info = value.fieldInfo || {};
            const before = this.formatTracking(info, value.oldValue);
            if (info.isPropertyField) {
                // Свойство: ядро показывает одно значение (прежнее) без стрелки.
                return { field: info.changedField, old: before, new: "" };
            }
            return { field: info.changedField, old: before, new: this.formatTracking(info, value.newValue) };
        });
        const rows = trackingRows(items);
        if (this.pmkTm) {
            rows.push(...tmRows(this.pmkTm));
        }
        return rows.map((row, index) => ({ ...row, key: index }));
    }

    /** Текст заметки или системной записи — как есть (кроме разобранной в таблицу). */
    get pmkShowBody() {
        return !this.pmkIsEmail && !this.message.isBodyEmpty && !this.pmkIsTm;
    }

    get pmkShowSubject() {
        const message = this.message;
        return Boolean(message.subject && !message.isSubjectSimilarToThreadName && !message.isSubjectDefault);
    }
}

/**
 * Лента окна: без разделителей дат (дата — в заголовке события) и без
 * значков действий; сообщение — PmkHistoryMessage. Геттер components, а не
 * поле: mail дописывает компоненты Thread патчами, копия на момент загрузки
 * модуля упустила бы поздние добавки (Owl берёт components у класса при
 * отрисовке).
 */
export class PmkHistoryThread extends Thread {
    static get components() {
        return { ...Thread.components, Message: PmkHistoryMessage };
    }

    // Тоже геттер: свойства по умолчанию Thread могут дописать патчи.
    static get defaultProps() {
        return { ...Thread.defaultProps, showDates: false, messageActions: false };
    }
}

/** Лента в окне: только просмотр истории, всегда развёрнута. */
export class PmkHistoryChatter extends Chatter {
    static template = "pmk_theme.HistoryChatter";

    // Шаг 66: лента окна — PmkHistoryThread. Геттер: chatter_patch.js
    // дописывает Chatter.components через Object.assign после загрузки
    // chatter.js. Вернуть штатную ленту шага 65 — убрать строку Thread.
    static get components() {
        return { ...Chatter.components, Thread: PmkHistoryThread };
    }

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
