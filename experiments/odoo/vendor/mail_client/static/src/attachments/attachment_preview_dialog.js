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
 */
import { Component, onWillDestroy, useEffect, useRef, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { hidePDFJSButtons } from "@web/core/utils/pdfjs";
import { url } from "@web/core/utils/urls";

import { formatSize } from "../utils";
import { KINDS, appendSheetRows, normalizePreview, normalizePrice } from "./preview_payload";

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
        // Кладёт служба диалогов.
        close: { type: Function, optional: true },
    };

    setup() {
        this.orm = useService("orm");
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
            const raw = await this.orm.call("mail.client.attachment", "preview", [], {
                attachment_id: this.props.attachmentId,
            });
            if (!this.alive) {
                return;
            }
            const preview = normalizePreview(raw);
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

    get preview() {
        return this.state.preview;
    }

    get dialogTitle() {
        // toString() обязателен: _t отдаёт не примитивную строку, а объект
        // отложенного перевода, а Dialog объявляет title как type: String —
        // в режиме разработчика проверка свойств на объекте падает.
        return (this.props.name || _t("Attachment")).toString();
    }

    /** Подпись под заголовком: что это за файл и сколько весит. */
    get subtitle() {
        const parts = [];
        if (this.preview && this.preview.mimetype) {
            parts.push(this.preview.mimetype);
        }
        // Размер берём только у сервера. В списке вложений письма стоит
        // размер MIME-части, то есть base64: он на треть больше настоящего,
        // и показывать его рядом с открытым файлом — врать в мелочи.
        if (this.preview && this.preview.size) {
            parts.push(formatSize(this.preview.size));
        }
        return parts.join(" · ");
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
            const raw = await this.orm.call("mail.client.attachment", "price_scan", [], {
                attachment_id: this.props.attachmentId,
                sheet: sheet.index,
            });
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
            const raw = await this.orm.call("mail.client.attachment", "preview", [], {
                attachment_id: this.props.attachmentId,
                sheet: sheet.index,
                offset: sheet.shownRows,
            });
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
