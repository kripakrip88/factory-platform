/* ПМК: окно просмотра вложения — чтобы файл из письма не приходилось скачивать.
 *
 * Почему модальное окно, а не четвёртая колонка: почта и так три колонки
 * (папки / список / письмо), и на панели чтения шириной около тысячи точек
 * места под таблицу прайса нет вовсе. Окно поверх письма даёт всю ширину
 * экрана и закрывается по Esc.
 *
 * Почему окно само ходит на сервер, хотя остальные панели модуля только
 * показывают то, что им дали сверху: просмотр — не часть состояния почты.
 * Его не надо восстанавливать после обновления списка, он живёт ровно столько,
 * сколько открыто окно, и тянуть его через корень значило бы добавить в корень
 * поле, которое никто, кроме этого окна, не читает.
 *
 * ПРАВКА ПМК (шаг 45, 05.10.2026): архив ZIP — список файлов внутри. Файл
 * из архива открывается ВТОРЫМ таким же окном поверх списка (props.member):
 * Esc и «Закрыть» возвращают к списку, а не к письму. Окно файла ходит на
 * сервер тем же preview() с аргументом member — таблица, «Показать ещё»,
 * сводка прайса, pdf.js и картинка работают как у обычного вложения.
 * «Скачать» у строки списка — запросом с разбором ответа, а не ссылкой: порча
 * файла выясняется только при распаковке, и причина отказа должна встать в
 * строку, а не пропасть в «Сбой» панели загрузок браузера.
 *
 * ПРАВКА ПМК (шаг 46, 06.10.2026): чертёж DXF (вложение и файл из архива) —
 * окном чертежа нашего модуля pmk_drawing: масштаб, сдвиг, слои. Окно
 * берётся из реестра pmk_file_viewers (ключ "dxf"), а не импортом: почта
 * ставится и работает без pmk_drawing, тогда DXF — «скачайте».
 */
