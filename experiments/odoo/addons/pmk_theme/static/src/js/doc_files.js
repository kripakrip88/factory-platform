/** @odoo-module **/
/**
 * Файлы документа — разбор UX, шаг 65 (11.10.2026).
 *
 * Антон 11.10: «файлы — можно перенести в вкладку, где стоит Заметки и
 * Связи (добавить счётчик, чтобы сигнализировать, что там что-то есть)».
 * Раньше вложения жили скрепкой в ленте под формой; лента ушла в окно
 * «История» (js/doc_tools.js) — файлы получают своё место:
 *   • у форм с вкладками — вкладка «Файлы» последней. Её ставит сервер для
 *     всех форм с лентой разом (models/doc_history.py, Base._get_view):
 *     <page name="pmk_files"><widget name="pmk_files"/></page> — XML форм
 *     не меняется. В ярлыке — число файлов (0 не рисуем);
 *   • у форм без вкладок (вентзонты, доборка, «Заказ в работе») — скрепка с
 *     числом в строке пути рядом с «Историей», щелчок — окно «Файлы».
 * Внутри — штатный список вложений mail (AttachmentList: просмотр, в т.ч.
 * DXF из pmk_drawing, скачивание, удаление со своим подтверждением),
 * «Добавить файл» и перетаскивание. Данные — те же вложения документа
 * (ir.attachment по res_model/res_id), что показывала скрепка ленты: через
 * хранилище почты (mail.store), поэтому числа на скрепке, во вкладке и в
 * «Истории» обновляются сами после загрузки и удаления.
 *
 * Доводка шага 65 (находки проверки):
 *   • список и число — свежие при каждом открытии документа, вкладки и окна
 *     (ensureAttachments(…, { fresh: true })): нить в mail.store живёт всю
 *     сессию, без этого файл, пришедший письмом после первого просмотра, не
 *     был виден до перезагрузки страницы;
 *   • у счёта (reload_on_attachment) после файла документ сначала
 *     сохраняется, потом перечитывается (saveThenLoad) — как лента;
 *   • число в ярлыке берёт запись из слота вкладки — работает и в окне
 *     строки, где env.model нет.
 *
 * ⚠️ ВНУТРЕННОСТИ mail: useAttachmentUploader, AttachmentList,
 * MailAttachmentDropzone, Thread.fetchThreadData(["attachments"]), поля
 * thread.attachments / areAttachmentsLoaded / isLoadingAttachments /
 * canPostMessage. Сверяет tests/test_step65_history.py — перепроверять при
 * обновлении Odoo.
 */
import { Component, onWillUpdateProps, useRef, useState, useEffect } from "@odoo/owl";
import { AttachmentList } from "@mail/core/common/attachment_list";
import { useAttachmentUploader } from "@mail/core/common/attachment_uploader_hook";
import { MailAttachmentDropzone } from "@mail/core/common/mail_attachment_dropzone";
import { isDragSourceExternalFile } from "@mail/utils/common/misc";
import { Dialog } from "@web/core/dialog/dialog";
import { useCustomDropzone } from "@web/core/dropzone/dropzone_hook";
import { Notebook } from "@web/core/notebook/notebook";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { FileUploader } from "@web/views/fields/file_handler";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { FILES_PAGE, countLabel, dialogTitle, shouldFetchAttachments } from "@pmk_theme/js/doc_tools_rules";

/** Нить документа в хранилище почты; у несохранённой записи — нет. */
export function threadOf(store, resModel, resId) {
    if (!store || !resModel || !resId) {
        return null;
    }
    return store.Thread.insert({ model: resModel, id: resId });
}

/**
 * Спросить вложения у сервера (правило — shouldFetchAttachments). fresh —
 * первый показ документа: перечитать, даже если нить уже грузилась раньше в
 * этой вкладке браузера, иначе число и список устаревают до перезагрузки
 * страницы. Вкладка, ярлык, скрепка и «История» открываются разом — запрос
 * один на всех (флаг isLoadingAttachments ставится сразу, до ответа:
 * mail chatter/web/thread_model_patch.js).
 */
export function ensureAttachments(thread, { fresh = false } = {}) {
    if (shouldFetchAttachments(thread, { fresh })) {
        thread.fetchThreadData(["attachments"]);
    }
}

/**
 * reload_on_attachment у <chatter> (счёт — account.move): после загрузки и
 * удаления файла документ перечитывается. Как reloadParentView ленты (mail
 * chatter_patch.js): СНАЧАЛА сохранить, потом перечитать — иначе load()
 * молча сбросит несохранённые правки шапки. Не сохранилось (ошибка
 * проверки) — не перечитываем: правки остаются на экране.
 *   save — сохранение формы (FormController.save), без него — record.save().
 */
export async function saveThenLoad(record, save) {
    if (!record) {
        return false;
    }
    const saved = save ? await save() : await record.save();
    if (!saved) {
        return false;
    }
    await record.load();
    return true;
}

/** Список файлов с загрузкой — и во вкладке, и в окне скрепки. */
export class PmkFiles extends Component {
    static template = "pmk_theme.Files";
    static components = { AttachmentList, FileUploader };
    static props = {
        resModel: { type: String, optional: true },
        resId: { optional: true },
        // reload_on_attachment у <chatter>: после загрузки и удаления
        // перечитать документ (так делала лента).
        reloadRecord: { type: Function, optional: true },
    };

