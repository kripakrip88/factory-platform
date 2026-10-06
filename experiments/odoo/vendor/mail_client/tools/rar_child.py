# -*- coding: utf-8 -*-
# ПРАВКА ПМК (шаг 45б разбора удобства, 06.10.2026) к вендорскому модулю mail_client.
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""Архив RAR в отдельном процессе: оглавление и ОДИН файл — и ничего больше.

Запускается из tools/archive_reader.py как `python3 -I -B rar_child.py …`.
Без импортов Odoo и без импортов своего пакета: при -I папка скрипта в путь
поиска не попадает. Числа пределов приходят аргументами — источник один,
раздел «ПРЕДЕЛЫ» archive_reader.py.

ПОЧЕМУ ОТДЕЛЬНЫЙ ПРОЦЕСС, А НЕ rarfile В РАБОЧЕМ ПРОЦЕССЕ ODOO
- RAR сжимает свой формат, Python его не разжимает: файл достаёт unrar, а он
  читает архив только по имени файла на диске. Значит, нужна копия архива во
  временной папке и чужая программа на чужих байтах — под пределами памяти,
  процессора и времени, которые не задеть рабочему процессу Odoo.
- Даже РАЗБОР оглавления rarfile запускает unrar: сжатый комментарий архива
  RAR4 (до 256 КБ) он разжимает через unrar с временным файлом в /tmp и без
  срока. Здесь комментарии не нужны и не читаются вовсе — ни у RAR4, ни у
  RAR5 (_quiet), а сам разбор чужих байтов идёт тоже здесь, под теми же
  пределами.

ИМЕНА В rarfile
- Запасная кодировка разбора — latin-1 (по умолчанию cp1252): имя RAR4 без
  флага Unicode rarfile пробует как UTF-8 и UTF-16, а не вышло — запасной.
  В cp1252 пять байтов не заняты (0x81, 0x8D, 0x8F, 0x90, 0x9D — в cp866 это
  Б, Н, П, Р, Э) и все становятся «�»: «Узел Б1.dxf» и «Узел Н1.dxf»
  превращались в одно имя. latin-1 разбирает байты без потерь. Показывает
  имя не rarfile, а родитель (по байтам, raw) — это имя только для сверок.
- Файл открывается мимо поиска по имени (_open_member): RarFile.open ищет
  запись по имени, и у двух одинаковых имён открылась бы последняя. Теперь
  открываются оба; не достать только сжатый файл «непрерывного» архива с
  повторяющимся именем — его unrar ищет по имени (ниже).

ДВА РЕЖИМА
  list <файлов> <байтов оглавления> <заголовков>
      архив — на вход (stdin), оглавление JSON — на выход. Временных файлов
      нет: rarfile читает из памяти.
  read <путь> <номер> <смещение заголовка> <предел байт> <файлов>
       <байтов оглавления> <заголовков> [--force-tool]
      архив — копия во временной папке (её создаёт и удаляет родитель),
      на выход — байты одного файла, кусками, с остановкой на пределе.
      Номер — позиция в RarFile.infolist(); смещение заголовка сверяется,
      чтобы номер не указал на чужой файл.

КАК ДОСТАЁТСЯ ФАЙЛ (rarfile 4.5, разборщик RarFile — см. _open_member)
- без сжатия — rarfile читает байты сам (DirectReader), unrar не нужен;
- сжатый файл обычного архива — rarfile пишет «мини-архив» (заголовок файла
  и его данные) в ту же временную папку и зовёт unrar БЕЗ имени файла —
  имя ни на что не влияет;
- «непрерывный» (solid) архив — unrar с именем файла: достать файл можно,
  только разжав всё, что лежит перед ним. Имя передаётся байтами, как оно
  записано в архиве (_unrar_name): так его сравнивает сам unrar. Если это
  имя поймает и другой файл (такое же имя или маска «*», «?»), файл не
  достать — список заранее ставит строке причину (поле clash).
  Окружение — C.UTF-8 (задаёт родитель): локали en_US.UTF-8, которую
  объявляет образ, в контейнере нет, и без неё unrar не находит ни одного
  русского имени (проба 06.10: 0 из 3, с C.UTF-8 — 20 из 20).
