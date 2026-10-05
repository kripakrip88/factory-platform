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
 *     mail.client.attachment.preview(attachment_id, sheet, offset, limit, member)
 *
 * Ответ:
 *
 *     kind      'sheet' | 'pdf' | 'image' | 'archive' | 'none' — ВИД ФАЙЛА ПО
 *               СОДЕРЖИМОМУ.
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
 * ПРАВКА ПМК (шаг 45, 05.10.2026) — архивы:
 *
 *     format_title  что за файл словами («архив ZIP», «таблица Excel») —
 *               подпись окна вместо mimetype
 *     archive   для kind='archive': {entries: [{index, path, dir, name, size,
 *               date, kind, reason, warn}], total, size, encrypted, hidden,
 *               notes} — см. normalizeArchive. kind строки — 'pdf' | 'sheet' |
 *               'image' | 'archive' | 'other'; reason — почему файл не
 *               открыть («закрыт паролем»), warn — пометка про путь
 *     member    для файла ИЗ архива: {index, path}; тогда же archive_name —
 *               имя архива, url — /mail_client/attachment/N/member/I,
 *               download_url — он же с ?download=1. Файл из архива
 *               спрашивается тем же preview() с аргументом member = index
 *               (и price_scan(attachment_id, sheet, member) — тоже).
 *     «Скачать» у строки списка — запрос GET того же адреса с ?download=1;
 *               отказ приходит текстом с кодом (см. downloadRefusal).
 *
 * ПРАВКА ПМК (шаг 46, 06.10.2026) — чертежи DXF:
 *
 *     kind      ещё 'drawing' — чертёж DXF, нарисованный сервером
 *               (модуль pmk_drawing, библиотека ezdxf)
 *     drawing   для kind='drawing': готовые пути по слоям — договор в шапке
 *               pmk_drawing/tools/dxf_render.py. Здесь он только
 *               пробрасывается: проверяет и рисует его окно чертежа
 *               pmk_drawing (normalizeDrawing), которое окно почты берёт из
 *               реестра pmk_file_viewers. Строка архива с kind 'drawing'
 *               открывается «Посмотреть», как PDF.
 *
 * Второй метод, price_scan(attachment_id, sheet) -> price, зовётся только при
 * переходе на другую вкладку: сводка считается по ЛИСТУ, и у листа «Сервис»
 * она своя. Считать её сразу для всех листов значило бы гонять разборщик
 * названий по всей книге ради вкладки, на которую человек может и не перейти.
 *
 * Запасные строки про отказ написаны по-русски прямо здесь, а не через _t:
 * перевод тянет за собой импорт Odoo, а вместе с ним и невозможность гонять
 * этот файл обычным node. Система русская, а видны эти строки только тогда,
 * когда сервер не прислал своего объяснения. По той же причине здесь
 * русские единицы размера (formatBytes): «КБ», а не «KB».
 */

export const KINDS = {
    SHEET: "sheet",
    PDF: "pdf",
    IMAGE: "image",
    ARCHIVE: "archive",
    // ПРАВКА ПМК (шаг 46): чертёж DXF.
    DRAWING: "drawing",
    NONE: "none",
};

const KNOWN_KINDS = new Set([
    KINDS.SHEET,
    KINDS.PDF,
    KINDS.IMAGE,
    KINDS.ARCHIVE,
    KINDS.DRAWING,
    KINDS.NONE,
]);

// Вид строки в списке архива. Посмотреть можно то, что окно умеет рисовать;
// вложенный архив и прочее — только скачать. ПРАВКА ПМК (шаг 46): чертёж
// DXF — тоже «Посмотреть» (сервер ставит 'drawing', только если модуль
// просмотра чертежей установлен).
const ENTRY_KINDS = new Set(["pdf", "sheet", "image", "drawing", "archive", "other"]);
const VIEWABLE_KINDS = new Set(["pdf", "sheet", "image", "drawing"]);

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
 * Размер по-русски: «512 Б», «2,0 КБ», «5,3 МБ». ПРАВКА ПМК (шаг 45).
 *
 * Общий formatSize почты пишет «KB» — английское слово на экране. Окно
 * просмотра своё, и в нём размер — русскими единицами.
 */
export function formatBytes(bytes) {
    const value = count(bytes);
    if (!value) {
        return "";
    }
    const units = ["Б", "КБ", "МБ", "ГБ"];
    let size = value;
    let unit = 0;
    while (size >= 1024 && unit < units.length - 1) {
        size /= 1024;
        unit++;
    }
    const number = unit === 0 ? String(size) : size.toFixed(1).replace(".", ",");
    return `${number} ${units[unit]}`;
}

/**
 * Адрес файла из архива на нашем сервере. ПРАВКА ПМК (шаг 45).
 *
 * Собирается из двух целых чисел и ничего больше: номер вложения и номер
 * файла в архиве. Не число — пустая строка, и кнопки «Скачать» у строки нет.
 */
export function memberUrl(attachmentId, index, download = false) {
    if (!Number.isInteger(attachmentId) || attachmentId <= 0 || !Number.isInteger(index) || index < 0) {
        return "";
    }
    return `/mail_client/attachment/${attachmentId}/member/${index}${download ? "?download=1" : ""}`;
}

/**
 * Что сказать у строки архива, если «Скачать» не удалось. ПРАВКА ПМК (шаг 45).
 *
 * Порча, неверная контрольная сумма, поддельный размер выясняются только при
 * распаковке, то есть уже по нажатию «Скачать». Сервер отвечает на отказ
 * простым текстом с кодом 413/422/502 — этот текст и показываем. Отказ «нет
 * такого файла» Odoo отдаёт страницей HTML: её разметка человеку ни к чему,
 * поэтому текст берётся только из ответа text/plain.
 */
