import { Component, useEffect, useRef, useState } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";

import { formatMessageDate, formatSize, splitAddress } from "../utils";
import { AttachmentPreviewDialog } from "../attachments/attachment_preview_dialog";
import { followFrame } from "./frame_fit";

/**
 * ПРАВКА ПМК: форма числа писем по правилам языка («14 писем», «2 письма»,
 * «1 письмо»). В _t форм множественного числа нет, а по-русски их три,
 * поэтому форму выбирает Intl.PluralRules, и у каждой формы своя строка
 * перевода. Английский форму «few» не выбирает никогда. Строки перевода
 * пишем в _t целиком, а не собираем: сборщик перевода берёт только их.
 */
function pluralForm(count) {
    try {
        // user.lang уже в виде браузера («ru-RU»), не Odoo («ru_RU»).
        return new Intl.PluralRules(user.lang || "en").select(count);
    } catch {
        return "other"; // неизвестный браузеру язык — английские формы
    }
}

function threadCountLabel(count) {
    const form = pluralForm(count);
    if (form === "one") {
        return _t("%s message in thread", count);
    }
    if (form === "few") {
        return _t("%s messages in thread (2-4)", count);
    }
    return _t("%s messages in thread", count);
}

// Заголовок блока переписки под строкой «От»: остальные письма, без открытого.
function otherInThreadLabel(count) {
    const form = pluralForm(count);
    if (form === "one") {
        return _t("%s other message in this conversation", count);
    }
    if (form === "few") {
        return _t("%s other messages in this conversation (2-4)", count);
    }
    return _t("%s other messages in this conversation", count);
}

export class ReadingPane extends Component {
    static template = "mail_client.ReadingPane";
    static components = { Dropdown, DropdownItem };
    static props = {
        detail: { optional: true },
        loading: { type: Boolean },
        moveTargets: { type: Array, optional: true },
        // False on a read-only mailbox, where the server refuses move and
        // delete rather than dropping mail from Odoo that is still on IMAP.
        canAct: { type: Boolean, optional: true },
        thread: { type: Array, optional: true },
        contact: { optional: true },
        onSelectMessage: { type: Function },
        onDownloadEml: { type: Function },
        onAllowImages: { type: Function },
        onToggleSeen: { type: Function },
        onToggleFlagged: { type: Function },
        onMove: { type: Function },
        onDelete: { type: Function },
        onReply: { type: Function },
        onDownloadAttachment: { type: Function },
    };

    setup() {
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.state = useState({
            downloading: null,
            showContact: false,
            // ПРАВКА ПМК: «Кому» и «Копия» раскрыты у этого письма. Храним id,
            // а не флажок: следующее письмо открывается снова свёрнутым.
            recipientsFor: null,
        });

        // ПРАВКА ПМК (шаг 17): одна прокрутка у окна чтения, рамка — ростом
        // с письмо (frame_fit.js).
        this.scrollerRef = useRef("scroller");
        this.frameRef = useRef("frame");
        // Другое письмо на экране — читаем его с начала. Окно прокрутки то же
        // самое (прежнее письмо на время загрузки не убирается), поэтому само
        // оно наверх не вернётся.
        useEffect(
            () => {
                if (this.scrollerRef.el) {
                    this.scrollerRef.el.scrollTop = 0;
                }
            },
            () => [this.props.detail?.id]
        );
        // Сменился текст в рамке (другое письмо, «Показать картинки») —
        // подогнать рамку под новый документ, как только он разобран, не
        // дожидаясь картинок. Элемент рамки тот же, меняется только srcdoc.
        // Без доступа к документу рамки (нет allow-same-origin) — прежнее
        // поведение: рамка на всю оставшуюся высоту с прокруткой внутри.
        useEffect(
            () => {
                const frame = this.frameRef.el;
                if (!frame) {
                    return;
                }
                return followFrame(frame, { getScroller: () => this.scrollerRef.el });
            },
            () => [this.props.detail?.body]
        );
    }

    /**
     * Пока грузится следующее письмо, на экране прежнее — бледное и
     * недоступное (inert): ни щелчком, ни с клавиатуры. Кнопки действуют на
     * выделенную строку, а она уже другая: Tab до флажка и пробел отметили
     * бы новое письмо, «Удалить» из «⋯» удалило бы его.
     */
    get stale() {
        return Boolean(this.props.loading && this.props.detail);
    }

    // ПРАВКА ПМК: см. комментарий в mail_client_action.js.
    get seenTitle() {
        return this.props.detail?.flag_seen ? _t("Mark as unread") : _t("Mark as read");
    }

    // ПРАВКА ПМК: подписи для строки над письмом и меню «⋯».
    get contactTitle() {
        return this.state.showContact ? _t("Hide contact") : _t("Show contact");
    }

