# -*- coding: utf-8 -*-
# Правка ПМК Парк к вендорскому модулю mail_client.
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""Разбор вложения на сервере: показать содержимое, не отдавая файл браузеру.

ПОЧЕМУ ОТДЕЛЬНЫМ ФАЙЛОМ, А НЕ ПРАВКОЙ mail_client_attachment.py
Вендорский модуль мы обновляем слиянием, и каждая строка, дописанная в чужой
файл, — это конфликт при следующем `git merge`. Здесь чужой файл не тронут
вовсе: всё наше лежит рядом и подмешивается через `_inherit`.

ПОЧЕМУ РАЗБОР НА СЕРВЕРЕ, А НЕ В БРАУЗЕРЕ
Файлы приходят от посторонних. Книга Excel — это код: формулы, внешние связи,
макросы. Разобранная библиотекой на сервере, она превращается в список строк,
и выполнять там уже нечего. PDF по той же причине не отдаём браузеру как
документ: страницу рисует pdf.js, а наш контроллер отдаёт байты так, что
показать их сам браузер не возьмётся (см. controllers/preview.py).

ПОЧЕМУ ПРАЙС ПОКАЗЫВАЕМ РАЗОБРАННЫМ
Сырая таблица на 596 строк человеку ничего не говорит: «цены пришли» видно и
по имени файла. Полезен ответ на другой вопрос — сколько из этих строк система
узнала и сможет залить. Поэтому таблицу, похожую на прайс, прогоняем через тот
же разборщик названий, которым заливаются цены (pmk_bridge/tools/vendor/match.py),
и отдаём сводку. Разборщик именно ИМПОРТИРУЕТСЯ: вторая копия правил разойдётся
с первой молча, и расхождение вылезет уже на деньгах.

