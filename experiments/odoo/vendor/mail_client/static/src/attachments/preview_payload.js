/* ПМК: разбор ответа сервера о вложении и решения о том, как рисовать таблицу.
 *
 * В файле намеренно нет ни одного импорта Odoo. Всё здесь — чистые функции над
 * простыми объектами, поэтому их гоняют на живых прайсах обычным node, не
 * поднимая ни браузер, ни Odoo. Логика, которая решает, читаемо ли выйдет
 * окно с 596 строками, должна проверяться дешевле, чем открытием почты.
 *
 * ДОГОВОР С СЕРВЕРНОЙ ЧАСТЬЮ
 * --------------------------
 * Второй конец договора — метод preview() в
 * models/mail_client_attachment_preview.py. Имена полей ниже — это имена,
 * которые он кладёт в ответ; менять их можно только с обеих сторон сразу.
 *
 *     mail.client.attachment.preview(attachment_id, sheet, offset, limit)
 *
 * Ответ:
 *
 *     kind      'sheet' | 'pdf' | 'image' | 'none'   — ВИД ФАЙЛА ПО СОДЕРЖИМОМУ.
 *               Определяет сервер, а не клиент: в письме от постороннего
 *               заявленный content-type регулярно врёт (прайс приходит
 *               как application/octet-stream), а расширение — тем более.
 *     name      имя файла
 *     mimetype  что на самом деле опознал сервер, для подписи
 *     size      размер В БАЙТАХ ПОСЛЕ РАСКОДИРОВАНИЯ. Не тот, что в списке
 *               вложений письма: там размер MIME-части, то есть base64,
 *               он на треть больше настоящего.
 *     url       путь к файлу на нашем сервере, '/mail_client/attachment/N/raw'.
 *               Нужен для pdf и картинки. Только свой путь от корня —
 *               см. safeUrl() ниже.
 *     sheets    для kind='sheet': ВСЕ листы книги
 *               [{name, columns: [строки], rows: [[строки]], total_rows}]
 *               Строки приходят для каждого листа, потому что вкладки окно
 *               переключает у себя, не спрашивая сервер. Ячейки приходят УЖЕ
 *               СТРОКАМИ: числа форматирует сервер, он один знает тип ячейки
 *               xls. Клиент их только выравнивает.
 *     price     разбор прайса ВЫБРАННОГО листа или null (см. normalizePrice)
 *     note      предупреждение при удавшемся просмотре: «назван .xls, а
 *               внутри HTML», «документ закрыт паролем»
 *     reason    для kind='none': почему просмотра нет, человеческими словами
 *
 * Второй метод, price_scan(attachment_id, sheet) -> price, зовётся только при
 * переходе на другую вкладку: сводка считается по ЛИСТУ, и у листа «Сервис»
 * она своя. Считать её сразу для всех листов значило бы гонять разборщик
 * названий по всей книге ради вкладки, на которую человек может и не перейти.
 *
 * Две запасные строки про отказ написаны по-русски прямо здесь, а не через _t:
 * перевод тянет за собой импорт Odoo, а вместе с ним и невозможность гонять
 * этот файл обычным node. Система русская, строк две, и видны они только
 * тогда, когда сервер не прислал своего объяснения.
 */

export const KINDS = {
    SHEET: "sheet",
    PDF: "pdf",
    IMAGE: "image",
    NONE: "none",
};

const KNOWN_KINDS = new Set([KINDS.SHEET, KINDS.PDF, KINDS.IMAGE, KINDS.NONE]);

/** Пустая строка вместо null/undefined/числа: в разметку идёт только текст. */
function text(value) {
    if (value === null || value === undefined || value === false) {
        return "";
    }
    return String(value);
}

function count(value) {
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? Math.floor(number) : 0;
}

/**
 * Пропускаем только путь от корня нашего же сервера.
 *
 * Файл пришёл от постороннего, и адрес для <img> или для pdf.js — это запрос,
 * который браузер сделает молча. Чужой абсолютный адрес («https://…») или
 * протоколо-относительный («//…») сообщил бы отправителю, что письмо открыли,
 * ровно так же, как картинка в теле письма, которую модуль блокирует. Поэтому
 * адрес принимается, только если он начинается с одной косой черты.
 */
export function safeUrl(value) {
    const raw = text(value);
    if (!raw.startsWith("/") || raw.startsWith("//")) {
        return "";
    }
    return raw;
}

/**
 * Число ли в ячейке.
 *
 * Считаем числом то, что человек читает как число в прайсе: «62 000,50»,
 * «1 234.5», «-3», «12%». Пробелы убираем все, включая неразрывный ( ) и
 * узкий неразрывный ( ) — Excel разделяет ими разряды, и без этого цена
 * «62 000» осталась бы текстом и уехала влево.
 */