    /** Писем в переписке, считая открытое; 0 — не показывать. */
    get threadCount() {
        const count = this.props.thread ? this.props.thread.length : 0;
        return count > 1 ? count : 0;
    }

    get threadCountLabel() {
        return threadCountLabel(this.threadCount);
    }

    get threadCountTitle() {
        return _t("%s messages", this.threadCount);
    }

    /** «От» одной строкой: имя и адрес отдельно, чтобы имя выделить. */
    get sender() {
        return splitAddress(this.props.detail?.email_from);
    }

    get hasRecipients() {
        return Boolean(this.props.detail?.email_to || this.props.detail?.email_cc);
    }

    get showRecipients() {
        return Boolean(this.props.detail) && this.state.recipientsFor === this.props.detail.id;
    }

    get recipientsToggleLabel() {
        return this.showRecipients ? _t("hide details") : _t("details");
    }

    toggleRecipients() {
        this.state.recipientsFor = this.showRecipients ? null : this.props.detail.id;
    }

    toggleContact() {
        this.state.showContact = !this.state.showContact;
        // Карточка встаёт над письмом — показать её, даже если письмо уже
        // прокручено вниз.
        if (this.state.showContact && this.scrollerRef.el) {
            this.scrollerRef.el.scrollTop = 0;
        }
    }

    /**
     * Колесо над закреплённой строкой крутит письмо: прокрутка у окна чтения
     * одна, «где бы ни стоял курсор». Сама строка крутится только вбок (на
     * узком окне), поэтому отдаём ей горизонтальное колесо и Ctrl+колесо
     * (масштаб страницы).
     */
    onToolbarWheel(ev) {
        const scroller = this.scrollerRef.el;
        if (!scroller || ev.ctrlKey || Math.abs(ev.deltaY) <= Math.abs(ev.deltaX)) {
            return;
        }
        const unit = ev.deltaMode === 1 ? 16 : ev.deltaMode === 2 ? scroller.clientHeight : 1;
        scroller.scrollTop += ev.deltaY * unit;
    }

    /** Other messages in this conversation, current one excluded. */
    get otherInThread() {
        if (!this.props.thread || !this.props.detail) {
            return [];
        }
        return this.props.thread.filter((message) => message.id !== this.props.detail.id);
    }

    // ПРАВКА ПМК: «ещё 2 письма в переписке», а не «2 писем» — число и
    // форма слова рядом с «3 письма» в закреплённой строке.
    get otherInThreadLabel() {
        return otherInThreadLabel(this.otherInThread.length);
    }

    formatDate(value) {
        return formatMessageDate(value);
    }

    formatSize(bytes) {
        return formatSize(bytes);
    }

    /**
     * The body is rendered inside a sandboxed iframe without allow-scripts:
     * no script of the message ever runs. Popups stay allowed so that
     * target="_blank" links still open.
     *
     * ПРАВКА ПМК (шаг 17, решение владельца 29.09.2026): добавлен
     * allow-same-origin — без него окно почты не может прочитать высоту
     * письма (frame_fit.js), а без высоты нет одной прокрутки на всё письмо.
     * allow-scripts НЕ добавлять никогда: вместе с allow-same-origin он
     * снимает песочницу целиком, и скрипт письма получил бы нашу сессию.
     * Цена allow-same-origin: запросы из письма к нашему серверу идут с
     * сессией. Их глушит pmk_mail_ui (tools/remote_paths.py, Г13) — всегда,
     * и после «Показать картинки»; ссылки javascript: снимает frame_fit.js.
     */
    get sandbox() {
        return "allow-same-origin allow-popups allow-popups-to-escape-sandbox";
    }

    async onDownload(attachment) {
        this.state.downloading = attachment.id;
        try {
            const result = await this.props.onDownloadAttachment(attachment.id);
            if (result && result.url) {
                // Fetched on demand, so the URL only exists after this call.
                window.open(result.url, "_blank");
            }
        } finally {
            this.state.downloading = null;
        }
    }

    /**
     * ПРАВКА ПМК: показать вложение, не скачивая его.
     *
     * Окно заводится прямо отсюда, а не через корень почты: просмотр не часть
     * состояния почты и живёт ровно столько, сколько открыт диалог. Кнопка
     * скачивания рядом осталась нетронутой — файл всё равно иногда нужен на
     * диске, и тогда его берут в один клик, как раньше.
     */
    onPreview(attachment) {
        this.dialog.add(AttachmentPreviewDialog, {
            attachmentId: attachment.id,
            name: attachment.name,
            // Скачивание из окна идёт тем же путём, что и по кнопке в письме:
            // колесо на кнопке и разбор отказа остаются в одном месте.
            onDownload: () => this.onDownload(attachment),
        });
    }

    onMoveTo(folderId) {
        this.props.onMove(folderId);
    }
}