ЧТО СЮДА НЕ ПОПАЛО
Чертежи DXF определяются как вид файла, но не разбираются: рисовать их в
браузере нам пока нечем, а обещать просмотр, которого нет, хуже, чем честно
предложить скачать.
"""

import csv as csv_module
import io
import logging
import os
import re
import zipfile
from datetime import date, datetime
from html.parser import HTMLParser
from xml.etree import ElementTree

from odoo import api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# ПРЕДЕЛЫ
# ═══════════════════════════════════════════════════════════════════════════
# Строк на один запрос. Прайс Металлсервиса — 711 строк на 15 колонок; если
# гнать лист целиком, в браузер уедет вся книга, а человек всё равно смотрит
# первый экран. 200 строк — это десяток экранов: пролистать с запасом есть
# что, а весит страница ~40 КБ. Остальное догружается тем же методом со
# смещением, поэтому «дальше не посмотреть» здесь не возникает.
PAGE_ROWS = 200
PAGE_ROWS_MAX = 500

# Колонок и длина ячейки: защита от таблиц, где справа тянется мусор на тысячу
# колонок, и от ячейки с вложенным письмом на 100 КБ.
MAX_COLS = 40
MAX_CELL_CHARS = 200

MAX_SHEETS = 20

# Сколько строк читаем с диска вообще. Сводка по прайсу считается по ВСЕМУ
# листу, иначе она врёт, поэтому предел выше страничного. 20 000 строк — это
# заведомо больше любого прайса поставщика, что мы видели.
SCAN_ROWS = 20000
# И общий потолок по ячейкам: 20 000 строк по 40 колонок дают 800 000 ячеек,
# а это уже сотни мегабайт строк в памяти рабочего процесса.
MAX_CELLS = 300000

# Разбирать таблицу тяжелее, чем показать: openpyxl держит лист в памяти.
MAX_PARSE_BYTES = 25 * 1024 * 1024
# Выше этого не тянем вовсе — вложение сначала целиком грузится с IMAP в
# память, потом в base64 в базу. 50 МБ в base64 — это 67 МБ в строке.
MAX_FETCH_BYTES = 50 * 1024 * 1024


def _mb(size):
    return "%.1f МБ" % (size / 1024.0 / 1024.0)


class PreviewError(Exception):
    """Понятная человеку причина, по которой показать нечего."""


# ═══════════════════════════════════════════════════════════════════════════
# 1. ВИД ФАЙЛА
# ═══════════════════════════════════════════════════════════════════════════
# Виды — те же пять, что и у WebErpMes: по ним решается, чем показывать.
KIND_BY_FORMAT = {
    'xls': 'sheet', 'xlsx': 'sheet', 'ods': 'sheet', 'csv': 'sheet',
    'html': 'sheet',
    'pdf': 'doc',
    'png': 'image', 'jpeg': 'image', 'gif': 'image', 'bmp': 'image',
    'webp': 'image', 'tiff': 'image',
    'dxf': 'cad2d',
}

FORMAT_TITLE = {
    'xls': 'таблица Excel (старый формат)', 'xlsx': 'таблица Excel',
    'ods': 'таблица OpenDocument', 'csv': 'таблица CSV',
    'html': 'таблица HTML', 'pdf': 'документ PDF', 'dxf': 'чертёж DXF',
    'svg': 'векторная картинка SVG', 'docx': 'документ Word',
    'zip': 'архив', 'ole2': 'документ Microsoft Office',
}

# Расширение и содержимое сплошь и рядом расходятся: 1С и старые ERP отдают
# «прайс.xls», внутри которого HTML-таблица или CSV, а .xlsx — это zip.
# Поэтому расширение здесь только для сообщения о расхождении.
EXT_FORMAT = {
    'xls': 'xls', 'xlsb': 'xls', 'xlsx': 'xlsx', 'xlsm': 'xlsx', 'xltx': 'xlsx',
    'ods': 'ods', 'csv': 'csv', 'tsv': 'csv', 'txt': 'csv',
    'htm': 'html', 'html': 'html', 'pdf': 'pdf', 'dxf': 'dxf', 'svg': 'svg',
    'png': 'png', 'jpg': 'jpeg', 'jpeg': 'jpeg', 'gif': 'gif', 'bmp': 'bmp',
    'webp': 'webp', 'tif': 'tiff', 'tiff': 'tiff', 'doc': 'ole2', 'docx': 'docx',
}

_TEXT_ENCODINGS = ('utf-8-sig', 'utf-8', 'cp1251', 'koi8-r')


def decode_text(blob, limit=None):
    """Текст из байтов. Русские выгрузки почти всегда cp1251, а не utf-8."""
    chunk = blob[:limit] if limit else blob
    for encoding in _TEXT_ENCODINGS:
        try:
            return chunk.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    # Последняя попытка: показать хоть что-то, потеряв отдельные символы.
    return chunk.decode('cp1251', 'replace'), 'cp1251'


def _zip_format(blob):
    """Что внутри zip: xlsx, ods, docx или просто архив."""
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            names = set(archive.namelist()[:200])
            if 'xl/workbook.xml' in names:
                return 'xlsx'
            if 'mimetype' in names:
                mimetype = archive.read('mimetype')[:100]
                if b'opendocument.spreadsheet' in mimetype:
                    return 'ods'
            if 'word/document.xml' in names:
                return 'docx'
            if any(n.startswith('xl/') for n in names):
                return 'xlsx'
    except (zipfile.BadZipFile, KeyError, OSError):
        return 'zip'
    return 'zip'


def _text_format(blob):
    """Форматы без сигнатуры: DXF, SVG, HTML, CSV. None — не текст вовсе."""
    head = blob[:8192]
    if b'\x00' in head:                       # двоичный файл, текстом не читаем
        return None
    text, _enc = decode_text(head)
    low = text.lstrip().lower()

    # DXF в текстовом виде начинается с группы 0 и слова SECTION; у части
    # файлов перед этим стоит комментарий группы 999.
    lines = [ln.strip() for ln in text.splitlines()[:40] if ln.strip()]
    if lines[:2] == ['0', 'SECTION'] or '$ACADVER' in text:
        return 'dxf'
    if low.startswith('<svg') or ('<svg' in low[:2048] and low.startswith('<?xml')):
        return 'svg'
    if low.startswith(('<!doctype html', '<html', '<table', '<meta')) or '<table' in low:
        return 'html'
    if _looks_delimited(text):
        return 'csv'
    return None


def _looks_delimited(text):
    """CSV узнаём по одинаковому числу разделителей в первых строках."""
    lines = [ln for ln in text.splitlines()[:20] if ln.strip()]
    if len(lines) < 2:
        return False
    for sep in (';', '\t', ','):
        counts = [ln.count(sep) for ln in lines]
        if min(counts) >= 1 and max(counts) - min(counts) <= 1:
            return True
    return False


def detect_format(blob, filename=''):
    """Вид файла по содержимому. Возвращает (format, kind, note)."""
    head = blob[:4096]
    ext = os.path.splitext(filename or '')[1].lower().lstrip('.')

    fmt = None
    if b'%PDF-' in head[:1024]:
        # По стандарту перед %PDF- допускается мусор, поэтому не startswith.
        fmt = 'pdf'
    elif head.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
        # OLE2 — это и .xls, и .doc, и .msg. Различит только чтение книги,
        # поэтому здесь ставим xls, а окончательно решает читатель.
        fmt = 'xls'
    elif head.startswith(b'PK\x03\x04'):
        fmt = _zip_format(blob)
    elif head.startswith(b'\x89PNG\r\n\x1a\n'):
        fmt = 'png'
    elif head.startswith(b'\xff\xd8\xff'):
        fmt = 'jpeg'
    elif head.startswith((b'GIF87a', b'GIF89a')):
        fmt = 'gif'
    elif head.startswith(b'BM'):
        fmt = 'bmp'
    elif head.startswith(b'RIFF') and head[8:12] == b'WEBP':
        fmt = 'webp'
    elif head.startswith((b'II*\x00', b'MM\x00*')):
        fmt = 'tiff'
    elif head[:32].find(b'AutoCAD Binary DXF') >= 0:
        fmt = 'dxf'
    else:
        fmt = _text_format(blob)

    if not fmt:
        fmt = 'other'
    kind = KIND_BY_FORMAT.get(fmt, 'other')

    note = ''
    expected = EXT_FORMAT.get(ext)
    # Внутри OLE2 по одной сигнатуре .doc от .xls не отличить — там общий
    # контейнер. Поэтому про расхождение здесь не говорим: окончательный ответ
    # даст чтение книги, и оно скажет человеку прямым текстом.
    ole2_family = ('doc', 'xls', 'xlsb', 'ppt', 'msg')
    if expected and expected != fmt and not (fmt == 'xls' and ext in ole2_family):
        note = ("Файл назван «.%s», а внутри — %s. Читаем по содержимому."
                % (ext, FORMAT_TITLE.get(fmt, fmt)))
    return fmt, kind, note


# ═══════════════════════════════════════════════════════════════════════════
# 2. ЯЧЕЙКИ И ЛИСТЫ
# ═══════════════════════════════════════════════════════════════════════════
def _num_text(value):
    """Число в текст без потери знаков: 82290.0 -> «82290», 1009.941 как есть.

    Форматирование через %g режет до шести значащих цифр, и цена 1009.941
    превращается в 1009.94 — то есть в другую цену.
    """
    if isinstance(value, bool):
        return 'да' if value else 'нет'
    if isinstance(value, int):
        return str(value)
    if value != value or value in (float('inf'), float('-inf')):   # NaN, inf
        return ''
    if float(value).is_integer() and abs(value) < 1e15:
        return str(int(value))
    return repr(round(float(value), 6))


def _cell_text(value):
    """Ячейка -> строка для показа. Длинное режем, иначе одна ячейка весит больше листа."""
    if value is None:
        return ''
    if isinstance(value, (datetime, date)):
        if isinstance(value, datetime) and (value.hour or value.minute):
            return value.strftime('%d.%m.%Y %H:%M')
        return value.strftime('%d.%m.%Y')
    if isinstance(value, (int, float, bool)):
        text = _num_text(value)
    else:
        text = str(value)
    text = text.replace('\r\n', '\n').strip()
    if len(text) > MAX_CELL_CHARS:
        text = text[:MAX_CELL_CHARS] + '…'
    return text


class _Budget:
    """Общий счётчик ячеек: предел на книгу, а не на лист.

    Иначе книга из двадцати листов по 300 000 ячеек проходит все проверки
    по листам и кладёт рабочий процесс.
    """

    def __init__(self, cells=MAX_CELLS):
        self.left = cells
        self.hit = False

    def take(self, count):
        if self.left <= 0:
            self.hit = True
            return False
        self.left -= count
        return True


def _sheet(name, rows, truncated=False, ncols=None):
    return {
        'name': name or 'Лист',
        'rows': rows,
        'nrows': len(rows),
        'ncols': ncols if ncols is not None else max([len(r) for r in rows] or [0]),
        'truncated': truncated,
    }


def _read_xls(blob):
    """Старый .xls (BIFF). xlrd 2.x умеет только его — и это нам и нужно."""
    try:
        import xlrd
    except ImportError:                                    # pragma: no cover
        raise PreviewError("На сервере нет библиотеки xlrd — таблицу .xls не прочитать.")
    from xlrd.xldate import xldate_as_datetime

    try:
        book = xlrd.open_workbook(file_contents=blob)
    except Exception as exc:
        # xlrd бросает XLRDError и на .doc, и на .msg: снаружи это один и тот
        # же OLE2. Разбирать сообщение библиотеки человеку незачем.
        raise PreviewError(
            "Это файл Microsoft Office, но не таблица Excel — возможно, документ "
            "Word или письмо .msg. Показать таблицей нечего.") from exc

    budget = _Budget()
    sheets = []
    for sheet in book.sheets()[:MAX_SHEETS]:
        ncols = min(sheet.ncols, MAX_COLS)
        rows, truncated = [], sheet.nrows > SCAN_ROWS or sheet.ncols > MAX_COLS
        for r in range(min(sheet.nrows, SCAN_ROWS)):
            if not budget.take(ncols):
                truncated = True
                break
            row = []
            for c in range(ncols):
                cell = sheet.cell(r, c)
                if cell.ctype == 3:                        # XL_CELL_DATE
                    try:
                        row.append(_cell_text(xldate_as_datetime(cell.value, book.datemode)))
                    except (ValueError, OverflowError):
                        row.append(_num_text(cell.value))
                elif cell.ctype == 5:                      # XL_CELL_ERROR
                    row.append('#ОШИБКА')
                else:
                    row.append(_cell_text(cell.value))
            rows.append(row)
        sheets.append(_sheet(sheet.name, rows, truncated, ncols))
    return sheets


def _read_xlsx(blob):
    """.xlsx через openpyxl в потоковом режиме: лист не поднимается в память целиком."""
    try:
        import openpyxl
    except ImportError:                                    # pragma: no cover
        raise PreviewError("На сервере нет библиотеки openpyxl — таблицу .xlsx не прочитать.")
    try:
        # data_only=True — берём посчитанные значения, а не тексты формул:
        # формула чужого файла нам и не нужна, и небезопасна как подсказка.
        book = openpyxl.load_workbook(io.BytesIO(blob), read_only=True,
                                      data_only=True, keep_links=False)
    except Exception as exc:
        raise PreviewError("Книга Excel повреждена и не открывается.") from exc

    budget = _Budget()
    sheets = []
    try:
        for worksheet in book.worksheets[:MAX_SHEETS]:
            rows, truncated = [], False
            for row_values in worksheet.iter_rows(max_col=MAX_COLS, values_only=True):
                if len(rows) >= SCAN_ROWS or not budget.take(MAX_COLS):
                    truncated = True
                    break
                rows.append([_cell_text(v) for v in row_values])
            # Хвост пустых строк openpyxl отдаёт как настоящие: лист «на
            # миллион строк» встречается у каждой второй выгрузки.
            while rows and not any(rows[-1]):
                rows.pop()
            sheets.append(_sheet(worksheet.title, rows, truncated))
    finally:
        book.close()
    return sheets


_ODS_NS = {
    'table': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
    'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
    'office': 'urn:oasis:names:tc:opendocument:xmlns:office:1.0',
}


def _ods_cell_text(cell):
    """Текст ячейки ODS: то, что видит человек, а не внутреннее значение."""
    parts = []
    for para in cell.iter('{%s}p' % _ODS_NS['text']):
        parts.append(''.join(para.itertext()))
    text = '\n'.join(p for p in parts if p is not None).strip()
    if text:
        return text[:MAX_CELL_CHARS]
    value = cell.get('{%s}value' % _ODS_NS['office'])
    if value is not None:
        try:
            return _num_text(float(value))
        except ValueError:
            return value
    return cell.get('{%s}date-value' % _ODS_NS['office']) or ''


def _read_ods(blob):
    """.ods читаем сами из content.xml: odfpy есть не в каждой сборке Odoo.

    Формат простой, но с подвохом: повторяющиеся ячейки и строки пишутся не
    списком, а числом повторов — и в конце листа этот повтор равен миллиону.
    Поэтому повторы разворачиваем только внутри пределов и никогда — для
    пустого хвоста.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            content = archive.read('content.xml')
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise PreviewError("Таблица OpenDocument повреждена: внутри нет content.xml.") from exc
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise PreviewError("Таблица OpenDocument повреждена: разметка не читается.") from exc

    budget = _Budget()
    sheets = []
    tables = list(root.iter('{%s}table' % _ODS_NS['table']))[:MAX_SHEETS]
    for table in tables:
        rows, truncated = [], False
        for row_el in table.iter('{%s}table-row' % _ODS_NS['table']):
            repeat = _int_attr(row_el, 'number-rows-repeated', 1)
            cells, ncols = [], 0
            for cell_el in row_el:
                tag = cell_el.tag
                if not tag.endswith('table-cell') and not tag.endswith('covered-table-cell'):
                    continue
                span = _int_attr(cell_el, 'number-columns-repeated', 1)
                text = _ods_cell_text(cell_el)
                span = min(span, MAX_COLS)
                if not text and ncols + span >= MAX_COLS:
                    break                                  # пустой хвост строки
                for _ in range(span):
                    if ncols >= MAX_COLS:
                        truncated = True
                        break
                    cells.append(text)
                    ncols += 1
            while cells and not cells[-1]:
                cells.pop()
            if not cells:
                # Пустая строка с повтором «на миллион» — конец листа.
                if repeat > 1:
                    continue
                repeat = 1
            for _ in range(min(repeat, SCAN_ROWS - len(rows))):
                if not budget.take(max(len(cells), 1)):
                    truncated = True
                    break
                rows.append(list(cells))
            if len(rows) >= SCAN_ROWS or budget.hit:
                truncated = True
                break
        while rows and not any(rows[-1]):
            rows.pop()
        name = table.get('{%s}name' % _ODS_NS['table']) or 'Лист'
        sheets.append(_sheet(name, rows, truncated))
    if not sheets:
        raise PreviewError("В таблице OpenDocument нет ни одного листа.")
    return sheets