export function downloadRefusal(status, contentType, body) {
    const plain = text(contentType).toLowerCase().startsWith("text/plain");
    const message = plain ? text(body).trim().slice(0, 500) : "";
    if (message) {
        return message;
    }
    if (status === 404) {
        return "Файл не найден: архив или письмо изменились, либо к письму нет доступа. Откройте архив заново.";
    }
    return "Файл не скачался. Скачайте архив целиком.";
}

/**
 * Список файлов архива. ПРАВКА ПМК (шаг 45).
 *
 * Строки приходят отсортированными с сервера (папка, потом имя, «Лист 2»
 * раньше «Лист 10»); здесь они только раскладываются по папкам — группа на
 * папку, корень первым, порядок групп — как пришли строки. Строка без
 * целого номера выбрасывается: открыть её нечем.
 */
export function normalizeArchive(raw) {
    const source = raw || {};
    const rawEntries = Array.isArray(source.entries) ? source.entries : [];
    const entries = [];
    for (const item of rawEntries) {
        if (!item || !Number.isInteger(item.index) || item.index < 0) {
            continue;
        }
        const kind = ENTRY_KINDS.has(item.kind) ? item.kind : "other";
        const reason = text(item.reason);
        const name = text(item.name) || text(item.path) || "без имени";
        entries.push({
            index: item.index,
            path: text(item.path) || name,
            dir: text(item.dir),
            name,
            size: count(item.size),
            date: text(item.date),
            kind,
            reason,
            warn: text(item.warn),
            canView: !reason && VIEWABLE_KINDS.has(kind),
            canDownload: !reason,
        });
    }
    const groups = [];
    const byDir = new Map();
    for (const entry of entries) {
        let group = byDir.get(entry.dir);
        if (!group) {
            group = {
                dir: entry.dir,
                // «Чертежи / Узел 1»: путь папки читается, а не разбирается.
                label: entry.dir.split("/").filter(Boolean).join(" / "),
                entries: [],
            };
            byDir.set(entry.dir, group);
            groups.push(group);
        }
        group.entries.push(entry);
    }
    // Корень — первым, даже если сервер прислал его позже.
    groups.sort((left, right) => (left.dir ? 1 : 0) - (right.dir ? 1 : 0));
    const notes = Array.isArray(source.notes) ? source.notes.map(text).filter(Boolean) : [];
    return {
        entries,
        groups,
        total: Math.max(count(source.total), entries.length),
        shown: entries.length,
        size: count(source.size),
        encrypted: count(source.encrypted),
        hidden: count(source.hidden),
        notes,
    };
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
    const member = source.member && Number.isInteger(source.member.index) && source.member.index >= 0
        ? { index: source.member.index, path: text(source.member.path) }
        : null;
    const preview = {
        kind,
        name: text(source.name),
        mimetype: text(source.mimetype),
        formatTitle: text(source.format_title),
        size: count(source.size),
        url: safeUrl(source.url),
        // Скачать файл из архива — наш адрес; у обычного вложения поле не
        // читается (скачивание идёт кнопкой письма).
        downloadUrl: safeUrl(source.download_url),
        reason: text(source.reason),
        // Предупреждение живёт отдельно от отказа: файл показался, но с
        // оговоркой («назван .xls, а внутри HTML»). Слить их в одно поле
        // значило бы либо прятать оговорку, либо ругаться на исправный файл.
        note: text(source.note),
        sheets: [],
        price: null,
        archive: null,
        member,
        archiveName: text(source.archive_name),
        drawing: null,
    };

    if (kind === KINDS.DRAWING) {
        // ПРАВКА ПМК (шаг 46): пути чертежа проверяет окно чертежа
        // (pmk_drawing, normalizeDrawing) — здесь только «пришёл ли он».
        const drawing = source.drawing;
        if (drawing && typeof drawing === "object" && !Array.isArray(drawing) && drawing.ok) {
            preview.drawing = drawing;
        } else {
            preview.kind = KINDS.NONE;
            preview.reason =
                preview.reason ||
                text(drawing && drawing.reason) ||
                "Чертёж не удалось показать. Файл можно скачать.";
        }
    } else if (kind === KINDS.SHEET) {
        const sheets = Array.isArray(source.sheets) ? source.sheets : [];
        preview.sheets = sheets.map(normalizeSheet).filter((sheet) => sheet.rows.length);
        preview.price = normalizePrice(source.price);
        if (!preview.sheets.length) {
            // Таблица без единой строки — это не таблица. Лучше сказать прямо,
            // чем рисовать пустую сетку и оставлять человека гадать.
            preview.kind = KINDS.NONE;
            preview.reason = preview.reason || "В файле не нашлось ни одной строки.";
        }
    } else if (kind === KINDS.ARCHIVE) {
        preview.archive = normalizeArchive(source.archive);
        if (!preview.archive.entries.length) {
            // Пустой список — не список: говорим прямо, почему смотреть нечего.
            preview.kind = KINDS.NONE;
            preview.reason =
                preview.reason ||
                (preview.archive.hidden
                    ? "В архиве только служебные файлы архиватора."
                    : "В архиве нет ни одного файла.");
            preview.archive = null;
        }
    } else if ((kind === KINDS.PDF || kind === KINDS.IMAGE) && !preview.url) {
        // Сюда попадает и пустой адрес, и отброшенный чужой: показывать нечем
        // в обоих случаях, а разбираться, какой именно был, человеку незачем.
        preview.kind = KINDS.NONE;
        preview.reason = preview.reason || "Нет пригодной ссылки, по которой файл можно показать.";
    }

    return preview;
}
