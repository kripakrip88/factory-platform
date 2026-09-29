import { Component, onWillUpdateProps, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";

import { formatMessageDate, pluralForm, senderName } from "../utils";
import { MessageCard } from "./message_card";

/**
 * ПРАВКА ПМК: переписка целиком под письмом («Почта как в Mail.ru», В1;
 * шаг 20 плана, 30.09.2026).
 *
 * Было: под письмом — список «ещё N писем в этой переписке» одними адресами,
 * щелчок открывал письмо вместо текущего. Стало, как в Mail.ru:
 *   - вся переписка лентой, новые сверху;
 *   - самое новое письмо и письмо строки, по которой щёлкнули, развёрнуты,
 *     остальные свёрнуты в строку «Имя · мы · начало текста · скрепка ·
 *     дата» (жирная, если не прочитано); щелчок разворачивает на месте;
 *   - от 6 писем видны 2 самых новых и самое первое (заявка), середина —
 *     «ещё N писем»; развёрнутые, свёрнутые обратно и непрочитанные на
 *     момент открытия не прячутся никогда; «ещё» из одного письма не
 *     бывает (строка того же роста, что кнопка), кусков «ещё» — не больше
 *     двух;
 *   - наши письма (is_outgoing: адрес ящика или папка Отправленные/
 *     Черновики) — на бледной подложке и с плашкой «мы»;
 *   - у развёрнутого письма свои «Ответить» и «Переслать». На НАШЕМ письме
 *     «Ответить» скрыт до шага 21: ответ ушёл бы нам же (Г3,
 *     mail_client_compose.py), «Переслать» есть.
 *
 * Тело письма, кроме открытого, читается лениво — get_message_detail при
 * развороте, один запрос на письмо. Тело приходит с сервера только на
 * просмотр (EXAMINE, BODY.PEEK): отметку «прочитано» на mail.ru разворот
 * не ставит, и отсюда никаких set_seen / pmk_mark_* нет. Прочитанным
 * переписку помечает pmk_mail_ui/thread_seen.js: открытие строки — всё,
 * что не новее письма строки; письмо ленты, тело которого пришло и которое
 * развёрнуто, — всё, что не новее его (props.onShown → крючок корня
 * conversationShown). Самое новое письмо гаснет, только когда его тело
 * показано, а не при открытии: не пришло тело — письмо остаётся
 * непрочитанным, и пометка не пишет строку письма, пока его тело ещё
 * читается с почтового сервера (разбор шага 20: иначе запись тела
 * упиралась в пометку, Odoo повторял запрос целиком — второй вход в
 * mail.ru и второе чтение тела).
 *
 * Открыли другое письмо (props.detail.id сменился) — всё состояние заново,
 * а ответы на запросы прежней переписки выбрасываются (свой знак, как
 * openToken у selectMessage).
 */

/** Новее ли письмо a письма b: по дате, при равной — по id. */
function isNewer(a, b) {
    const da = a.date || "";
    const db = b.date || "";
    return da > db || (da === db && a.id > b.id);
}

/** Письма переписки, новые сверху (дата ↓, id ↓). */
export function newestFirst(thread) {
    return [...(thread || [])].sort((a, b) => (isNewer(a, b) ? -1 : isNewer(b, a) ? 1 : 0));
}

/** Самое новое письмо переписки или null. Одно правило с thread_seen.js. */
export function newestOf(thread) {
    let best = null;
    for (const item of thread || []) {
        if (!best || isNewer(item, best)) {
            best = item;
        }
    }
    return best;
}

/**
 * Лента переписки: [{type: "message", key, item, expanded}
 *                   | {type: "more", key, ids, count}], новые сверху.
 *
 * expanded — id развёрнутых писем; shown — id, которые прятать нельзя
 * (непрочитанные на момент открытия, раскрытые кнопкой «ещё», свёрнутые
 * после разворота). До
 * threshold писем видны все; больше — head самых новых, tail самых
 * старых, развёрнутые и shown, прочее — в «ещё N». Одно спрятанное письмо
 * не прячем (кнопка «ещё 1 письмо» не короче самой строки). Кусков «ещё»
 * больше двух не бывает: оставляем спрятанными два самых длинных, прочее
 * показываем.
 */
export function conversationLayout(
    thread,
    { expanded = [], shown = [], threshold = 5, head = 2, tail = 1 } = {}
) {
    const open = new Set(expanded);
    const keep = new Set(shown);
    const items = newestFirst(thread);
    const count = items.length;
    const visible = items.map(
        (item, index) =>
            count <= threshold ||
            index < head ||
            index >= count - tail ||
            open.has(item.id) ||
            keep.has(item.id)
    );
    let runs = [];
    for (let index = 0; index < count; index++) {
        if (visible[index]) {
            continue;
        }
        const last = runs[runs.length - 1];
        if (last && last.end === index) {
            last.end = index + 1;
        } else {
            runs.push({ start: index, end: index + 1 });
        }
    }
    runs = runs.filter((run) => run.end - run.start > 1);
    if (runs.length > 2) {
        const longest = [...runs]
            .sort((a, b) => b.end - b.start - (a.end - a.start) || a.start - b.start)
            .slice(0, 2);
        runs = runs.filter((run) => longest.includes(run));
    }
    const hiddenAt = new Map(runs.map((run) => [run.start, run]));
    const layout = [];
    for (let index = 0; index < count; index++) {
        const run = hiddenAt.get(index);
        if (run) {
            const ids = items.slice(run.start, run.end).map((item) => item.id);
            layout.push({ type: "more", key: `more-${ids[0]}`, ids, count: ids.length });
            index = run.end - 1;
            continue;
        }
        const item = items[index];
        layout.push({ type: "message", key: `m-${item.id}`, item, expanded: open.has(item.id) });
    }
    return layout;
}

const RE_PREFIX = /^\s*(?:re|fwd?|fw|ответ|отв|пересл)\s*(?:\[\d+\]|\(\d+\))?\s*:\s*/i;

/** Тема без «Re:/Fwd:/Fw:/Ответ:» (сколько бы их ни было), без регистра. */
export function normalizeSubject(subject) {
    let text = (subject || "").trim();
    while (RE_PREFIX.test(text)) {
        text = text.replace(RE_PREFIX, "");
    }
    return text.replace(/\s+/g, " ").toLowerCase();
}

/**
 * Начало текста в строке свёрнутого письма: превью, если есть (у писем,
 * тело которых ещё не приходило с сервера, его нет); иначе тема, если она
 * не та же, что у переписки; иначе пусто — «Имя · дата · скрепка».
 */
export function collapsedSnippet(item, threadSubject) {
    const preview = (item.preview || "").trim();
    if (preview) {
        return preview;
    }
    const subject = (item.subject || "").trim();
    if (subject && normalizeSubject(subject) !== normalizeSubject(threadSubject)) {
        return subject;
    }
    return "";
}

/**
 * Письма ленты. Открытого письма в переписке быть не должно (с шага 20
 * get_thread оставляет из копий открытую), но если его нет — ставим сами:
 * письмо, по которому щёлкнули, видно всегда.
 */
export function conversationItems(detail, thread) {
    const items = thread || [];
    if (items.some((item) => item.id === detail.id)) {
        return items;
    }
    return [...items, { ...detail, has_attachment: Boolean(detail.attachments?.length) }];
}

/** «ещё 3 письма» — форма числа по языку (pluralForm, utils.js). */
export function moreLabel(count, lang = user.lang) {
    const form = pluralForm(count, lang);
    if (form === "one") {
        return _t("%s more message", count);
    }
    if (form === "few") {
        return _t("%s more messages (2-4)", count);
    }
    return _t("%s more messages", count);
}

export class Conversation extends Component {
    static template = "mail_client.Conversation";
    static components = { MessageCard };
    static props = {
        // Открытое письмо (строка списка) — его тело уже загружено.
        detail: { type: Object },
        thread: { type: Array },
        getScroller: { type: Function },
        // compose(mode, messageId) корня почты.
        onReply: { type: Function },
        // «Показать картинки» у открытого письма — через корень (там своя
        // сверка с выделенной строкой).
        onAllowImages: { type: Function },
        onDownloadAttachment: { type: Function },
        // Письмо ленты показано: развёрнуто, и его тело пришло с сервера
        // (крючок корня conversationShown — для отметки «прочитано»).
        onShown: { type: Function, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState(this.freshState(this.props));
        // Знак переписки на экране: ответ на запрос прежней — выбросить.
        this.epoch = 0;
        this.loadExpanded(this.props);
        onWillUpdateProps((next) => {
            if (next.detail.id !== this.props.detail.id) {
                this.epoch++;
                Object.assign(this.state, this.freshState(next));
                this.loadExpanded(next);
            }
        });
    }

    /** Самое новое письмо развёрнуто сразу — его тело нужно сразу, а не по
     *  щелчку. Открытое письмо уже загружено корнем. */
    loadExpanded({ detail }) {
        for (const id of Object.keys(this.state.expanded).map(Number)) {
            if (id !== detail.id && !this.state.details[id]) {
                this.load(id);
            }
        }
    }

    /**
     * Состояние открытой переписки. Непрочитанные запоминаем СЕЙЧАС: при
     * открытии thread_seen.js гасит их (ответ сервера придёт позже, а
     * props строятся раньше), но спрятать их в «ещё N» после этого нельзя —
     * лента бы перестроилась на глазах.
     */
    freshState({ detail, thread }) {
        const items = conversationItems(detail, thread);
        const expanded = { [detail.id]: true };
        const newest = newestOf(items);
        if (newest) {
            expanded[newest.id] = true;
        }
        const shown = {};
        for (const item of items) {
            if (!item.flag_seen) {
                shown[item.id] = true;
            }
        }
        return { details: {}, loading: {}, failed: {}, expanded, shown };
    }

    get layout() {
        return conversationLayout(conversationItems(this.props.detail, this.props.thread), {
            expanded: Object.keys(this.state.expanded).map(Number),
            shown: Object.keys(this.state.shown).map(Number),
        });
    }

    get oursTitle() {
        return _t("Our message");
    }

    get collapseTitle() {
        return _t("Collapse");
    }

    moreLabel(count) {
        return moreLabel(count);
    }

    senderName(emailFrom) {
        return senderName(emailFrom);
    }

    formatDate(value) {
        return formatMessageDate(value);
    }

    snippet(item) {
        const loaded = this.state.details[item.id];
        return collapsedSnippet(
            loaded && loaded.preview ? { ...item, preview: loaded.preview } : item,
            this.props.detail.subject
        );
    }

    /** Письмо для карточки: открытое — из корня, прочие — загруженные тут. */
    cardDetail(item) {
        return item.id === this.props.detail.id ? this.props.detail : this.state.details[item.id];
    }

    expand(item) {
        this.state.expanded[item.id] = true;
        if (!this.cardDetail(item)) {
            this.load(item.id);
        }
    }

    /**
     * Свёрнутое письмо остаётся строкой на своём месте. Иначе письмо из
     * середины длинной переписки (его было видно лишь потому, что оно
     * развёрнуто, — например, письмо строки, по которой щёлкнули)
     * проваливалось в соседнее «ещё N»: пропадало с экрана, а счётчик «ещё»
     * скачком рос (разбор шага 20).
     */
    collapse(item) {
        delete this.state.expanded[item.id];
        this.state.shown[item.id] = true;
    }

    reveal(ids) {
        for (const id of ids) {
            this.state.shown[id] = true;
        }
    }

    reply(mode, item) {
        return this.props.onReply(mode, item.id);
    }

    /**
     * Тело письма — один запрос на письмо. Ошибку показываем в карточке, а
     * не окном: письмо, которое просто развернули, не повод прерывать
     * чтение переписки.
     *
     * Ответ «тело не пришло» (body_state 'failed': почтовый сервер отказал,
     * лишнее подключение и т. п.) — такая же неудача, с «Повторить»: в
     * кэш его не кладём, иначе повтора не было бы вовсе, а разворот брал бы
     * тот же неудачный ответ. Письмо с пришедшим телом, если оно всё ещё
     * развёрнуто, — показано: props.onShown (отметка «прочитано» — дело
     * pmk_mail_ui, см. выше).
     */
    async load(messageId) {
        if (this.state.loading[messageId]) {
            return;
        }
        const epoch = this.epoch;
        this.state.loading[messageId] = true;
        delete this.state.failed[messageId];
        let shown = false;
        try {
            const detail = await this.orm.call(
                "mail.client.message",
                "get_message_detail",
                [messageId]
            );
            if (epoch === this.epoch) {
                if (detail.body_state === "failed") {
                    this.state.failed[messageId] = true;
                } else {
                    this.state.details[messageId] = detail;
                    shown = Boolean(this.state.expanded[messageId]);
                }
            }
        } catch {
            if (epoch === this.epoch) {
                this.state.failed[messageId] = true;
            }
        } finally {
            if (epoch === this.epoch) {
                delete this.state.loading[messageId];
            }
        }
        if (shown && this.props.onShown) {
            await this.props.onShown(messageId);
        }
    }

    async allowImages(item) {
        if (item.id === this.props.detail.id) {
            return this.props.onAllowImages();
        }
        const epoch = this.epoch;
        const detail = await this.orm.call("mail.client.message", "allow_images", [item.id]);
        if (epoch === this.epoch) {
            this.state.details[item.id] = detail;
        }
    }
}