def _int_attr(element, name, default):
    raw = element.get('{%s}%s' % (_ODS_NS['table'], name))
    try:
        return max(int(raw), 1) if raw else default
    except (TypeError, ValueError):
        return default


def _read_csv(blob):
    """CSV: и кодировку, и разделитель определяем по файлу, а не по надежде."""
    text, encoding = decode_text(blob)
    if not text.strip():
        raise PreviewError("Файл пустой.")
    sample = text[:65536]
    try:
        dialect = csv_module.Sniffer().sniff(sample, delimiters=';,\t|')
        delimiter = dialect.delimiter
    except csv_module.Error:
        # Наиболее вероятный разделитель — тот, что ровнее всего повторяется
        # по строкам. Русский Excel пишет «;», выгрузки из ERP — табуляцию.
        lines = [ln for ln in sample.splitlines()[:20] if ln.strip()]
        delimiter = max((';', '\t', ',', '|'),
                        key=lambda s: min([ln.count(s) for ln in lines] or [0]))

    budget = _Budget()
    rows, truncated = [], False
    for row in csv_module.reader(io.StringIO(text), delimiter=delimiter):
        if len(rows) >= SCAN_ROWS or not budget.take(min(len(row), MAX_COLS) or 1):
            truncated = True
            break
        rows.append([_cell_text(v) for v in row[:MAX_COLS]])
    while rows and not any(rows[-1]):
        rows.pop()
    if not rows:
        raise PreviewError("Файл пустой.")
    sheet = _sheet('%s (%s, разделитель «%s»)' % (
        'Таблица', encoding, '\\t' if delimiter == '\t' else delimiter), rows, truncated)
    return [sheet]


