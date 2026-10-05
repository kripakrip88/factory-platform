/* ПМК: вложение .dxf в ленте документа — окно чертежа (шаг 46).
 *
 * Штатный просмотрщик Odoo (useFileViewer) умеет pdf, картинки, видео и
 * текст. DXF для него «не просматривается»: щелчок по карточке чертежа в
 * ленте расчёта или задания лазеру не делал НИЧЕГО, а файл, который браузер
 * прислал как text/plain, открывался сырым текстом группа за группой.
 * Теперь щелчок по DXF открывает наше окно чертежа; остальные вложения —
 * как было (super).
 *
 * В разметке ядра (mail.AttachmentList) щелчок по карточке ловят ДВА
 * обработчика — сама карточка и её верхняя половина внутри, событие
 * всплывает через обе. Для штатного просмотрщика это безвредно (он один на
 * список), а окон диалога открылось бы два. Поэтому — флаг «окно уже
 * открыто», который снимается при закрытии окна.
 *
 * Чтобы карточка чертежа ВЫГЛЯДЕЛА открываемой (курсор-лупа, как у картинок
 * и PDF, и подсказка «посмотреть чертёж»), шаблон ленты помечает её
 * data-pmk-dxf (xml/attachment_list.xml, стиль — scss/dxf_viewer.scss).
 * Штатный признак isViewable не трогаем: с ним DXF попал бы в карусель
 * штатного просмотрщика, который его не умеет.
 */
import { AttachmentList } from "@mail/core/common/attachment_list";
import { patch } from "@web/core/utils/patch";

import { DxfViewerDialog } from "./dxf_dialog";
import { isDxfFile } from "./dxf_view_math";

patch(AttachmentList.prototype, {
    /** Карточка — чертёж DXF, который откроется нашим окном. */
    pmkIsDxf(attachment) {
        return Boolean(
            attachment &&
                !attachment.uploading &&
                attachment.type !== "url" &&
                Number.isInteger(attachment.id) &&
                attachment.id > 0 &&
                isDxfFile(attachment.name, attachment.mimetype)
        );
    },

    onClickAttachment(attachment) {
        if (this.pmkIsDxf(attachment)) {
            if (this.pmkDxfOpen) {
                return;
            }
            this.pmkDxfOpen = true;
            this.dialog.add(
                DxfViewerDialog,
                {
                    attachmentId: attachment.id,
                    name: attachment.name || "",
                    downloadUrl: attachment.downloadUrl || "",
                },
                {
                    onClose: () => {
                        this.pmkDxfOpen = false;
                    },
                }
            );
            return;
        }
        return super.onClickAttachment(...arguments);
    },
});