export function isNumericCell(value) {
    const cleaned = text(value).replace(/[\s  ]/g, "");
    if (!cleaned) {
        return false;
    }
    return /^[-+]?\d+(?:[.,]\d+)?%?$/.test(cleaned);
}

/**
 * Выравнивание каждой колонки: 'num' — вправо, 'text' — влево.
 *
 * Решаем по большинству непустых ячеек, а не по первой попавшейся: в колонке
 * цен обязательно найдётся «по запросу» или прочерк, и одна такая ячейка не
 * должна разворачивать всю колонку. Порог 0.6 взят с запасом — на прайсе
 * Металлсервиса числовые колонки дают 0.95 и выше, текстовые 0.0.
 */
export function columnAlignments(rows, columnCount) {
    const aligns = [];
    for (let column = 0; column < columnCount; column++) {
        let filled = 0;
        let numeric = 0;
        for (const row of rows) {
            const cell = row[column];
            if (!cell) {
                continue;
            }
            filled++;
            if (isNumericCell(cell)) {
                numeric++;
            }
        }
        aligns.push(filled && numeric / filled >= 0.6 ? "num" : "text");
    }
    return aligns;
}

/**
 * Лист таблицы: выравниваем строки по одной ширине.
 *
 * Строки из xls приходят рваными — в Excel у строки ровно столько ячеек,
 * сколько заполнено. Рваный <tr> ломает сетку таблицы, и вместе с ней
 * закреплённую шапку: колонки под шапкой перестают совпадать с ней по ширине.
 * Поэтому ширина листа — максимум по шапке и по всем строкам, короткие строки
 * добиваются пустыми ячейками, лишние ячейки отбрасываются.
 */
function normalizeSheet(raw, index) {
    const source = raw || {};
    const rawRows = Array.isArray(source.rows) ? source.rows : [];
    const rawColumns = Array.isArray(source.columns) ? source.columns : [];

    let width = rawColumns.length;
    for (const row of rawRows) {
        if (Array.isArray(row) && row.length > width) {
            width = row.length;
        }
    }

    const fit = (row) => {
        const cells = [];
        for (let i = 0; i < width; i++) {
            cells.push(text(Array.isArray(row) ? row[i] : ""));
        }
        return cells;
    };

    const rows = rawRows.map(fit);
    const columns = fit(rawColumns);
    const shownRows = rows.length;
    // Сервер мог прислать только начало листа. Берём максимум из заявленного
    // и присланного: если total_rows потерялся, «показано 200 из 0» — враньё
    // хуже молчания.
    const totalRows = Math.max(count(source.total_rows), shownRows);

    return {
        // Номер листа В КНИГЕ, а не в этом массиве. Пустые листы из показа
        // выпадают, и после этого «третья вкладка» и «третий лист книги» —
        // разные листы. Сервер спрашивают именно про лист книги, поэтому
        // номер носим с собой, а не считаем по положению вкладки.
        index: Number.isInteger(source.index) ? source.index : index,
        name: text(source.name) || `Лист ${index + 1}`,
        columns,
        rows,
        aligns: columnAlignments(rows, width),
        hasHeader: columns.some((cell) => cell !== ""),
        shownRows,
        totalRows,
        truncated: totalRows > shownRows,
    };
}

/**
 * Дописать к листу следующий кусок строк, пришедший с сервера.
 *
 * Лист пересобирается целиком, а не дополняется на месте, и это не лень:
 * ширина листа считается по самой длинной строке, и строка на 18 колонок,
 * приехавшая во второй сотне, расширяет ВСЮ таблицу. Дописав её к готовому
 * листу, мы получили бы первую сотню строк на 15 ячеек под шапкой на 18 —
 * то есть съехавшую сетку. Выравнивание колонок по той же причине считается
 * заново: по двум сотням строк оно вернее, чем по одной.
 */
export function appendSheetRows(sheet, raw) {
    const source = raw || {};
    const fresh = Array.isArray(source.rows) ? source.rows : [];
    const merged = normalizeSheet(
        {
            index: sheet.index,
            name: sheet.name,
            columns: sheet.columns,
            rows: sheet.rows.concat(fresh),
            total_rows: Math.max(sheet.totalRows, count(source.total_rows)),
        },
        sheet.index
    );
    if (!fresh.length) {
        // Сервер отдал пустой кусок: строки кончились, сколько бы их ни было
        // обещано. Иначе кнопка «Показать ещё» осталась бы на месте навсегда
        // и на каждое нажатие не делала бы ничего.
        merged.totalRows = merged.shownRows;
        merged.truncated = false;
    }
    return merged;
}