class _TableParser(HTMLParser):
    """Таблицы из HTML. Так выгружают прайсы 1С и почтовые «xls» со звёздочкой."""

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.tables = []
        self._stack = []
        self._cell = None

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self._stack.append([])
        elif tag == 'tr' and self._stack:
            self._stack[-1].append([])
        elif tag in ('td', 'th') and self._stack:
            if not self._stack[-1]:
                self._stack[-1].append([])
            self._cell = []
        elif tag == 'br' and self._cell is not None:
            self._cell.append(' ')

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self._cell is not None and self._stack:
            row = self._stack[-1][-1]
            if len(row) < MAX_COLS:
                row.append(_cell_text(''.join(self._cell)))
            self._cell = None
        elif tag == 'table' and self._stack:
            table = self._stack.pop()
            if table:
                self.tables.append(table)

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def close(self):
        HTMLParser.close(self)
        # Незакрытый </table> в выгрузках встречается чаще, чем закрытый.
        while self._stack:
            table = self._stack.pop()
            if table:
                self.tables.append(table)


def _read_html(blob):
    text, _encoding = decode_text(blob)
    match = re.search(r'charset=["\']?([\w\-]+)', text[:2048], re.I)
    if match:
        try:
            text = blob.decode(match.group(1), 'replace')
        except LookupError:
            pass
    parser = _TableParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:                     # разметка бывает любой
        raise PreviewError("Разметка HTML не читается как таблица.") from exc
    if not parser.tables:
        raise PreviewError("В файле нет ни одной таблицы — показывать нечего.")

    budget = _Budget()
    sheets = []
    for number, table in enumerate(parser.tables[:MAX_SHEETS], start=1):
        rows, truncated = [], len(table) > SCAN_ROWS
        for row in table[:SCAN_ROWS]:
            if not budget.take(len(row) or 1):
                truncated = True
                break
            rows.append(row)
        while rows and not any(rows[-1]):
            rows.pop()
        if rows:
            sheets.append(_sheet('Таблица %d' % number, rows, truncated))
    if not sheets:
        raise PreviewError("Таблицы в файле есть, но все пустые.")
    return sheets


