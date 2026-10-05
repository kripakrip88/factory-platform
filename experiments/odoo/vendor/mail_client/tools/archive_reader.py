# -*- coding: utf-8 -*-
# ПРАВКА ПМК (шаг 45 разбора удобства, 05.10.2026) к вендорскому модулю mail_client.
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""Архив ZIP из письма: список файлов и ОДИН файл в память — и ничего на диск.

ЗАЧЕМ
Поставщики шлют чертежи и прайсы архивом. Чтобы посмотреть один PDF, человек
скачивал архив, распаковывал его и искал файл в папке «Загрузки». Окно
просмотра вложений (models/mail_client_attachment_preview.py) теперь
показывает список файлов архива и открывает PDF, таблицу или картинку прямо
из него.

ПОЧЕМУ ВСЁ В ПАМЯТИ И ПО ОДНОМУ ФАЙЛУ
Архив пришёл от постороннего. Распаковка на диск — это пути «../../etc» и
«C:\\Windows», ссылки, тысячи файлов и терабайты нулей. Здесь распаковки нет
вовсе: читается оглавление, а по запросу — байты ОДНОГО файла, в память, с
потолком. Путь из архива никогда не становится путём на диске — значит, и
выйти за пределы папки ему некуда. extract() и extractall() не используются,
временных файлов нет.

ЗАЩИТЫ (числа — в разделе «ПРЕДЕЛЫ»)
- Число файлов и размер оглавления проверяются ПО КОНЦУ АРХИВА, ещё до разбора
  оглавления: zipfile строит объект на каждую запись, и архив на миллион
  записей съел бы сотни мегабайт рабочего процесса раньше любой проверки.
  Конец архива ищет функция самого zipfile (directory_info) — ровно те числа,
  по которым он потом читает оглавление.
- Распакованный размер одного файла — не больше 50 МБ; заявленный коэффициент
  сжатия — не больше 100 (для файлов крупнее 1 МБ: мелочь вроде пустого листа
  жмётся сильнее, и вреда от неё нет).
- Заявленному размеру не верим: распаковка идёт кусками и останавливается,
  как только вышло больше заявленного. Распаковщик свой (zlib, bz2, lzma с
  пределом выдачи), а не ZipExtFile: тот у bzip2 и lzma разжимает кусок
  входа целиком, и 4 КБ bzip2 разворачиваются в гигабайты за один вызов —
  раньше, чем дойдёт до проверки.
- Словарь LZMA — не больше распакованного файла: заявленный в архиве словарь
  на 4 ГБ liblzma выделил бы целиком ещё до первого байта (см. _lzma).
- Наложение записей (одни и те же сжатые байты под многими именами — так
  устроены «бомбы» Фифилда) — отказ на весь архив.
- Зашифрованный файл и незнакомый способ сжатия — понятный отказ, а не
  трейсбек; повреждённый архив — тоже.
- Контрольная сумма каждого прочитанного файла сверяется.

ИМЕНА ФАЙЛОВ
Стандарт ZIP знает две кодировки имён: флаг UTF-8 или «как в DOS» (cp437).
Русская Windows (Проводник, WinRAR, 7-Zip) пишет без флага в своей «DOS»
кодировке cp866 — оттуда кракозябры «Б╤хЄ.pdf» у всех, кто читает по
стандарту. Порядок разбора — в member_name().