import { Component, markRaw, onWillDestroy, useEffect, useRef, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { downloadFile } from "@web/core/network/download";
import { hidePDFJSButtons } from "@web/core/utils/pdfjs";
import { url } from "@web/core/utils/urls";

import {
    KINDS,
    appendSheetRows,
    downloadRefusal,
    formatBytes,
    memberUrl,
    normalizePreview,
    normalizePrice,
} from "./preview_payload";

// Значок строки архива по её виду (ПРАВКА ПМК, шаг 45).
const ENTRY_ICONS = {
    pdf: "fa-file-pdf-o",
    sheet: "fa-file-excel-o",
    image: "fa-file-image-o",
    // ПРАВКА ПМК (шаг 46): чертёж DXF — значком «Разобрать чертежи» лазера.
    drawing: "fa-object-ungroup",
    archive: "fa-file-archive-o",
    other: "fa-file-o",
};

export class AttachmentPreviewDialog extends Component {
    static template = "mail_client.AttachmentPreviewDialog";
    static components = { Dialog };
    static props = {
        // Запись mail.client.attachment, а не ir.attachment: файл может ещё
        // лежать на почтовом сервере и не быть скачанным вовсе.
        attachmentId: { type: Number },
        name: { type: String, optional: true },
        // Скачивание остаётся за панелью чтения: там уже есть и колесо на
        // кнопке, и разбор ошибок. Второй такой же код здесь был бы лишним.
        onDownload: { type: Function, optional: true },
        // ПРАВКА ПМК (шаг 45): файл ИЗ архива — номер в архиве и путь;
        // archiveName — имя архива для подписи окна.
        member: {
            type: Object,
            optional: true,
            shape: { index: Number, path: String },
        },
        archiveName: { type: String, optional: true },
        // Кладёт служба диалогов.
        close: { type: Function, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.KINDS = KINDS;
        this.state = useState({
            loading: true,
            error: "",
            // Не null, а разобранный пустой ответ: тогда в разметке нет ни
            // одной проверки «а есть ли вообще ответ», и последняя ветка,
            // которая читает причину отказа, не может упасть на пустоте.
            preview: normalizePreview(null),
            // Вкладка — положение в МАССИВЕ листов, а не номер листа в книге:
            // пустые листы в показ не попадают. Номер листа для сервера берём
            // из самого листа (sheet.index).
            tab: 0,
            // Сводки прайса по НОМЕРУ ЛИСТА: у листа «Металл» она своя, у
            // листа «Сервис» своя. Считаются по мере перехода на вкладку.
            prices: {},
            scanningPrice: false,
            loadingMore: false,
            // «Скачать» у строк архива (ПРАВКА ПМК, шаг 45): по номеру файла в
            // архиве — идёт ли скачивание и почему не вышло.
            downloading: {},
            rowErrors: {},
        });
        this.pdfFrameRef = useRef("pdfFrame");

        // Запрос НЕ повешен на onWillStart намеренно. onWillStart задерживает
        // появление самого окна, и на десятимегабайтном вложении человек
        // несколько секунд смотрит на неизменившееся письмо и не понимает,
        // нажалась ли кнопка. Окно открывается сразу с колесом, ответ
        // приезжает в state и перерисовывает содержимое.
        this.alive = true;
        onWillDestroy(() => {
            this.alive = false;
        });
        this.load();

        // Прячем у просмотрщика pdf.js кнопки, которые в письме бессмысленны
        // («Открыть файл», правка). Делается ровно так же, как в штатном
        // виджете pdf_viewer ядра: стиль подкладывается в документ рамки
        // по её событию load.
        useEffect(
            (element) => {
                if (element) {
                    hidePDFJSButtons(element, {});
                }
            },
            () => [this.pdfFrameRef.el]
        );
    }

    async load() {
        try {
            const raw = await this.orm.call("mail.client.attachment", "preview", [], this.serverKwargs());
            if (!this.alive) {
                return;
            }
            const preview = normalizePreview(raw);
            if (preview.kind === KINDS.DRAWING) {
                // ПРАВКА ПМК (шаг 46): до 150 000 путей чертежа — мимо
                // реактивного состояния (следить за каждым незачем). Окна
                // чертежа нет (модуль на сервере есть, а его скрипт не
                // загрузился) — честный отказ, а не пустое окно.
                if (this.drawingViewer) {
                    preview.drawing = markRaw(preview.drawing);
                } else {
                    preview.kind = KINDS.NONE;
                    preview.drawing = null;
                    // prettier-ignore
                    preview.reason = _t("The drawing viewer is not loaded — download the file to open it on your computer.").toString();
                }
            }
            this.state.preview = preview;
            // Какой лист сервер уже разобрал — говорит он сам. Под нулём
            // сводку класть нельзя: пустые листы из показа выпадают, и первая
            // вкладка запросто окажется вторым листом книги.
            //
            // Запоминаем и пустой ответ: «этот лист на прайс не похож» — тоже
            // ответ, и спрашивать его второй раз при возврате на вкладку
            // значит гонять разбор файла заново ради того же «нет».
            const scanned = raw && raw.price ? raw.price.sheet : null;
            if (Number.isInteger(scanned)) {
                this.state.prices[scanned] = preview.price;
            }
        } catch (error) {
            // Окно уже закрыли — ругаться не на что и не перед кем.
            if (!this.alive) {
                return;
            }
            // Файл пришёл от постороннего, и отказ здесь — обычное дело:
            // битый архив, оборванная выборка IMAP, неизвестный формат.
            // Аварийное окно Odoo поверх почты пугает сильнее, чем строка
            // в самом просмотре, под которой осталась кнопка «Скачать».
            this.state.error =
                (error && error.data && error.data.message) ||
                (error && error.message) ||
                _t("The file could not be read.");
        } finally {
            if (this.alive) {
                this.state.loading = false;
            }
        }
    }

    /**
     * Аргументы вызова сервера: вложение и, у файла из архива, его номер.
     * Один помощник на preview, price_scan и «Показать ещё» — иначе одна
     * из трёх дорог забыла бы member и показала бы лист архива вместо листа
     * файла (ПРАВКА ПМК, шаг 45).
     */
    serverKwargs(extra = {}) {
        const kwargs = { attachment_id: this.props.attachmentId, ...extra };
        if (this.props.member) {
            kwargs.member = this.props.member.index;
        }
        return kwargs;
    }

    get preview() {
        return this.state.preview;
    }

    /**
     * Окно чертежа DXF из модуля pmk_drawing (ПРАВКА ПМК, шаг 46) или null.
     * Реестр, а не импорт: без pmk_drawing почта собирается и работает.
     */
    get drawingViewer() {
        return registry.category("pmk_file_viewers").get("dxf", null);
    }

    get dialogTitle() {
        // toString() обязателен: _t отдаёт не примитивную строку, а объект
        // отложенного перевода, а Dialog объявляет title как type: String —
        // в режиме разработчика проверка свойств на объекте падает.
        return (this.props.name || _t("Attachment")).toString();
    }

    /**
     * Подпись под заголовком: откуда файл, что это и сколько весит.
     *
     * ПРАВКА ПМК (шаг 45): вид файла — словами с сервера («таблица Excel»,
     * «архив ZIP»), а не «application/vnd.openxmlformats-…»; размер — «КБ»,
     * а не «KB»; у файла из архива — «из архива «Заказ.zip»».
     */
    get subtitle() {
        const parts = [];
        const archiveName = this.props.archiveName || (this.preview && this.preview.archiveName);
        if (this.props.member && archiveName) {
            parts.push(_t("from the archive «%s»", archiveName));
        }
        if (this.preview && (this.preview.formatTitle || this.preview.mimetype)) {
            parts.push(this.preview.formatTitle || this.preview.mimetype);
        }
        // Размер берём только у сервера. В списке вложений письма стоит
        // размер MIME-части, то есть base64: он на треть больше настоящего,
        // и показывать его рядом с открытым файлом — врать в мелочи.
        if (this.preview && this.preview.size) {
            parts.push(formatBytes(this.preview.size));
        }
        return parts.join(" · ");
    }

    // ------------------------------------------------------------------
    // Архив (ПРАВКА ПМК, шаг 45)
    // ------------------------------------------------------------------

    get archive() {
        return (this.preview && this.preview.archive) || null;
    }

    /**
     * «Файлов: 12 · в распакованном виде: 34,5 МБ · скрыто служебных файлов
     * архиватора: 2». «В распакованном виде», а не «распаковано»: это объём
     * по оглавлению, распаковки не было.
     */
    get archiveSummary() {
        const archive = this.archive;
        if (!archive) {
            return "";
        }
        const parts = [_t("Files: %s", archive.total)];
        if (archive.size) {
            parts.push(_t("size when unpacked: %s", formatBytes(archive.size)));
        }
        if (archive.hidden) {
            parts.push(_t("archiver service files hidden: %s", archive.hidden));
        }
        return parts.join(" · ");
    }

    /**
     * Оговорки к архиву целиком («закрыт паролем», «Показано файлов: 1000 из N») —
     * полосой над списком. Оговорка про сам файл («назван .rar, а внутри
     * ZIP») стоит своей полосой выше, как у любого вложения.
     */
    get archiveNotes() {
        return this.archive ? this.archive.notes : [];
    }

    iconClass(entry) {
        return ENTRY_ICONS[entry.kind] || ENTRY_ICONS.other;
    }

    sizeLabel(entry) {
        return formatBytes(entry.size) || "0 Б";
    }

    /** Адрес «Скачать» у строки архива — только этот файл. */
    entryUrl(entry) {
        return memberUrl(this.props.attachmentId, entry.index, true);
    }

    /**
     * «Скачать» у строки архива — один файл.
     *
     * Не ссылкой <a download>: отказ сервера (порча, контрольная сумма,
     * поддельный размер — всё это видно только при распаковке) браузер
     * показал бы в загрузках словом «Сбой», без причины. Здесь ответ читается:
     * файл — сохраняется, отказ — встаёт красной строкой под именем файла.
     * Файл до 50 МБ (предел сервера) спокойно помещается в память вкладки.
     */
    async downloadEntry(entry) {
        const address = this.entryUrl(entry);
        if (!address || this.state.downloading[entry.index]) {
            return;
        }
        this.state.downloading[entry.index] = true;
        this.state.rowErrors[entry.index] = "";
        try {
            const response = await fetch(url(address), { credentials: "same-origin" });
            if (!response.ok) {
                const body = await response.text();
                if (this.alive) {
                    this.state.rowErrors[entry.index] = downloadRefusal(
                        response.status,
                        response.headers.get("Content-Type"),
                        body
                    );
                }
                return;
            }
            const blob = await response.blob();
            downloadFile(blob, entry.name, "application/octet-stream");
        } catch {
            if (this.alive) {
                // Строка целиком в одном вызове _t — см. priceLoaderHint.
                // prettier-ignore
                this.state.rowErrors[entry.index] = _t("No connection to the server — the file was not downloaded. Try again.").toString();
            }
        } finally {
            if (this.alive) {
                this.state.downloading[entry.index] = false;
            }
        }
    }

    /** Подсказка строки: полный путь в архиве и пометка про путь. */
    entryTitle(entry) {
        return entry.warn ? `${entry.path} — ${entry.warn}` : entry.path;
    }

    /**
     * Открыть файл из архива вторым окном поверх списка. То же окно, что у
     * вложения письма: вид файла сервер решит по содержимому.
     */
    openMember(entry) {
        if (!entry || !entry.canView) {
            return;
        }
        this.dialog.add(AttachmentPreviewDialog, {
            attachmentId: this.props.attachmentId,
            name: entry.name,
            member: { index: entry.index, path: entry.path },
            archiveName: this.props.name || "",
        });
    }

    /**
     * «Скачать» в окне файла из архива — только этот файл (свой адрес).
     *
     * Сервер отказал прочитать файл (пароль, «бомба», порча) — адреса нет и
     * кнопки нет: по ней пришёл бы текст отказа вместо файла. Не дошёл сам
     * запрос (связь) — окно пишет «Файл всё равно можно скачать», и адрес
     * собирается из номера файла.
     */
    get memberDownloadUrl() {
        const member = this.props.member;
        if (!member) {
            return "";
        }
        if (this.state.error) {
            return memberUrl(this.props.attachmentId, member.index, true);
        }
        return this.preview ? this.preview.downloadUrl : "";
    }

    get sheets() {
        return this.preview ? this.preview.sheets : [];
    }

    get sheet() {
        return this.sheets[this.state.tab] || null;
    }

    /** Сводка прайса ТЕКУЩЕГО листа, если она уже посчитана. */
    get price() {
        const sheet = this.sheet;
        return (sheet && this.state.prices[sheet.index]) || null;
    }

    async selectSheet(tab) {
        this.state.tab = tab;
        const sheet = this.sheet;
        // Сводку листа считаем один раз и по первому переходу на него.
        // Сразу для всей книги — значит гонять разборщик названий по листам,
        // которые никто не откроет; каждый раз заново — значит считать одно и
        // то же при щелчках по вкладкам туда-сюда.
        // Сравнение с undefined, а не проверка на истинность: посчитанное
        // «это не прайс» хранится как null и тоже значит «уже спрашивали».
        if (!sheet || this.state.prices[sheet.index] !== undefined || this.state.scanningPrice) {
            return;
        }
        this.state.scanningPrice = true;
        try {
            const raw = await this.orm.call(
                "mail.client.attachment",
                "price_scan",
                [],
                this.serverKwargs({ sheet: sheet.index })
            );
            if (this.alive) {
                // null тоже запоминаем — это ответ «лист на прайс не похож»,
                // и спрашивать его второй раз незачем.
                this.state.prices[sheet.index] = normalizePrice(raw);
            }
        } catch {
            // Сводка — добавка к таблице, а не сама таблица. Не посчиталась —
            // человек смотрит лист без неё, и это лучше, чем окно с ошибкой
            // поверх открытого прайса.
            if (this.alive) {
                this.state.prices[sheet.index] = null;
            }
        } finally {
            if (this.alive) {
                this.state.scanningPrice = false;
            }
        }
    }

    /**
     * Следующий кусок строк того же листа.
     *
     * Сервер отдаёт первые двести строк — этого хватает, чтобы понять, что за
     * файл, и не хватает, чтобы дочитать прайс. «Скачайте файл, чтобы увидеть
     * остальное» в окне, которое заведено ради того, чтобы НЕ скачивать,
     * звучит издевательски, поэтому остальное догружается тем же методом.
     */
    async loadMore() {
        const sheet = this.sheet;
        if (!sheet || !sheet.truncated || this.state.loadingMore) {
            return;
        }
        this.state.loadingMore = true;
        try {
            const raw = await this.orm.call(
                "mail.client.attachment",
                "preview",
                [],
                this.serverKwargs({ sheet: sheet.index, offset: sheet.shownRows })
            );
            if (!this.alive) {
                return;
            }
            // Сырой лист, а не разобранный: appendSheetRows пересобирает лист
            // сама и ждёт то, что прислал сервер. Второй разбор по дороге
            // переименовал бы поля (total_rows -> totalRows), и догруженные
            // строки потерялись бы молча.
            const sheets = (raw && Array.isArray(raw.sheets) && raw.sheets) || [];
            const fresh = sheets.find((item) => item.index === sheet.index);
            this.state.preview.sheets[this.state.tab] = appendSheetRows(sheet, fresh);
        } catch {
            // Догрузка сорвалась — на экране остаётся всё, что уже прочитано,
            // и та же кнопка, которую можно нажать ещё раз. Аварийное окно
            // поверх открытого прайса здесь хуже молчания.
        } finally {
            if (this.alive) {
                this.state.loadingMore = false;
            }
        }
    }

    /**
     * Адрес рамки pdf.js.
     *
     * Файл не отдаётся браузеру: страницу рисует pdf.js из /web/static/lib,
     * тот самый, которым пользуется штатный виджет pdf_viewer. Встроенный
     * просмотрщик браузера выполнил бы то, что в PDF записано, — для файла
     * от постороннего это лишнее.
     */
    get pdfViewerUrl() {
        if (!this.preview || !this.preview.url) {
            return "";
        }
        const file = encodeURIComponent(url(this.preview.url));
        return `/web/static/lib/pdfjs/web/viewer.html?file=${file}`;
    }

    /**
     * Доля узнанного — обычные скобки с процентом, без перевода: переводить
     * «(88%)» не на что, а лишняя строка в словаре живёт вечно.
     */
    get percentLabel() {
        const price = this.price;
        return price ? `(${price.matchedPercent}%)` : "";
    }

    /** Номер строки прайса у примера непознанной позиции. */
    rowLabel(example) {
        return _t("line %s:", example.row);
    }

    /** «размера нет в справочнике — 153» одной строкой. */
    statusLabel(item) {
        return `${item.status} — ${item.count}`;
    }

    /**
     * Чем заканчивается сводка прайса.
     *
     * Фраза длинная, поэтому живёт здесь, а не текстом в разметке: в
     * разметке перенос строки уехал бы в словарь переводов вместе с
     * отступами, и одна правка вёрстки обнулила бы перевод.
     *
     * По смыслу это отказ обещать лишнее. Загрузчик цен не берёт из файла ни
     * поставщика, ни дату прайса, ни ставку НДС, и угадывать их нельзя:
     * ошибка в любом из трёх тихо уезжает в деньги.
     */
    get priceLoaderHint() {
        // Строка целиком, без склейки: извлекатель переводов Odoo читает
        // аргумент _t регулярным выражением и от склейки увидел бы только
        // первый кусок — перевод молча потерялся бы наполовину.
        // prettier-ignore
        return _t("Prices are loaded by the price loader: it needs the supplier, the date of the price list and the VAT rate. A person sets those — the system does not guess them.");
    }

    /**
     * Сколько строк показано из скольких. Число внутри фразы, а не рядом с
     * ней: в русском «показаны первые 200 строк из 711» — одно предложение,
     * и склеивать его из кусков в разметке значило бы заставить переводчика
     * гадать о порядке слов.
     */
    get truncatedLabel() {
        const sheet = this.sheet;
        if (!sheet) {
            return "";
        }
        return _t("Showing %s rows of %s.", sheet.shownRows, sheet.totalRows);
    }

    onDownload() {
        if (this.props.onDownload) {
            this.props.onDownload();
        }
    }

    onClose() {
        if (this.props.close) {
            this.props.close();
        }
    }
}