_READERS = {
    'xls': _read_xls, 'xlsx': _read_xlsx, 'ods': _read_ods,
    'csv': _read_csv, 'html': _read_html,
}


def read_sheets(blob, fmt):
    """Листы таблицы: [{name, rows, nrows, ncols, truncated}]."""
    reader = _READERS.get(fmt)
    if not reader:
        raise PreviewError("Такой формат таблицей не читается.")
    if len(blob) > MAX_PARSE_BYTES:
        raise PreviewError(
            "Таблица весит %s — это больше предела разбора (%s). Файл можно скачать."
            % (_mb(len(blob)), _mb(MAX_PARSE_BYTES)))
    sheets = reader(blob)
    if not sheets or not any(sheet['nrows'] for sheet in sheets):
        raise PreviewError("В таблице нет ни одной заполненной строки.")
    return sheets


# ═══════════════════════════════════════════════════════════════════════════
# 3. PDF И КАРТИНКИ
# ═══════════════════════════════════════════════════════════════════════════
def pdf_info(blob):
    """Страницы и защита паролем. Сам PDF рисует pdf.js, нам нужен только счёт."""
    try:
        try:
            from pypdf import PdfReader
        except ImportError:
            from PyPDF2 import PdfReader
    except ImportError:                                    # pragma: no cover
        return {'pages': None, 'encrypted': False}
    try:
        reader = PdfReader(io.BytesIO(blob), strict=False)
        encrypted = bool(getattr(reader, 'is_encrypted', False))
        if encrypted:
            # Половина «защищённых» счетов закрыта пустым паролем — такие
            # pdf.js открывает молча, и пугать человека замком незачем.
            try:
                encrypted = not reader.decrypt('')
            except Exception:
                encrypted = True
        return {'pages': None if encrypted else len(reader.pages),
                'encrypted': encrypted}
    except Exception as exc:
        raise PreviewError("Файл PDF повреждён и не открывается: %s"
                           % str(exc).split('\n')[0][:120])


def image_info(blob):
    """Размер картинки. Pillow читает только заголовок, пиксели не разжимает."""
    try:
        from PIL import Image
    except ImportError:                                    # pragma: no cover
        return {}
    try:
        with Image.open(io.BytesIO(blob)) as image:
            return {'width': image.width, 'height': image.height}
    except Exception as exc:
        raise PreviewError("Картинка повреждена и не открывается: %s"
                           % str(exc).split('\n')[0][:120])


# ═══════════════════════════════════════════════════════════════════════════
# 4. ПОХОЖЕ ЛИ ЭТО НА ПРАЙС
# ═══════════════════════════════════════════════════════════════════════════
# Заголовок таблицы узнаём по двум признакам сразу: колонка с ценой и колонка
# с названием. Одной цены мало — цена есть и в счёте, и в акте.
PRICE_WORDS = ('цена', 'цены', 'стоимость', 'прайс', 'руб', '₽', 'price')
NAME_WORDS = ('наименование', 'номенклатура', 'товар', 'позиция', 'профиль',
              'размер', 'материал', 'продукция', 'сортамент', 'описание',
              'наимен', 'name')