Модуль без импортов Odoo: его гоняют обычным python на собранных в тесте
архивах (tests/test_step45_archive.py).
"""
import bz2
import io
import lzma
import re
import struct
import unicodedata
import zipfile
import zlib


# ═══════════════════════════════════════════════════════════════════════════
# ПРЕДЕЛЫ
# ═══════════════════════════════════════════════════════════════════════════
# Файлов в архиве. Архив чертежей заказа — десятки файлов, выгрузка
# документов за год — сотни. 5000 — с запасом на любой рабочий случай.
MAX_ENTRIES = 5000
# Размер оглавления: 5000 записей с длинными русскими путями — около 2 МБ.
MAX_DIRECTORY_BYTES = 4 * 1024 * 1024
# Строк списка, которые уходят в окно за раз: дальше человек всё равно не
# листает, а ответ на 5000 строк весит мегабайт.
LIST_ROWS = 1000
# Распакованный файл — как предел вложения в письме (MAX_FETCH_BYTES).
MEMBER_MAX_BYTES = 50 * 1024 * 1024
# Во сколько раз файл может быть сжат. Таблицы и тексты жмутся в 5–20 раз,
# сжатое (xlsx, pdf, jpg) — почти никак. «Бомба» — в тысячи раз.
MEMBER_MAX_RATIO = 100
RATIO_FROM = 1024 * 1024
# Выше этого распакованный объём архива только подписывается: файлы всё
# равно открываются по одному.
WARN_TOTAL = 2 * 1024 * 1024 * 1024
# Кусок входа на один шаг распаковки.
READ_CHUNK = 1024 * 1024
# Наименьший словарь LZMA (LZMA_DICT_SIZE_MIN в liblzma).
LZMA_DICT_FLOOR = 4096
# Книга Excel и OpenDocument — тоже zip. Сколько её частей вместе может весить
# в распакованном виде: книга на 25 МБ (предел разбора таблицы) — это около
# 250 МБ разметки XML.
BOOK_MAX_UNPACKED = 256 * 1024 * 1024

# Способы сжатия: без сжатия, deflate, bzip2, lzma.
STORED, DEFLATED, BZIP2, LZMA = 0, 8, 12, 14
SUPPORTED_METHODS = frozenset({STORED, DEFLATED, BZIP2, LZMA})

FLAG_ENCRYPTED = 0x1
FLAG_UTF8 = 0x800

# Служебные файлы архиваторов: в списке не показываются, только считаются.
JUNK_DIRS = ('__macosx',)
JUNK_NAMES = frozenset({'.ds_store', 'thumbs.db', 'desktop.ini'})


class ArchiveError(Exception):
    """Понятная человеку причина отказа. status — код ответа контроллера."""

    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


def _mb(size):
    if size >= 1024 ** 3:
        return ('%.1f ГБ' % (size / 1024.0 ** 3)).replace('.', ',')
    return ('%.1f МБ' % (size / 1024.0 / 1024.0)).replace('.', ',')


BROKEN = ("Архив повреждён и не открывается. Скачайте его — архиватор на "
          "компьютере, возможно, достанет файлы.")
OVERLAP = ("Записи архива наложены друг на друга — так устроены поддельные "
           "архивы-«бомбы». Открывать его не будем.")


# ═══════════════════════════════════════════════════════════════════════════
# 1. ВИД АРХИВА И ОГЛАВЛЕНИЕ ПО КОНЦУ ФАЙЛА
# ═══════════════════════════════════════════════════════════════════════════
def archive_format(blob):
    """'zip', 'rar', '7z' по сигнатуре или None."""
    head = bytes(blob[:8])
    if head.startswith((b'PK\x03\x04', b'PK\x05\x06')):
        return 'zip'
    if head.startswith((b'Rar!\x1a\x07\x00', b'Rar!\x1a\x07\x01\x00')):
        return 'rar'
    if head.startswith(b'7z\xbc\xaf\x27\x1c'):
        return '7z'
    return None


# Запись конца архива (EOCD) ищет и читает функция САМОГО zipfile — та же, по
# которой ZipFile() потом возьмёт размер оглавления и прочтёт его. Своя копия
# поиска расходилась с ней (окно поиска на байт короче; метка Zip64 без записи
# Zip64 обнуляла числа, а zipfile читает оглавление по 32-битным полям; саму
# запись Zip64 разные сборки Python ищут по-разному — в контейнере odoo-app
# стоит 3.12.3 Ubuntu с поправками из новых версий), и каждое расхождение
# было дорогой в обход проверки. Функция внутренняя, но есть в zipfile всех
# нынешних версий Python 3; пропадёт при обновлении Python — архивы перестанут
# открываться («повреждён»), а не откроются без проверки, и это сразу покажет
# тест test_zipfile_end_record_api.
_END_RECORD = getattr(zipfile, '_EndRecData', None)
_ECD_ENTRIES_TOTAL = getattr(zipfile, '_ECD_ENTRIES_TOTAL', 4)
_ECD_SIZE = getattr(zipfile, '_ECD_SIZE', 5)


def directory_info(blob):
    """Число записей и размер оглавления — те самые, что возьмёт zipfile.

    Возвращает {'entries', 'size'} или None — конца архива нет, и ZipFile()
    такой архив не откроет тоже (он ищет его той же функцией). Метка Zip64
    без настоящей записи Zip64 не прячет чисел: zipfile в этом случае читает
    оглавление по 32-битным полям — их и проверяем (0xFFFF записей, 4 ГБ
    оглавления — отказ). Оглавление при этом не разбирается вовсе — в этом
    весь смысл.
    """
    if _END_RECORD is None:
        return None
    try:
        endrec = _END_RECORD(io.BytesIO(blob))
    except (zipfile.BadZipFile, OSError, ValueError, EOFError, struct.error):
        return None
    if not endrec:
        return None
    return {'entries': endrec[_ECD_ENTRIES_TOTAL], 'size': endrec[_ECD_SIZE]}


def _too_many(count):
    return ArchiveError(
        "Файлов в архиве: %s — список длиннее %d здесь не показываем. Скачайте "
        "архив и откройте его на компьютере." % (count, MAX_ENTRIES), 413)


def _times(number):
    """«в 100 раз», «в 1023 раза»."""
    if number % 10 in (2, 3, 4) and number % 100 not in (12, 13, 14):
        return '%d раза' % number
    return '%d раз' % number


def _open(blob):
    """ZipFile и записи — после проверки по концу архива и на наложение."""
    info = directory_info(blob)
    if info is None:
        # Конца архива нет — ZipFile() его не найдёт тоже. Не зовём его вовсе:
        # отказ тот же, а разбирать нечего.
        raise ArchiveError(BROKEN)
    if info['entries'] > MAX_ENTRIES:
        raise _too_many(info['entries'])
    if info['size'] > MAX_DIRECTORY_BYTES:
        raise ArchiveError(
            "Оглавление архива весит %s — такой длинный список здесь не "
            "показываем. Скачайте архив." % _mb(info['size']), 413)
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
    except (zipfile.BadZipFile, OSError, ValueError, EOFError, struct.error,
            NotImplementedError, RuntimeError, KeyError, IndexError) as exc:
        # ValueError — это и UnicodeDecodeError: флаг UTF-8 при битом имени.
        raise ArchiveError(BROKEN) from exc
    infos = archive.infolist()
    # Число записей в конце архива можно подделать — пересчитываем по факту.
    # Память к этому моменту ограничена размером оглавления выше.
    if len(infos) > MAX_ENTRIES:
        archive.close()
        raise _too_many(len(infos))
    if _overlaps(infos, getattr(archive, 'start_dir', None)):
        archive.close()
        raise ArchiveError(OVERLAP)
    return archive, infos


def _raw_name(info):
    """Байты имени, как они записаны в архиве."""
    encoding = 'utf-8' if info.flag_bits & FLAG_UTF8 else 'cp437'
    return info.orig_filename.encode(encoding)


def _overlaps(infos, directory_start):
    """Записи наложены друг на друга или заходят на оглавление.

    Длина записи считается снизу (заголовок + имя + сжатые данные, без поля
    extra локального заголовка), поэтому честный архив отказа не получит.
    """
    spans = sorted(
        (info.header_offset, info.header_offset + 30 + len(_raw_name(info)) + info.compress_size)
        for info in infos)
    for (_start, end), (next_start, _next_end) in zip(spans, spans[1:]):
        if next_start < end:
            return True
    return bool(spans and directory_start is not None and spans[-1][1] > directory_start)


# ═══════════════════════════════════════════════════════════════════════════
# 2. ИМЕНА И ПУТИ
# ═══════════════════════════════════════════════════════════════════════════
def _extra_fields(extra):
    fields = {}
    while len(extra) >= 4:
        kind, length = struct.unpack('<HH', extra[:4])
        fields[kind] = extra[4:4 + length]
        extra = extra[4 + length:]
    return fields


def member_name(info):
    """Имя файла без кракозябр.

    1. Флаг UTF-8 — имя как есть (сам Python, 7-Zip, macOS, Windows 11).
    2. Поле Info-ZIP «Unicode Path» (0x7075) с контрольной суммой исходного
       имени — его пишут 7-Zip, WinRAR и zip из Linux. Разбираем сами:
       Python понимает это поле не во всех версиях (3.11 — нет, 3.12 — да).
    3. Только латиница — как есть.
    4. Ни одного байта псевдографики cp866 (B0–DF) — это cp866, русские имена
       из Проводника, WinRAR и 7-Zip под русской Windows. В cp866 русские
       буквы лежат в 80–AF и E0–F1, а в B0–DF — рамки и уголки, которых в
       именах файлов не бывает. У русского в UTF-8 ведущие байты D0/D1 —
       как раз в B0–DF, поэтому UTF-8 за cp866 не примется.
    5. UTF-8 без флага (старый macOS, zip из Linux).
    6. Запасной путь — cp437, как велит стандарт.
    """
    if info.flag_bits & FLAG_UTF8:
        return info.orig_filename
    raw = _raw_name(info)
    unicode_path = _extra_fields(info.extra).get(0x7075)
    if (unicode_path and len(unicode_path) > 5 and unicode_path[0] == 1
            and struct.unpack('<L', unicode_path[1:5])[0] == zlib.crc32(raw)):
        try:
            return unicode_path[5:].decode('utf-8')
        except UnicodeDecodeError:
            pass
    if raw.isascii():
        return raw.decode('ascii')
    if not any(0xB0 <= byte <= 0xDF for byte in raw):
        return raw.decode('cp866')
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('cp437')


# Управляющие символы направления письма: с ними «счёт‮fdp.exe» на экране
# читается как «счётexe.pdf». В имени файла им делать нечего.
_BIDI = dict.fromkeys(map(ord, '\u200e\u200f\u061c\u202a\u202b\u202c\u202d\u202e'
                               '\u2066\u2067\u2068\u2069'))
_DRIVE = re.compile(r'^[A-Za-z]:')
WARN_UP = "путь вёл за пределы архива"
WARN_ROOT = "путь от корня диска"


def clean_path(name):
    """Путь для показа: {path, dir, name, warn}.

    Обратная косая — разделитель папок (так пишет Windows); буква диска,
    ведущая косая, «.» и «..» выбрасываются. «..» и путь от корня — не повод
    молчать: такой путь в честном архиве не встречается, поэтому строка
    получает пометку warn. Опасности в нём нет — на диск ничего не пишется.
    """
    text = (name or '').replace('\\', '/')
    text = ''.join(ch for ch in text if unicodedata.category(ch) != 'Cc').translate(_BIDI)
    warn = ''
    if _DRIVE.match(text):
        text = text[2:]
        warn = WARN_ROOT
    if text.startswith('/'):
        warn = warn or WARN_ROOT
    parts = []
    for part in text.split('/'):
        if part in ('', '.'):
            continue
        if part == '..':
            warn = WARN_UP
            continue
        parts.append(part)
    base = parts[-1] if parts else 'без имени'
    folder = '/'.join(parts[:-1])
    return {'path': '/'.join(parts) or base, 'dir': folder, 'name': base, 'warn': warn}


def _is_dir(info, name):
    return name.endswith(('/', '\\')) or info.is_dir()


def _is_junk(meta):
    first = meta['path'].split('/', 1)[0].lower()
    base = meta['name'].lower()
    return first in JUNK_DIRS or base.startswith('._') or base in JUNK_NAMES


_DIGITS = re.compile(r'([0-9]+)')


def _natural(text):
    """Ключ «как в Проводнике»: «Лист 2» раньше «Лист 10», регистр не важен.

    Число сравнивается длиной и цифрами, а не через int(): имя из пяти тысяч
    цифр int() не переварит (предел длины числа в Python 3.11+).
    """
    key = []
    for part in _DIGITS.split(text):
        if not part:
            continue
        if part[0] in '0123456789':
            digits = part.lstrip('0') or '0'
            key.append((0, len(digits), digits))
        else:
            key.append((1, 0, part.casefold()))
    return tuple(key)


def _sort_key(entry):
    folders = tuple(_natural(part) for part in entry['dir'].split('/')) if entry['dir'] else ()
    return (folders, _natural(entry['name']), entry['index'])


def _date(info):
    """Дата из архива «дд.мм.гггг чч:мм». 01.01.1980 — «даты нет» у ZIP."""
    year, month, day, hour, minute = info.date_time[:5]
    if year <= 1980 and month <= 1 and day <= 1 and not hour and not minute:
        return ''
    if not (1 <= month <= 12 and 1 <= day <= 31 and 0 <= hour < 24 and 0 <= minute < 60):
        return ''
    return '%02d.%02d.%04d %02d:%02d' % (day, month, year, hour, minute)


# ═══════════════════════════════════════════════════════════════════════════
# 3. ОТКАЗЫ
# ═══════════════════════════════════════════════════════════════════════════
ENCRYPTED = ("Файл «%s» закрыт паролем. Скачайте архив и откройте его "
             "архиватором — он спросит пароль.")


def _refusal(info):
    """(коротко для строки списка, полностью для окна, код) или None."""
    if info.flag_bits & FLAG_ENCRYPTED:
        return ("закрыт паролем", ENCRYPTED, 422)
    if info.compress_type not in SUPPORTED_METHODS:
        return ("сжат неизвестным способом",
                "Файл «%s» сжат способом, которого система не знает. Скачайте "
                "архив и откройте его на компьютере.", 422)
    if info.file_size > MEMBER_MAX_BYTES:
        return ("больше %s" % _mb(MEMBER_MAX_BYTES),
                "Файл «%%s» весит %s в распакованном виде — больше предела %s. "
                "Скачайте архив целиком." % (_mb(info.file_size), _mb(MEMBER_MAX_BYTES)), 413)
    if info.file_size > RATIO_FROM and info.file_size > MEMBER_MAX_RATIO * info.compress_size:
        ratio = _times(info.file_size // max(info.compress_size, 1))
        return ("сжат в %s — похоже на подделку" % ratio,
                "Файл «%%s» сжат в %s — так бывает у поддельных архивов-«бомб». "
                "Открывать не будем; если файл нужен, скачайте архив." % ratio, 413)
    return None


# ═══════════════════════════════════════════════════════════════════════════
# 4. СПИСОК
# ═══════════════════════════════════════════════════════════════════════════
def _entry(index, info, meta):
    refusal = _refusal(info)
    return {
        'index': index,
        'path': meta['path'],
        'dir': meta['dir'],
        'name': meta['name'],
        'size': info.file_size,
        'date': _date(info),
        'reason': refusal[0] if refusal else '',
        'warn': meta['warn'],
    }


def list_zip(blob):
    """Список файлов архива для окна просмотра.

    {entries: [{index, path, dir, name, size, date, reason, warn}],
     total, size, encrypted, hidden, notes}

    index — номер записи в архиве (по нему открывается файл); entries — не
    больше LIST_ROWS строк, total — сколько файлов всего; size — сумма
    ЗАЯВЛЕННЫХ распакованных размеров; hidden — сколько служебных файлов
    архиватора скрыто; notes — оговорки к архиву целиком.
    """
    archive, infos = _open(blob)
    with archive:
        files, hidden, encrypted, total_size = [], 0, 0, 0
        for index, info in enumerate(infos):
            name = member_name(info)
            if _is_dir(info, name):
                continue
            meta = clean_path(name)
            if _is_junk(meta):
                hidden += 1
                continue
            if info.flag_bits & FLAG_ENCRYPTED:
                encrypted += 1
            total_size += info.file_size
            files.append(_entry(index, info, meta))
    files.sort(key=_sort_key)

    total = len(files)
    notes = []
    if total and encrypted == total:
        notes.append("Архив закрыт паролем: список файлов виден, открыть их здесь "
                     "нельзя. Скачайте архив и откройте архиватором — он спросит пароль.")
    elif encrypted:
        notes.append("Файлов под паролем: %d — их здесь не открыть, только скачать "
                     "архив целиком." % encrypted)
    if total > LIST_ROWS:
        notes.append("Показано файлов: %d из %d." % (LIST_ROWS, total))
    if total_size > WARN_TOTAL:
        notes.append("Распакованный объём — %s: файлы открываются только по одному."
                     % _mb(total_size))
    return {
        'entries': files[:LIST_ROWS],
        'total': total,
        'size': total_size,
        'encrypted': encrypted,
        'hidden': hidden,
        'notes': notes,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 5. ОДИН ФАЙЛ
# ═══════════════════════════════════════════════════════════════════════════
class _Overflow(Exception):
    pass


class _Corrupt(Exception):
    pass


def _inflate(data, cap):
    """deflate кусками; выдача не больше cap + 1 байт."""
    decomp = zlib.decompressobj(-zlib.MAX_WBITS)
    out = bytearray()
    pos, tail = 0, b''
    while not decomp.eof:
        if not tail:
            if pos >= len(data):
                break
            tail = data[pos:pos + READ_CHUNK]
            pos += len(tail)
        before = len(tail)
        piece = decomp.decompress(tail, cap + 1 - len(out))
        tail = decomp.unconsumed_tail
        out += piece
        if len(out) > cap:
            raise _Overflow()
        if not piece and len(tail) == before:
            raise _Corrupt()
    if not decomp.eof and not tail:
        # Вход кончился без конца потока: дочищаем то, что zlib держит в себе
        # (не больше окна), а целостность решит контрольная сумма.
        out += decomp.flush()
        if len(out) > cap:
            raise _Overflow()
    return out


def _drain(decomp, data, cap):
    """bz2/lzma кусками; у них предел выдачи — max_length и needs_input."""
    out = bytearray()
    pos, stalls = 0, 0
    while not decomp.eof:
        if decomp.needs_input:
            if pos >= len(data):
                break
            chunk = data[pos:pos + READ_CHUNK]
            pos += len(chunk)
        else:
            chunk = b''
        piece = decomp.decompress(chunk, cap + 1 - len(out))
        out += piece
        if len(out) > cap:
            raise _Overflow()
        if piece or chunk:
            stalls = 0
        else:
            stalls += 1
            if stalls > 3:
                raise _Corrupt()
    return out


def _lzma(data, cap):
    """lzma в zip: 2 байта версии, 2 байта длины свойств, свойства, поток.

    Словарь распаковщика — не больше выдачи. Размер словаря записан в архиве
    (4 байта свойств), и liblzma выделяет его целиком при создании
    распаковщика: заявленные 4 ГБ — это MemoryError в рабочем процессе
    (у него предел адресного пространства) вместо понятного отказа. Словарь
    больше распакованного файла не нужен вовсе: ссылка назад дальше уже
    выданных байтов — порча, а выдаём мы не больше cap + 1 байт. Поэтому
    словарь урезается до выдачи, и результат тот же, байт в байт.
    """
    if len(data) < 4:
        raise _Corrupt()
    props_size = struct.unpack('<H', bytes(data[2:4]))[0]
    if len(data) < 4 + props_size:
        raise _Corrupt()
    lzma_filter = lzma._decode_filter_properties(lzma.FILTER_LZMA1, bytes(data[4:4 + props_size]))
    # 4096 — меньше словаря liblzma не бывает (LZMA_DICT_SIZE_MIN).
    lzma_filter['dict_size'] = min(lzma_filter.get('dict_size') or LZMA_DICT_FLOOR,
                                   max(cap + 1, LZMA_DICT_FLOOR))
    decomp = lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=[lzma_filter])
    return _drain(decomp, data[4 + props_size:], cap)


def _unpack(info, data, cap):
    if info.compress_type == STORED:
        if len(data) > cap:
            raise _Overflow()
        return bytes(data)
    if info.compress_type == DEFLATED:
        return bytes(_inflate(data, cap))
    if info.compress_type == BZIP2:
        return bytes(_drain(bz2.BZ2Decompressor(), data, cap))
    return bytes(_lzma(data, cap))


def _member_data(blob, info):
    """Сжатые байты записи — по её локальному заголовку, со сверкой имени."""
    offset = info.header_offset
    header = bytes(blob[offset:offset + 30])
    if len(header) < 30 or header[:4] != b'PK\x03\x04':
        raise _Corrupt()
    flags = struct.unpack('<H', header[6:8])[0]
    name_len, extra_len = struct.unpack('<HH', header[26:30])
    if bytes(blob[offset + 30:offset + 30 + name_len]) != _raw_name(info):
        # Имя в оглавлении и в самой записи расходятся — подделка или порча.
        raise _Corrupt()
    start = offset + 30 + name_len + extra_len
    data = memoryview(blob)[start:start + info.compress_size]
    if len(data) < info.compress_size:
        raise _Corrupt()
    return flags, data


def read_zip_member(blob, index):
    """(байты файла, строка списка) — один файл архива, в память, с пределом."""
    archive, infos = _open(blob)
    archive.close()
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(infos):
        raise ArchiveError("В архиве нет такого файла. Откройте архив заново.", 404)
    info = infos[index]
    name = member_name(info)
    meta = clean_path(name)
    if _is_dir(info, name):
        raise ArchiveError("Это папка архива, а не файл.", 404)
    refusal = _refusal(info)
    if refusal:
        raise ArchiveError(refusal[1] % meta['name'], refusal[2])

    cap = min(info.file_size, MEMBER_MAX_BYTES)
    broken = "Файл «%s» в архиве повреждён и не читается." % meta['name']
    try:
        flags, data = _member_data(blob, info)
        if flags & FLAG_ENCRYPTED:
            # Оглавление можно подделать, локальный заголовок — тоже: пароль
            # проверяем в обоих.
            raise ArchiveError(ENCRYPTED % meta['name'])
        payload = _unpack(info, data, cap)
    except _Overflow:
        raise ArchiveError(
            "Файл «%s» распаковывается больше заявленного размера — архив "
            "поддельный. Чтение остановлено." % meta['name'], 413) from None
    except (_Corrupt, zlib.error, lzma.LZMAError, OSError, EOFError, ValueError,
            LookupError, struct.error):
        raise ArchiveError(broken) from None
    except MemoryError:
        # Страховка: распаковщик не получил памяти (словарь LZMA урезан выше,
        # но рабочий процесс живёт под пределом адресного пространства).
        # Отказ словами, а не «500» у кнопки «Скачать».
        raise ArchiveError(
            "Файл «%s» не удалось распаковать: на сервере не хватило памяти. "
            "Скачайте архив целиком." % meta['name'], 413) from None
    if zlib.crc32(payload) & 0xFFFFFFFF != info.CRC:
        raise ArchiveError("Файл «%s» в архиве повреждён: контрольная сумма не "
                           "сходится." % meta['name'])
    return payload, _entry(index, info, meta)


# ═══════════════════════════════════════════════════════════════════════════
# 6. КНИГИ EXCEL И OPENDOCUMENT — ТОЖЕ ZIP
# ═══════════════════════════════════════════════════════════════════════════
def check_book(blob):
    """Проверка книги xlsx/ods ДО библиотеки, которая её разберёт.

    openpyxl и наше чтение ods берут части книги через zipfile. У deflate и
    «без сжатия» zipfile не выдаёт больше ЗАЯВЛЕННОГО размера части, поэтому
    сумма заявленных размеров и есть потолок памяти. У bzip2 и lzma такого
    потолка нет (см. шапку файла), а Excel и LibreOffice ими не пишут —
    книга с ними не открывается. Без этой проверки книга-«бомба» внутри
    архива (или просто во вложении) кладёт рабочий процесс.

    Возвращает None или текст отказа.
    """
    try:
        archive, infos = _open(blob)
    except ArchiveError as exc:
        if exc.status == 413:
            return "В книге слишком много частей — так её не разобрать. Файл можно скачать."
        return "Книга повреждена и не открывается."
    archive.close()
    total = 0
    for info in infos:
        if info.flag_bits & FLAG_ENCRYPTED:
            return "Книга закрыта паролем — показать её нечем. Файл можно скачать."
        if info.compress_type not in (STORED, DEFLATED):
            return "Книга сжата необычным способом — так её не разобрать. Файл можно скачать."
        total += info.file_size
    if total > BOOK_MAX_UNPACKED:
        return ("Книга в распакованном виде весит %s — больше предела %s. Файл можно скачать."
                % (_mb(total), _mb(BOOK_MAX_UNPACKED)))
    return None


def read_part_head(blob, name, limit):
    """Короткая часть `name` (mimetype книги OpenDocument) — для опознания вида.

    Без сжатия — первые limit байт. Сжатая — своим распаковщиком с потолком
    limit: больше limit + 1 байт в памяти не появится ни при каком заявленном
    размере; часть длиннее limit — None (mimetype столько не весит).
    Стандарт ODF велит класть mimetype без сжатия, но нестрогие программы
    сжимают и его, а LibreOffice такие книги открывает — значит, и мы должны
    узнать в них таблицу, а не показать список служебных XML.
    """
    try:
        archive, infos = _open(blob)
    except ArchiveError:
        return None
    archive.close()
    for info in infos:
        if info.orig_filename != name:
            continue
        if info.flag_bits & FLAG_ENCRYPTED or info.compress_type not in SUPPORTED_METHODS:
            return None
        try:
            _flags, data = _member_data(blob, info)
            if info.compress_type == STORED:
                return bytes(data[:limit])
            return _unpack(info, data, limit)
        except (_Overflow, _Corrupt, zlib.error, lzma.LZMAError, OSError, EOFError,
                ValueError, LookupError, struct.error, MemoryError):
            return None
    return None