/**
 * Разбор прайса: сколько строк, сколько позиций узнано, сколько нет.
 *
 * Ради этого всё и делается: прайс в письме интересен не как таблица, а как
 * ответ на вопрос «сколько отсюда ляжет в цены и что не ляжет».
 *
 * Лист, который на прайс не похож (счёт, письмо, перечень услуг), сводки не
 * получает вовсе — возвращается null. Показывать «узнано 0 из 0» под каждым
 * счётом значит приучить не читать эту строку.
 *
 * А вот прайс, который РАЗОБРАТЬ НЕ ВЫШЛО (справочник металла недоступен),
 * сводку получает — с полем error. Молчание в этом месте человек прочитает
 * как «в прайсе ничего не узналось», то есть как ответ про прайс, хотя
 * ответ здесь про систему.
 */
export function normalizePrice(raw) {
    if (!raw || !raw.is_price) {
        return null;
    }
    const rowsTotal = count(raw.rows_total);
    const matched = count(raw.matched);
    const unmatched = count(raw.unmatched);
    const error = text(raw.error);
    if (!rowsTotal && !matched && !unmatched && !error) {
        return null;
    }
    const examples = Array.isArray(raw.unmatched_examples) ? raw.unmatched_examples : [];
    const byStatus = raw.by_status && typeof raw.by_status === "object" ? raw.by_status : {};
    return {
        // Номер листа книги, к которому относится сводка. Присылает сервер:
        // сам клиент его не вычислит, потому что не знает, какие листы
        // выпали из показа пустыми.
        sheet: Number.isInteger(raw.sheet) ? raw.sheet : 0,
        rowsTotal,
        matched,
        unmatched,
        // Доля узнанного: по ней видно, тот ли это разборщик для этого прайса,
        // ещё до того, как человек начнёт листать примеры.
        matchedPercent: rowsTotal ? Math.round((matched / rowsTotal) * 100) : 0,
        // Почему не узналось, по видам, от частого к редкому. Порядок задаём
        // здесь: словарь с сервера приходит в произвольном, и список причин
        // прыгал бы при каждом открытии одного и того же файла.
        byStatus: Object.keys(byStatus)
            .map((status) => ({ status, count: count(byStatus[status]) }))
            .filter((item) => item.count > 0 && item.status !== "совпало")
            .sort((left, right) => right.count - left.count),
        unmatchedExamples: examples.slice(0, 10).map((example) => ({
            row: count(example && example.row),
            text: text(example && example.text),
            status: text(example && example.status),
        })),
        note: text(raw.note),
        error,
    };
}

/**
 * Приводим ответ сервера к виду, на который рассчитана разметка.
 *
 * Неизвестный вид файла — это 'none', а не пустое окно: старый сервер рядом с
 * новым клиентом честно скажет «просмотр не поддерживается» и оставит
 * скачивание, вместо того чтобы показать пустоту.
 */
export function normalizePreview(raw) {
    const source = raw || {};
    const kind = KNOWN_KINDS.has(source.kind) ? source.kind : KINDS.NONE;
    const preview = {
        kind,
        name: text(source.name),
        mimetype: text(source.mimetype),
        size: count(source.size),
        url: safeUrl(source.url),
        reason: text(source.reason),
        // Предупреждение живёт отдельно от отказа: файл показался, но с
        // оговоркой («назван .xls, а внутри HTML»). Слить их в одно поле
        // значило бы либо прятать оговорку, либо ругаться на исправный файл.
        note: text(source.note),
        sheets: [],
        price: null,
    };

    if (kind === KINDS.SHEET) {
        const sheets = Array.isArray(source.sheets) ? source.sheets : [];
        preview.sheets = sheets.map(normalizeSheet).filter((sheet) => sheet.rows.length);
        preview.price = normalizePrice(source.price);
        if (!preview.sheets.length) {
            // Таблица без единой строки — это не таблица. Лучше сказать прямо,
            // чем рисовать пустую сетку и оставлять человека гадать.
            preview.kind = KINDS.NONE;
            preview.reason = preview.reason || "В файле не нашлось ни одной строки.";
        }
    } else if ((kind === KINDS.PDF || kind === KINDS.IMAGE) && !preview.url) {
        // Сюда попадает и пустой адрес, и отброшенный чужой: показывать нечем
        // в обоих случаях, а разбираться, какой именно был, человеку незачем.
        preview.kind = KINDS.NONE;
        preview.reason = preview.reason || "Нет пригодной ссылки, по которой файл можно показать.";
    }

    return preview;
}