# Колонки, которые к названию не относятся, хотя слово в них есть.
NOT_NAME_WORDS = ('марка стали', 'цена', 'стоимость', 'вес', 'масса', 'длина',
                  'кол-во', 'количество', 'ед.', 'единиц', 'остаток', 'наличие')

HEADER_SEARCH_ROWS = 60
_NUMBER_RE = re.compile(r'^\d[\d\s]*(?:[.,]\d+)?$')


def _is_number(text):
    return bool(_NUMBER_RE.match((text or '').strip()))


def find_price_header(rows):
    """Найти строку заголовка прайса. Возвращает dict или None."""
    for index, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        lowered = [(cell or '').strip().lower() for cell in row]
        price_cols = [i for i, cell in enumerate(lowered)
                      if cell and any(word in cell for word in PRICE_WORDS)]
        name_cols = [i for i, cell in enumerate(lowered)
                     if cell and any(word in cell for word in NAME_WORDS)
                     and not any(bad in cell for bad in NOT_NAME_WORDS)]
        if not price_cols or not name_cols:
            continue
        # Колонки названия — те, что левее первой цены: справа от цены обычно
        # вес и цена за штуку, и в название они не входят.
        price_col = price_cols[0]
        name_cols = [i for i in name_cols if i < price_col] or name_cols[:1]
        return {'header_row': index, 'price_column': price_col,
                'name_columns': name_cols}
    return None


def price_rows(rows, header):
    """Строки прайса: (название, строка листа). Заголовки разделов — в префикс.

    Вид проката в прайсах сплошь и рядом стоит только в шапке раздела
    («Труба электросварная»), а в строке остаётся один размер. Без раздела
    такая строка не разбирается вовсе, поэтому раздел запоминаем и пробуем
    им дополнить название.
    """
    price_col = header['price_column']
    name_cols = header['name_columns']
    out = []
    # Заголовок ПЕРВОГО раздела стоит выше шапки таблицы: у Металлсервиса это
    # «Труба водогазопроводная ГОСТ 3262-75» строкой раньше «Профиль | Размер».
    # Без этого взгляда назад первый раздел прайса теряется целиком.
    section = ''
    for index in range(header['header_row'] - 1, -1, -1):
        row = rows[index]
        filled = [i for i, cell in enumerate(row) if (cell or '').strip()]
        if len(filled) == 1 and filled[0] in name_cols and len(row[filled[0]].strip()) > 3:
            section = row[filled[0]].strip()
            break
    for index in range(header['header_row'] + 1, len(rows)):
        row = rows[index]
        filled = [i for i, cell in enumerate(row) if (cell or '').strip()]
        price = row[price_col].strip() if len(row) > price_col else ''
        name = ' '.join(row[i].strip() for i in name_cols
                        if len(row) > i and row[i].strip())
        if not _is_number(price):
            # Одинокая ячейка слева — это заголовок раздела, а не позиция.
            if len(filled) == 1 and filled[0] in name_cols and len(row[filled[0]]) > 3:
                section = row[filled[0]].strip()
            continue
        if not name:
            continue
        out.append((name, section, index))
    return out


_MATCHER_CACHE = []


def _matcher_module():
    """Разборщик названий из pmk_bridge — именно импортом, а не копией.

    Две копии правил разъезжаются молча, и разойдутся они на цене. Сам
    load_prices.py импортировать нельзя: он скрипт и на импорте проверяет,
    что запущен не на боевой базе.
    """
    # Ответ запоминается один раз на процесс — и «нашли», и «не нашли».
    # Правила между письмами не меняются, а поиск несуществующего модуля
    # пишет предупреждение в журнал: на каждое открытие вложения это мусор.
    # Разложили pmk_bridge — Odoo всё равно перезапускается при деплое.
    if not _MATCHER_CACHE:
        _MATCHER_CACHE.append(_import_matcher())
    return _MATCHER_CACHE[0]