--force-tool (только для тестов) — и файл без сжатия читать через unrar.

КОПИИ И ССЫЛКИ (RAR5)
WinRAR с «сохранять одинаковые файлы как ссылки» кладёт байты один раз, а
остальные такие же файлы — записью «копия файла X» (жёсткая ссылка — так
же). Для человека это обычные файлы: список отдаёт номер записи с байтами
(orig), и родитель читает её. Символьная ссылка и копия, чьего файла в
архиве нет, — отказ с целью (target) словами.

Контрольную сумму сверяет rarfile на последнем куске; ошибку unrar он
сообщает только после закрытия трубы — код выхода unrar разбирается в
_explain.
"""
import collections
import fnmatch
import json
import os
import shutil
import signal
import sys

# Коды выхода. Родитель (archive_reader) переводит их в слова.
OK = 0
BROKEN = 20
CRC = 21
PASSWORD = 22
MEMORY = 23
OVERFLOW = 24
VOLUME = 25
NO_TOOL = 26
NOT_FOUND = 27
LIMIT = 28
TOO_MANY = 30
HEADERS = 31

# Пределы самого процесса. unrar наследует их: словарь RAR5 бывает до 4 ГБ
# (RAR 7 — до 64 ГБ), и выделить столько ему не даст предел памяти — это код
# 8 «не хватило памяти», а не упавший сервер.
MEMORY_LIMIT = 768 * 1024 * 1024
CPU_LIMIT = 15
CHUNK = 1024 * 1024

# Коды выхода unrar (rar.txt): 3 — контрольная сумма, 8 — память,
# 10 — нет такого файла, 11 — неверный пароль.
UNRAR_CODES = {3: CRC, 8: MEMORY, 10: NOT_FOUND, 11: PASSWORD}

# Запись RAR5 «байты — как у файла X»: жёсткая ссылка (4) и копия (5).
COPY_KINDS = (4, 5)
# Сколько шагов цепочки «копия копии» проходить.
COPY_HOPS = 8
# Имён с «*» или «?» у файлов, которые unrar достаёт по имени: столько
# сверяется с каждым другим именем (масками), сверх — сразу «не достать».
# Под Windows таких имён не бывает, а 5000 масок на 5000 имён — 25 млн
# сверок, дольше срока.
MASK_SCAN = 64


class _Stop(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _limit(file_limit=None):
    """Пределы памяти, процессора и размера файла — до чтения архива.

    file_limit — сколько может весить файл, который запишет процесс:
    «мини-архив» не больше самого архива. Core-файлы не нужны вовсе.
    """
    try:
        import resource
    except ImportError:                                      # pragma: no cover
        return
    limits = [(resource.RLIMIT_AS, MEMORY_LIMIT), (resource.RLIMIT_CPU, CPU_LIMIT),
              (resource.RLIMIT_CORE, 0)]
    if file_limit is not None:
        limits.append((resource.RLIMIT_FSIZE, file_limit))
    for limit, value in limits:
        try:
            soft, hard = resource.getrlimit(limit)
            if hard != resource.RLIM_INFINITY:
                value = min(value, hard)
            if soft == resource.RLIM_INFINITY or soft > value:
                resource.setrlimit(limit, (value, hard))
        except (ValueError, OSError):
            pass


def _no_comment(*_args, **_kwargs):
    return b''


def _skip(*_args, **_kwargs):
    return None


def _quiet(rarfile, folder=None):
    """Настройки rarfile — только в этом процессе.

    - комментарии архива не читаются: у RAR4 — ни старые (в заголовке, их
      разжимает rar3_decompress через unrar), ни новые (запись «CMT»,
      _read_comment_v3); у RAR5 — запись «CMT» (_load_comment). Тот
      раскодирует комментарий строго как UTF-8, а под паролем выводит ключ
      из пустого пароля — и в обоих случаях роняет разбор: необычный
      комментарий делал «повреждённым» весь архив с целыми файлами;
    - «мини-архив» — при любом размере файла (по умолчанию с 20 МБ rarfile
      переходит на unrar с именем файла) и в нашей временной папке;
    - unrar: без файлов-списков (имя «@x.pdf» — это имя, а не список), без
      настроек из ~/.rarrc и RAR, без вывода комментариев.
    """
    rarfile.rar3_decompress = _no_comment
    for parser, method in (('RAR3Parser', '_read_comment_v3'), ('RAR5Parser', '_load_comment')):
        cls = getattr(rarfile, parser, None)
        if cls is not None and hasattr(cls, method):
            setattr(cls, method, _skip)
    rarfile.HACK_SIZE_LIMIT = 1 << 62
    rarfile.USE_EXTRACT_HACK = 1
    # Без папки (режим list) временный файл создать негде — и не нужно.
    rarfile.HACK_TMP_DIR = folder or '/nonexistent-pmk-mail-rar'
    rarfile.UNRAR_CONFIG['open_cmd'] = ('UNRAR_TOOL', 'p', '-inul', '-@', '-cfg-', '-c-')
    rarfile.UNRAR_TOOL = shutil.which('unrar') or 'unrar'


class _Guard:
    """Страж разбора: rarfile зовёт его на каждый заголовок.

    Исключение отсюда останавливает разбор сразу — архив на миллион
    заголовков не строится целиком (проба: 6000 записей — стоп на 5003 за
    0,08 с). Считает файлы, байты заголовков и все заголовки; тома узнаёт по
    признакам продолжения: файл разрезан или конец архива «дальше следующий
    том». Один флаг «том» у архива — не повод: так выглядит «многотомный»
    архив, которому хватило одной части.
    """

    def __init__(self, rarfile, max_files, max_bytes, max_headers):
        self.rarfile = rarfile
        self.max_files, self.max_bytes, self.max_headers = max_files, max_bytes, max_headers
        self.files = self.bytes = self.headers = 0
        self.end = False

    def __call__(self, header):
        rarfile = self.rarfile
        self.headers += 1
        if self.headers > self.max_headers:
            raise _Stop(BROKEN)
        self.bytes += header.header_size or 0
        if self.bytes > self.max_bytes:
            raise _Stop(HEADERS)
        if header.type == rarfile.RAR_BLOCK_FILE:
            self.files += 1
            if self.files > self.max_files:
                raise _Stop(TOO_MANY)
            if header.flags & (rarfile.RAR_FILE_SPLIT_BEFORE | rarfile.RAR_FILE_SPLIT_AFTER):
                raise _Stop(VOLUME)
        elif header.type == rarfile.RAR_BLOCK_ENDARC:
            self.end = True
            if header.flags & rarfile.RAR_ENDARC_NEXT_VOLUME:
                raise _Stop(VOLUME)


def _open(rarfile, source, guard):
    """RarFile или код отказа. Запасная кодировка имён — latin-1 (шапка,
    «Имена в rarfile»)."""
    try:
        return rarfile.RarFile(source, charset='latin-1', info_callback=guard), OK
    except _Stop as stop:
        return None, stop.code
    except rarfile.NeedFirstVolume:
        return None, VOLUME
    except MemoryError:
        return None, MEMORY
    except Exception as exc:                                  # чужой файл — что угодно
        sys.stderr.write('rar: %r\n' % (exc,))
        return None, BROKEN


# ═══════════════════════════════════════════════════════════════════════════
# сверки имён — общие для list и read
# ═══════════════════════════════════════════════════════════════════════════
def _by_name(rarfile, archive, info):
    """Достаёт ли файл unrar по имени: сжатый файл «непрерывного» архива.
    Без сжатия rarfile читает сам, обычный сжатый — «мини-архивом» без имени."""
    return ((archive.is_solid() or bool(info.flags & rarfile.RAR_FILE_SOLID))
            and info.compress_type != rarfile.RAR_M0)


def _names(infos):
    """Сколько раз встречается каждое имя (без папок) — для _clash."""
    return collections.Counter(info.filename or '' for info in infos if not info.is_dir())


def _clash(infos, info, counts, scan=True):
    """Поймает ли имя, которое получит unrar, и другой файл архива:
    'twin' — такое же имя, 'mask' — «?» и «*» в имени (unrar из Linux
    понимает их как шаблон) подходят к другому имени, '' — нет. unrar выдал
    бы несколько файлов подряд, и проверка суммы сказала бы «повреждён» про
    целый файл. scan=False — маску не сверять, а сразу считать пойманной."""
    name = info.filename or ''
    if counts.get(name, 0) > 1:
        return 'twin'
    if '*' in name or '?' in name:
        if not scan:
            return 'mask'
        pattern = name.lower()
        for other in infos:
            if other is info or other.is_dir():
                continue
            if fnmatch.fnmatchcase((other.filename or '').lower(), pattern):
                return 'mask'
    return ''


def _key(name):
    return (name or '').replace('\\', '/').rstrip('/')


def _original(infos, number, places):
    """Копия или жёсткая ссылка RAR5 -> номер записи, чьи байты она
    повторяет; None — файла нет в архиве, цепочка длиннее COPY_HOPS или
    замкнута, ведёт к папке или к символьной ссылке.

    Запись ищется по имени, как у самого rarfile (getinfo_orig): при двух
    одинаковых именах — последняя."""
    seen = set()
    while True:
        info = infos[number]
        redir = info.file_redir
        if redir is None:
            if info.is_dir() or info.is_symlink():
                return None
            return number
        if redir[0] not in COPY_KINDS or number in seen or len(seen) >= COPY_HOPS:
            return None
        seen.add(number)
        number = places.get(_key(redir[2]))
        if number is None:
            return None


# ═══════════════════════════════════════════════════════════════════════════
# list
# ═══════════════════════════════════════════════════════════════════════════
def _item(rarfile, info, orig=None, clash='', places=None):
    """Строка оглавления — только факты; имя и отказы решает родитель.

    orig — у копии RAR5 номер записи с байтами (см. _original), иначе None;
    clash — см. _clash (только у файлов, которые unrar достаёт по имени);
    places — имя -> номер записи (как в _original)."""
    rar3 = isinstance(info, rarfile.Rar3Info)
    raw = ''
    if rar3 and not info.flags & rarfile.RAR_FILE_UNICODE:
        # Имя без флага Unicode — в кодировке DOS или Windows; rarfile
        # пробует UTF-16 и портит его («Старое.pdf» — «ꖮ瀮晤»). Байты — родителю.
        raw = bytes(info.orig_filename or b'').hex()
    mtime = None
    if info.mtime is not None and info.mtime.tzinfo is not None:
        mtime = info.mtime.timestamp()        # RAR5: время в UTC
    redir = info.file_redir
    copy = redir is not None and redir[0] in COPY_KINDS
    return {
        'name': info.filename or '',
        'raw': raw,
        'dir': bool(info.is_dir()),
        # Ссылка — и копия, чьих байтов в архиве нет.
        'link': bool(info.is_symlink() or (redir is not None and orig is None)),
        'copy': bool(copy),
        'orig': orig if copy else None,
        'target': str(redir[2] or '') if redir is not None else '',
        # Копия без байтов: файла с таким именем в архиве нет вовсе (иначе —
        # он есть, но это ссылка, папка или замкнутая цепочка копий).
        'lost': bool(copy and orig is None and places is not None
                     and _key(redir[2]) not in places),
        'clash': clash,
        'pw': bool(info.needs_password()),
        'solid': bool(info.flags & rarfile.RAR_FILE_SOLID),
        'size': int(info.file_size or 0),
        'packed': int(info.compress_size or 0),
        'method': int(info.compress_type or 0),
        'mtime': mtime,
        'dt': list(info.date_time[:6]) if info.date_time else None,
        'off': int(info.header_offset or 0),
    }


def _items(rarfile, archive, infos):
    """Строки оглавления по порядку infolist()."""
    counts = _names(infos)
    # Как _info_map у rarfile: с папками, при одинаковых именах — последняя.
    places = {_key(info.filename): number for number, info in enumerate(infos)}
    fetched = [info.file_redir is None and not info.is_dir() and not info.is_symlink()
               and _by_name(rarfile, archive, info) for info in infos]
    masks = sum(1 for number, info in enumerate(infos)
                if fetched[number] and ('*' in (info.filename or '') or '?' in (info.filename or '')))
    scan = masks <= MASK_SCAN
    items = []
    for number, info in enumerate(infos):
        orig = None
        if info.file_redir is not None and info.file_redir[0] in COPY_KINDS:
            orig = _original(infos, number, places)
        clash = _clash(infos, info, counts, scan) if fetched[number] else ''
        items.append(_item(rarfile, info, orig, clash, places))
    return items


def _list(argv):
    max_files, max_bytes, max_headers = (int(value) for value in argv[:3])
    _limit(file_limit=0)
    try:
        import rarfile
    except ImportError:
        return NO_TOOL
    _quiet(rarfile)
    blob = sys.stdin.buffer.read()
    guard = _Guard(rarfile, max_files, max_bytes, max_headers)
    archive, code = _open(rarfile, _BytesIO(blob), guard)
    if archive is None:
        return code
    try:
        infos = archive.infolist()
        error = archive.strerror() or ''
        rar5 = blob.startswith(rarfile.RAR5_ID)
        listing = {
            'rar': 5 if rar5 else 3,
            'solid': bool(archive.is_solid()),
            'needs_password': bool(archive.needs_password()),
            # RAR5 без записи «конец архива» — обрезан или с блоком
            # незнакомого вида: rarfile на таком молча прекращает разбор.
            # У RAR4 конца может не быть законно (RAR 2.x его не пишет).
            'partial': bool(error) or (rar5 and not guard.end),
            'error': error,
            'items': _items(rarfile, archive, infos),
        }
        text = json.dumps(listing)
    except MemoryError:
        return MEMORY
    except Exception as exc:                                  # чужой файл — что угодно
        sys.stderr.write('rar: %r\n' % (exc,))
        return BROKEN
    sys.stdout.write(text)
    sys.stdout.flush()
    return OK


def _BytesIO(blob):
    import io
    return io.BytesIO(blob)


# ═══════════════════════════════════════════════════════════════════════════
# read
# ═══════════════════════════════════════════════════════════════════════════
def _unrar_name(rarfile, info):
    """Имя для unrar — так, как его сравнивает сам unrar.

    RAR5 и RAR4 без флага Unicode — байтами из архива (unrar и аргумент, и
    имя в архиве переводит одной и той же функцией, проба 06.10: имя cp866
    находится только байтами), у RAR4 обратная косая — косая. RAR4 с флагом
    Unicode — строкой: в байтах там лишь запасное имя в кодировке DOS.
    """
    if isinstance(info, rarfile.Rar3Info):
        if info.flags & rarfile.RAR_FILE_UNICODE:
            return info.filename
        return bytes(info.orig_filename or b'').replace(b'\\', b'/')
    return bytes(info.orig_filename or b'')


def _open_member(archive, info):
    """Поток байтов ЭТОЙ записи.

    RarFile.open ищет запись по имени и при двух одинаковых именах открыл бы
    последнюю, поэтому — мимо поиска, разборщиком rarfile (_file_parser,
    rarfile 4.5): тот же путь, что у RarFile.open после поиска. Папку,
    ссылку и пароль _read отсеял раньше. Без разборщика (другая версия
    rarfile) — по имени, но только если имя не занято другой записью.
    """
    parser = getattr(archive, '_file_parser', None)
    if parser is not None and callable(getattr(parser, 'open', None)):
        return parser.open(info, None)
    if archive.getinfo(info.filename) is not info:
        raise _Stop(NOT_FOUND)
    return archive.open(info)


def _explain(rarfile, exc, src):
    """Исключение чтения -> код выхода. Код unrar известен только после
    закрытия трубы: rarfile читает до конца и лишь тогда видит нехватку."""
    if isinstance(exc, rarfile.NeedFirstVolume):
        return VOLUME
    if isinstance(exc, (rarfile.PasswordRequired, rarfile.RarWrongPassword)):
        return PASSWORD
    if isinstance(exc, rarfile.RarCannotExec):
        return NO_TOOL
    if isinstance(exc, (MemoryError, rarfile.RarMemoryError)):
        return MEMORY
    if isinstance(exc, rarfile.RarCRCError):
        return CRC
    if isinstance(exc, rarfile.RarSignalExit):
        return LIMIT
    if isinstance(exc, rarfile.NoRarEntry):
        return NOT_FOUND
    if isinstance(exc, rarfile.BadRarFile):
        returncode = 0
        if src is not None:
            try:
                src.close()
            except Exception:                                 # закрываем как можем
                pass
            returncode = getattr(src, '_returncode', 0) or 0
        if returncode < 0 and returncode != -signal.SIGPIPE:
            return LIMIT                                      # unrar убит пределом
        if returncode in UNRAR_CODES:
            return UNRAR_CODES[returncode]
        return CRC if 'CRC' in str(exc) else BROKEN
    return BROKEN


def _read(argv):
    path = argv[0]
    index, offset, cap, max_files, max_bytes, max_headers = (int(value) for value in argv[1:7])
    force_tool = '--force-tool' in argv[7:]
    folder = os.path.dirname(os.path.abspath(path))
    try:
        file_limit = os.path.getsize(path) + 1024 * 1024
    except OSError:
        return BROKEN
    _limit(file_limit=file_limit)
    try:
        import rarfile
    except ImportError:
        return NO_TOOL
    _quiet(rarfile, folder)
    try:
        # Только unrar: без этого rarfile при неудаче перебрал бы unar, 7z и
        # bsdtar — другое поведение и другие коды ошибок.
        setup = rarfile.tool_setup(unrar=True, unar=False, bsdtar=False, sevenzip=False,
                                   sevenzip2=False, force=True)
    except rarfile.Error:
        return NO_TOOL
    guard = _Guard(rarfile, max_files, max_bytes, max_headers)
    archive, code = _open(rarfile, path, guard)
    if archive is None:
        return code
    infos = archive.infolist()
    if not 0 <= index < len(infos) or infos[index].header_offset != offset:
        return NOT_FOUND
    info = infos[index]
    if info.is_dir() or info.is_symlink() or info.file_redir is not None:
        # У папки и ссылки своих байтов нет; копию RAR5 родитель читает по
        # номеру записи с байтами (orig из списка), а не по номеру копии.
        return NOT_FOUND
    if info.needs_password():
        return PASSWORD
    # Имя уходит unrar у сжатого файла «непрерывного» архива (и в тестах с
    # --force-tool); без сжатия rarfile читает сам, обычный сжатый — через
    # «мини-архив» без имени. Список такой файл уже пометил (clash).
    by_name = force_tool or _by_name(rarfile, archive, info)
    if by_name and _clash(infos, info, _names(infos)):
        return NOT_FOUND
    unrar_name = _unrar_name(rarfile, info)
    setup.add_file_arg = lambda cmdline, _filename: cmdline.append(unrar_name)
    if force_tool:
        rarfile.FORCE_TOOL = True
    src = None
    out = sys.stdout.buffer
    try:
        src = _open_member(archive, info)
        total = 0
        while True:
            chunk = src.read(min(CHUNK, cap + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > cap:
                return OVERFLOW
            out.write(chunk)
        out.flush()
        return OK
    except _Stop as stop:
        return stop.code
    except Exception as exc:                                  # чужой файл — что угодно
        sys.stderr.write('rar: %r\n' % (exc,))
        return _explain(rarfile, exc, src)
    finally:
        if src is not None:
            try:
                src.close()
            except Exception:                                 # закрываем как можем
                pass


def main(argv):
    if not argv:
        return BROKEN
    if argv[0] == 'list':
        return _list(argv[1:])
    if argv[0] == 'read':
        return _read(argv[1:])
    return BROKEN


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
