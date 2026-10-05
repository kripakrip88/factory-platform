/* ПМК: окно чертежа DXF для ленты документа и лазера (шаг 46).
 *
 * Окно само просит чертёж у сервера (pmk.drawing.attachment_preview) и
 * открывается сразу — с колесом, пока сервер рисует: большой чертёж
 * готовится секунды, и человек должен видеть, что кнопка нажалась.
 *
 * Здесь же — две регистрации:
 *   • реестр pmk_file_viewers, ключ "dxf" — само окно чертежа (DxfViewer)
 *     для почты: vendor/mail_client берёт его оттуда, не импортируя наш
 *     модуль (без pmk_drawing почта ставится и работает);
 *   • клиентское действие pmk_drawing.view — кнопка «Посмотреть» у детали
 *     задания лазеру (pmk_laser, action_view_drawing): открывает окно поверх
 *     формы и никуда не уводит.
 */
import { Component, markRaw, onWillDestroy, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { ConnectionLostError, RPCError } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

import { DxfViewer } from "./dxf_viewer";

// Нет связи: пропал Wi-Fi на планшете в цеху, Odoo перезапускается при
// выкладке, nginx не дождался ответа (504). У такой ошибки нет слов сервера,
// а её собственный текст английский («Connection to … interrupted»).
export const NO_CONNECTION =
    "Нет связи с сервером — чертёж не получен. Попробуйте открыть его ещё раз.";
const NOT_RECEIVED = "Чертёж не удалось получить с сервера. Попробуйте открыть его ещё раз.";

/**
 * Ошибка запроса -> слова в окне. Слова сервера (UserError, AccessError —
 * по-русски) — как есть; обрыв связи — своей фразой; всё прочее —
 * общей русской, а не текстом исключения браузера.
 */
export function requestErrorText(error) {
    if (error instanceof RPCError && error.data && error.data.message) {
        return String(error.data.message);
    }
    if (error instanceof ConnectionLostError) {
        return NO_CONNECTION;
    }
    return NOT_RECEIVED;
}

function russianBytes(bytes) {
    const value = Number(bytes) || 0;
    if (value <= 0) {
        return "";
    }
    const units = ["Б", "КБ", "МБ", "ГБ"];
    let size = value;
    let unit = 0;
    while (size >= 1024 && unit < units.length - 1) {
        size /= 1024;
        unit++;
    }
    return `${unit ? size.toFixed(1).replace(".", ",") : size} ${units[unit]}`;
}

function ownUrl(value) {
    const raw = value ? String(value) : "";
    return raw.startsWith("/") && !raw.startsWith("//") ? raw : "";
}

export class DxfViewerDialog extends Component {
    static template = "pmk_drawing.DxfViewerDialog";
    static components = { Dialog, DxfViewer };
    static props = {
        // ir.attachment, а не запись-владелец: права проверит сервер по
        // вложению (документ-владелец и поле).
        attachmentId: { type: Number },
        name: { type: String, optional: true },
        // Своя ссылка «Скачать» (у детали лазера — по полю, с именем файла).
        downloadUrl: { type: String, optional: true },
        close: { type: Function, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ loading: true, error: "", ready: false });
        // Ответ — в обычном поле: в нём до 150 000 путей.
        this.payload = null;
        this.alive = true;
        onWillDestroy(() => {
            this.alive = false;
        });
        this.load();
    }

    async load() {
        try {
            const payload = await this.orm.call("pmk.drawing", "attachment_preview", [
                this.props.attachmentId,
            ]);
            if (!this.alive) {
                return;
            }
            this.payload = markRaw(payload || {});
            this.state.ready = true;
        } catch (error) {
            if (!this.alive) {
                return;
            }
            this.state.error = requestErrorText(error);
        } finally {
            if (this.alive) {
                this.state.loading = false;
            }
        }
    }

    get title() {
        return String(this.props.name || (this.payload && this.payload.name) || "Чертёж DXF");
    }

    /** «чертёж DXF · 1,2 МБ · 3455 × 1581 мм» — как подпись окна почты. */
    get subtitle() {
        const parts = ["чертёж DXF"];
        const size = russianBytes(this.payload && this.payload.file_size);
        if (size) {
            parts.push(size);
        }
        return parts.join(" · ");
    }

    get downloadUrl() {
        return (
            ownUrl(this.props.downloadUrl) ||
            ownUrl(this.payload && this.payload.download_url) ||
            `/web/content/${this.props.attachmentId}?download=true`
        );
    }

    get failed() {
        return !this.state.loading && (this.state.error || !(this.payload && this.payload.ok));
    }

    get reason() {
        return (
            this.state.error ||
            (this.payload && this.payload.reason) ||
            "Чертёж не удалось показать."
        );
    }

    onClose() {
        if (this.props.close) {
            this.props.close();
        }
    }
}

registry.category("pmk_file_viewers").add("dxf", DxfViewer);

/**
 * «Посмотреть» у детали задания лазеру: сервер вернул действие с номером
 * вложения поля «Чертёж» (pmk_laser, action_view_drawing). Окно — поверх
 * формы; действие ничего не возвращает, и форма остаётся на месте.
 */
export function openDxfViewerAction(env, action) {
    const params = (action && action.params) || {};
    const attachmentId = Number(params.attachment_id);
    if (!Number.isInteger(attachmentId) || attachmentId <= 0) {
        return;
    }
    env.services.dialog.add(DxfViewerDialog, {
        attachmentId,
        name: params.name ? String(params.name) : "",
        downloadUrl: params.download_url ? String(params.download_url) : "",
    });
}

registry.category("actions").add("pmk_drawing.view", openDxfViewerAction);