def _import_matcher():
    try:
        from odoo.addons.pmk_bridge.tools.vendor import match
        return match
    except Exception:
        # Не только ImportError: этот импорт поднимает весь пакет pmk_bridge
        # с его моделями, и сломаться там может что угодно. Почта из-за
        # соседнего модуля падать не должна — просто останется без сводки.
        pass
    # Запасной путь: каталог tools/ не пакет (в нём нет __init__.py), и на
    # части сборок обычный импорт до него не достаёт.
    try:
        import importlib.util
        from odoo.modules.module import get_module_path
        base = get_module_path('pmk_bridge')
        if not base:
            return None
        path = os.path.join(base, 'tools', 'vendor', 'match.py')
        if not os.path.exists(path):
            return None
        spec = importlib.util.spec_from_file_location('pmk_price_match', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        _logger.exception("Mail Client: разборщик названий не загрузился")
        return None


def build_reference(env):
    """Справочник металла из базы: те же ключи, что у загрузчика цен.

    Ключ позиции — имя её внешнего идентификатора без модуля: по нему
    загрузчик находит карточку товара. Сводка обязана считать теми же
    ключами, иначе «узнано 417» и «залито 417» окажутся про разные строки.
    """
    profiles, sheets = [], []
    records = env['pmk.metal.profile'].sudo().search([], order='id')
    external = records.get_external_id()
    for record in records:
        xmlid = external.get(record.id)
        if xmlid:
            profiles.append({'id': xmlid.split('.', 1)[1], 'type': record.profile_type,
                             'size': record.size_label, 'gost': record.gost,
                             'mass': record.mass_per_meter})
    records = env['pmk.metal.sheet'].sudo().search([], order='id')
    external = records.get_external_id()
    for record in records:
        xmlid = external.get(record.id)
        if xmlid:
            sheets.append({'id': xmlid.split('.', 1)[1], 'type': record.sheet_type,
                           'th': record.thickness_mm, 'gost': record.gost,
                           'mass': record.mass_per_sqm})
    return {'profiles': profiles, 'sheets': sheets}


# Насколько далеко разбор продвинулся. Из двух попыток берём ту, что дошла
# дальше: «размера нет в справочнике» — это уже понятая позиция, которой у нас
# просто нет, а «вид не опознан» — непонятая строка. Смешивать их нельзя:
# первое заводит номенклатуру, второе чинит разбор.
STATUS_RANK = {
    'совпало': 6,
    'неоднозначно': 5,
    'размера нет в справочнике': 4,
    'толщины нет в справочнике': 4,
    'вида нет в справочнике': 3,
    'размер не найден': 2,
    'толщина не найдена': 2,
    'вид не опознан': 1,
    'не разобрано': 0,
}


def summarize_price(rows, header, matcher):
    """Сводка: сколько строк, сколько узнано, сколько нет и почему."""
    from collections import Counter
    statuses = Counter()
    unknown = []
    matched = 0
    items = price_rows(rows, header)
    for name, section, _index in items:
        result = matcher.match(name)
        if result['status'] != 'совпало' and section:
            # Вторая попытка с разделом: «Квадратная 40 х 40 х 2» сама по себе
            # не значит ничего, а «Труба профильная квадратная 40 х 40 х 2» —
            # уже позиция справочника.
            with_section = matcher.match('%s %s' % (section, name))
            if (STATUS_RANK.get(with_section['status'], 0)
                    > STATUS_RANK.get(result['status'], 0)):
                result = with_section
        statuses[result['status']] += 1
        if result['status'] == 'совпало':
            matched += 1
        elif len(unknown) < 10:
            unknown.append({'name': name, 'status': result['status']})
    return {
        'rows': len(items),
        'matched': matched,
        'unmatched': len(items) - matched,
        'by_status': dict(statuses),
        'unknown': unknown,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 5. МОДЕЛЬ
# ═══════════════════════════════════════════════════════════════════════════
class MailClientAttachment(models.Model):
    _inherit = 'mail.client.attachment'

    # ------------------------------------------------------------------
    # байты
    # ------------------------------------------------------------------
    def _preview_bytes(self):
        """Содержимое вложения. Скачивается с IMAP один раз, дальше из базы."""
        self.ensure_one()
        estimated = self._decoded_size()
        if estimated > MAX_FETCH_BYTES:
            raise PreviewError(
                "Вложение весит около %s — столько в память не берём. Файл можно скачать."
                % _mb(estimated))
        attachment = self.attachment_id if self.state == 'fetched' else False
        # «Скачано», но ir.attachment уже удалён (ondelete='set null' в модуле):
        # тогда качаем заново, а не показываем пустоту.
        if not attachment:
            attachment = self._fetch()
        if not attachment:
            raise PreviewError("Вложение не удалось получить с почтового сервера.")
        return attachment.sudo().raw or b''

    def _decoded_size(self):
        """Размер после раскодирования. BODYSTRUCTURE сообщает размер В ПИСЬМЕ,
        а base64 раздувает файл на треть — сравнивать пределы надо с исходным."""
        size = self.file_size or 0
        if (self.encoding or '').lower() == 'base64':
            return int(size * 0.75)
        return size

    # ------------------------------------------------------------------
    # просмотр
    # ------------------------------------------------------------------
    @api.model
    def preview(self, attachment_id, sheet=0, offset=0, limit=None):
        """Что показать вместо кнопки «скачать».

        Ответ всегда один и тот же по форме: вид файла, чем его показывать и
        по возможности содержимое. Ошибка разбора — это тоже ответ с полем
        error, а не исключение: сорванный разбор чужого файла не повод
        показывать человеку окно с трейсбеком.
        """
        record = self.browse(attachment_id).exists()
        if not record:
            raise UserError("Это вложение больше не существует.")
        record.message_id.check_access('read')
        record = record.sudo()

        payload = {
            'id': record.id,
            'name': record.name,
            'size': record._decoded_size(),
            'content_type': record.content_type or '',
            'kind': 'other',
            'format': 'other',
            'note': '',
            'error': '',
            'url': '/mail_client/attachment/%s/raw' % record.id,
            'download_url': '',
        }
        try:
            blob = record._preview_bytes()
            payload['download_url'] = ('/web/content/%s?download=true'
                                       % record.attachment_id.id)
            payload['size'] = len(blob)
            fmt, kind, note = detect_format(blob, record.name)
            payload.update({'format': fmt, 'kind': kind, 'note': note})

            if kind == 'sheet':
                payload.update(record._preview_sheet(blob, fmt, sheet, offset, limit))
            elif kind == 'doc':
                payload.update(pdf_info(blob))
            elif kind == 'image':
                payload.update(image_info(blob))
            elif kind == 'cad2d':
                payload['note'] = (payload['note'] + ' ' if payload['note'] else '') + \
                    "Чертёж DXF в системе не рисуется — файл можно скачать."
            else:
                payload['note'] = (payload['note'] + ' ' if payload['note'] else '') + \
                    "Этот вид файла в системе не показывается — его можно скачать."
        except PreviewError as exc:
            payload['error'] = str(exc)
        except UserError as exc:
            # Сюда попадает отказ IMAP из _fetch вендорского модуля.
            payload['error'] = str(exc)
        except Exception:
            # Файл пришёл от постороннего: сломать разбор может что угодно, и
            # падать из-за чужого файла почта не должна. Трейсбек — в журнал.
            _logger.exception("Mail Client: разбор вложения %s не удался", attachment_id)
            payload['error'] = "Файл не удалось разобрать. Его можно скачать."
        return payload

    def _preview_sheet(self, blob, fmt, sheet_index, offset, limit):
        """Листы таблицы плюс страница строк и сводка по прайсу."""
        self.ensure_one()
        sheets = read_sheets(blob, fmt)
        sheet_index = max(0, min(int(sheet_index or 0), len(sheets) - 1))
        offset = max(0, int(offset or 0))
        limit = min(int(limit or PAGE_ROWS), PAGE_ROWS_MAX)
        current = sheets[sheet_index]

        out = {
            'sheets': [{'index': index, 'name': item['name'], 'rows': item['nrows'],
                        'cols': item['ncols'], 'truncated': item['truncated']}
                       for index, item in enumerate(sheets)],
            'page': {'sheet': sheet_index, 'offset': offset, 'limit': limit,
                     'rows': current['rows'][offset:offset + limit]},
            'price': None,
        }
        if offset == 0:
            # Сводка считается по всему листу, поэтому только на первой
            # странице: листать таблицу не значит пересчитывать прайс.
            out['price'] = self._price_summary(current)
        return out

    def _price_summary(self, sheet):
        """Прайс это или нет, и что из него система узнала."""
        header = find_price_header(sheet['rows'])
        if not header:
            return {'is_price': False,
                    'reason': "В таблице не нашлось колонок «наименование» и «цена» — "
                              "на прайс не похоже."}
        summary = {'is_price': True,
                   'header_row': header['header_row'] + 1,
                   'price_column': header['price_column'],
                   'name_columns': header['name_columns'],
                   'rows': 0, 'matched': 0, 'unmatched': 0,
                   'by_status': {}, 'unknown': [], 'error': ''}

        module = _matcher_module()
        if module is None:
            summary['error'] = ("Разбор прайса недоступен: на сервере нет модуля "
                                "pmk_bridge с правилами разбора названий.")
            return summary
        try:
            reference = build_reference(self.env)
        except KeyError:
            summary['error'] = ("Справочник металла недоступен: модуль pmk_calc "
                                "не установлен на этом сервере.")
            return summary
        if not reference['profiles'] and not reference['sheets']:
            summary['error'] = "Справочник металла пуст — сверять строки не с чем."
            return summary

        summary.update(summarize_price(sheet['rows'], header, module.Matcher(reference)))
        summary['reference'] = {'profiles': len(reference['profiles']),
                                'sheets': len(reference['sheets'])}
        # Колонки «наименование» и «цена» есть и у прайса на услуги резки, и у
        # счёта. Отличает их доля узнанного: если из тридцати строк узнались
        # четыре, это не наш металл, и человеку лучше сказать это прямо, чем
        # оставить его гадать, почему так мало.
        if summary['rows'] >= 10 and summary['matched'] < summary['rows'] * 0.15:
            summary['note'] = ("Узнано меньше шестой части строк — похоже, это не "
                               "прайс на металлопрокат.")
        return summary

    @api.model
    def price_scan(self, attachment_id, sheet=0):
        """Только сводка по прайсу — для повторного пересчёта без страницы строк."""
        record = self.browse(attachment_id).exists()
        if not record:
            raise UserError("Это вложение больше не существует.")
        record.message_id.check_access('read')
        record = record.sudo()
        try:
            blob = record._preview_bytes()
            fmt, kind, _note = detect_format(blob, record.name)
            if kind != 'sheet':
                return {'is_price': False,
                        'reason': "Это не таблица, а %s."
                                  % FORMAT_TITLE.get(fmt, 'другой файл')}
            sheets = read_sheets(blob, fmt)
            index = max(0, min(int(sheet or 0), len(sheets) - 1))
            return record._price_summary(sheets[index])
        except PreviewError as exc:
            return {'is_price': False, 'reason': str(exc)}
        except UserError as exc:
            return {'is_price': False, 'reason': str(exc)}
        except Exception:
            _logger.exception("Mail Client: разбор прайса %s не удался", attachment_id)
            return {'is_price': False,
                    'reason': "Файл не удалось разобрать. Его можно скачать."}
