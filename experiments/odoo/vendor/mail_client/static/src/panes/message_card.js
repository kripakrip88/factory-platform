import { Component, useEffect, useRef, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

import { formatMessageDate, formatSize, splitAddress } from "../utils";
import { AttachmentPreviewDialog } from "../attachments/attachment_preview_dialog";
import { followFrame } from "./frame_fit";

/**
 * ПРАВКА ПМК (шаг 20 плана, 30.09.2026): одно письмо — строка «От»,
 * предупреждения, вложения и рамка с текстом.
 *
 * Вынесено из окна чтения шага 17 без видимых изменений: одиночное письмо
 * (без переписки) ReadingPane показывает этой карточкой, и разметка у него
 * та же, что была, — блоки лежат прямо в окне прокрутки (у шаблона
 * несколько корней, обёртки нет), поэтому правила pmk_theme вида
 * «.o_mail_client_reading_scroll > .px-4» и растяжка короткого письма до
 * низа окна действуют как раньше. Карточку контакта окно чтения ставит
 * слотом afterHeader — туда же, где она стояла.
 *
 * В переписке (panes/conversation.js) развёрнутое письмо — та же карточка,
 * а в строке «От» ещё плашка «мы» (ours), маленькие «Ответить» и
 * «Переслать» (onReply) и сворачивание (onCollapse). У каждой карточки
 * своя рамка и своя подгонка высоты (frame_fit.js): рамок в окне теперь
 * несколько, и каждая следит за своим письмом и останавливается, когда
 * карточку сворачивают.
 */
export class MessageCard extends Component {
    static template = "mail_client.MessageCard";
    static props = {
        detail: { type: Object },
        // Окно прокрутки, чью прокрутку frame_fit.js бережёт при мерке.
        getScroller: { type: Function },
        onAllowImages: { type: Function },
        onDownloadAttachment: { type: Function },
        // Только в переписке:
        ours: { type: Boolean, optional: true },
        onReply: { type: Function, optional: true },
        // «Ответить» на нашем письме ушло бы нам же (Г3) — до шага 21 скрыто.
        canReply: { type: Boolean, optional: true },
        onCollapse: { type: Function, optional: true },
        slots: { type: Object, optional: true },
    };

    setup() {
        this.dialog = useService("dialog");
        this.state = useState({
            downloading: null,
            // «Кому» и «Копия» раскрыты у этого письма. Храним id, а не
            // флажок: следующее письмо открывается снова свёрнутым (у
            // одиночного письма карточка одна на все письма).
            recipientsFor: null,
        });
        this.frameRef = useRef("frame");
        // Сменился текст в рамке (другое письмо, «Показать картинки») —
        // подогнать рамку под новый документ, как только он разобран, не
        // дожидаясь картинок. Без доступа к документу рамки (нет
        // allow-same-origin) — прежнее поведение из CSS.
        useEffect(
            () => {
                const frame = this.frameRef.el;
                if (!frame) {
                    return;
                }
                return followFrame(frame, { getScroller: () => this.props.getScroller() });
            },
            () => [this.props.detail.body]
        );
    }

    /** «От» одной строкой: имя и адрес отдельно, чтобы имя выделить. */
    get sender() {
        return splitAddress(this.props.detail.email_from);
    }

    get hasRecipients() {
        return Boolean(this.props.detail.email_to || this.props.detail.email_cc);
    }

    get showRecipients() {
        return this.state.recipientsFor === this.props.detail.id;
    }

    get recipientsToggleLabel() {
        return this.showRecipients ? _t("hide details") : _t("details");
    }

    get oursTitle() {
        return _t("Our message");
    }

    get collapseTitle() {
        return _t("Collapse");
    }

    toggleRecipients() {
        this.state.recipientsFor = this.showRecipients ? null : this.props.detail.id;
    }

    /**
     * Щелчок по пустому месту строки «От» сворачивает письмо в переписке.
     * Кнопки и ссылки в строке делают своё.
     */
    onHeaderClick(ev) {
        if (!this.props.onCollapse || ev.target.closest("button, a, input, label")) {
            return;
        }
        // Мышью выделяли адрес или дату, чтобы скопировать, — не сворачивать.
        const selection = window.getSelection ? window.getSelection() : null;
        if (selection && !selection.isCollapsed) {
            return;
        }
        this.props.onCollapse();
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
}