    setup() {
        // Хранилище — без useService: промисы его методов не должны зависеть
        // от жизни компонента (грабля шага 31).
        this.store = this.env.services["mail.store"];
        this.rootRef = useRef("root");
        this.state = useState({ thread: threadOf(this.store, this.props.resModel, this.props.resId) });
        this.uploader = useAttachmentUploader(this.state.thread);
        onWillUpdateProps((next) => {
            if (next.resModel !== this.props.resModel || next.resId !== this.props.resId) {
                this.state.thread = threadOf(this.store, next.resModel, next.resId);
                this.uploader.thread = this.state.thread;
            }
        });
        // Открыли вкладку или окно — список свежий (fresh).
        useEffect(
            (thread) => ensureAttachments(thread, { fresh: true }),
            () => [this.state.thread]
        );
        useCustomDropzone(
            this.rootRef,
            MailAttachmentDropzone,
            {
                extraClass: "o_pmk_files_dropzone",
                onDrop: (ev) => this.onDrop(ev),
            },
            () => Boolean(this.state.thread?.canPostMessage)
        );
    }

    get thread() {
        return this.state.thread;
    }

    get attachments() {
        return this.state.thread?.attachments ?? [];
    }

    get loading() {
        const thread = this.state.thread;
        return Boolean(thread && !thread.areAttachmentsLoaded);
    }

    get canUpload() {
        return Boolean(this.state.thread?.canPostMessage);
    }

    async afterChange() {
        if (this.props.reloadRecord) {
            await this.props.reloadRecord();
        }
    }

    /** Кнопка «Добавить файл» (FileUploader отдаёт файлы по одному). */
    async onUploaded(data) {
        const thread = this.state.thread;
        if (!thread) {
            return;
        }
        await this.uploader.uploadData(data, { thread });
        await this.afterChange();
    }

    async onDrop(ev) {
        const thread = this.state.thread;
        if (!thread || !isDragSourceExternalFile(ev.dataTransfer)) {
            return;
        }
        const files = [...ev.dataTransfer.files];
        await Promise.all(files.map((file) => this.uploader.uploadFile(file, { thread })));
        await this.afterChange();
    }

    async unlink(attachment) {
        await this.uploader.unlink(attachment);
        await this.afterChange();
    }
}

/** Вкладка «Файлы»: <widget name="pmk_files"/> (models/doc_history.py). */
export class PmkFilesWidget extends Component {
    static template = "pmk_theme.FilesWidget";
    static components = { PmkFiles };
    static props = { ...standardWidgetProps };

    get reloadRecord() {
        const attrs = this.env.pmkChatterAttrs;
        if (!attrs?.reloadOnAttachment) {
            return undefined;
        }
        // Сохранение формы основного окна (doc_tools.js, useSubEnv); у формы
        // с лентой под листом его нет — record.save().
        const save = this.env.pmkSaveRecord || undefined;
        return () => saveThenLoad(this.props.record, save);
    }
}

registry.category("view_widgets").add(FILES_PAGE, { component: PmkFilesWidget });

/** Окно «Файлы» — скрепка у форм без вкладок. */
export class PmkFilesDialog extends Component {
    static template = "pmk_theme.FilesDialog";
    static components = { Dialog, PmkFiles };
    static props = {
        close: Function,
        name: { type: String, optional: true },
        resModel: String,
        resId: Number,
        reloadRecord: { type: Function, optional: true },
    };

    get title() {
        return dialogTitle("Файлы", this.props.name);
    }
}

/** Число в ярлыке вкладки «Файлы». */
export class PmkFilesCount extends Component {
    static template = "pmk_theme.FilesCount";
    static props = {
        resModel: { type: String, optional: true },
        resId: { optional: true },
    };

    setup() {
        this.store = this.env.services["mail.store"];
        this.state = useState({ thread: threadOf(this.store, this.props.resModel, this.props.resId) });
        onWillUpdateProps((next) => {
            if (next.resModel !== this.props.resModel || next.resId !== this.props.resId) {
                this.state.thread = threadOf(this.store, next.resModel, next.resId);
            }
        });
        // Ярлык рисуется при открытии документа — число свежее (fresh).
        useEffect(
            (thread) => ensureAttachments(thread, { fresh: true }),
            () => [this.state.thread]
        );
    }

    get count() {
        return this.state.thread?.attachments?.length || 0;
    }

    get label() {
        return countLabel(this.count);
    }
}

// Ярлык вкладки рисует web.Notebook (и его копия у счетов —
// account.AccountMoveFormNotebook, наследник класса): компонент числа —
// геттером на прототипе, шаблон — xml/doc_tools.xml.
patch(Notebook.prototype, {
    get pmkFilesCountCls() {
        return this.env.services?.["mail.store"] ? PmkFilesCount : null;
    },

    /**
     * Запись, чьи файлы считаем. Слот вкладки «Файлы» несёт запись своей
     * формы (параметр pmk_record — doc_tools.js, патч FormCompiler): у окна
     * строки (X2ManyFieldDialog) env.model нет, и без него число пропало бы.
     * Запасной путь — корневая запись формы.
     */
    pmkFilesRecord(navItem) {
        return navItem?.[1]?.pmk_record || this.env.model?.root || null;
    },
});
