# -*- coding: utf-8 -*-
"""Чертёж DXF -> пути для окна просмотра. Разбор и отрисовка — библиотекой ezdxf.

ЧТО ЗДЕСЬ И ЧЕГО ЗДЕСЬ НЕТ
Своего разбора DXF здесь нет (решение Антона 06.10.2026: «читалку DXF —
готовую»). Файл читает ezdxf 1.4.2 (MIT, github.com/mozman/ezdxf, стоит в
образе: experiments/odoo/Dockerfile, ARG PYDEPS): recover — текстовый DXF с
починкой битых мест, двоичный — его же загрузчиком. Рисует тоже ezdxf:
addons.drawing (Frontend + RenderContext + SVG-бэкенд) — дуги полилиний,
сплайны, блоки с масштабом и поворотом, размеры через их блок, тексты
контурами шрифта. Наше — три вещи:
  1. раскладка готовых путей SVG по слоям (слой выключается в браузере без
     перерисовки, порядок наложения сохраняется);
  2. пределы: размер файла, число объектов, время, память, объём ответа;
  3. оговорки словами: кодировка, починка, пропущенные объекты, единицы.

ПОЧЕМУ ОТДЕЛЬНЫМ ПРОЦЕССОМ
Файл запускается как `python3 -I dxf_render.py`: байты чертежа — на вход,
ответ JSON — на выход (models/drawing.py, _run_renderer). Чертёж на 50 000
объектов берёт около 0,5 ГБ памяти, а разбор (recover.read) кооперативно не
прервать. Внутри рабочего процесса Odoo (предел 1,28 ГБ виртуальной памяти,
два процесса на контейнер 2,5 ГБ) это означало бы его убийство посреди
запроса. У отдельного процесса свой предел памяти и процессорного времени
(_limit_resources), а снаружи — жёсткий срок subprocess.run(timeout=…). Тот
же приём Odoo применяет для wkhtmltopdf.

Поэтому в файле НЕТ импорта odoo, а ezdxf импортируется внутри функций:
модуль pmk_drawing ставится и без ezdxf и тогда честно говорит «Просмотр
DXF недоступен», а тесты гоняют render() прямо в процессе.

ДОГОВОР ОТВЕТА (второй конец — static/src/js/dxf_view_math.js,
normalizeDrawing; менять только вместе):
    ok        True — чертёж нарисован; False — reason словами
    version   PAYLOAD_VERSION
    viewbox   [W, H] — пространство координат путей (целые 0…1 000 000 по
              большей стороне, ось y уже перевёрнута — так пишет SVG-бэкенд
              ezdxf)
    viewbox   по слоям, ВКЛЮЧЁННЫМ в файле: выключенный или замороженный
              слой с мусором далеко в стороне не делает чертёж точкой в углу
              (так и AutoCAD «Показать до границ»). Его пути рисуются в тех же
              координатах — за краем viewbox
    layers    [{name, color '#rrggbb', on, box}] — номер слоя = индекс в
              списке; on — включён ли слой в самом файле (выключенные и
              замороженные рисуются, но окно показывает их снятой галочкой);
              box [x0, y0, x1, y1] — рамка путей слоя в координатах viewbox
              (по ней окно «вписывает» слои с галочкой); нет — рамки нет
    palette   ['#rrggbb', …] — цвета путей, как их отдал ezdxf на белом листе
              (ACI 7 уже чёрный); читаемость на белом добирает браузер
    items     [[слой, вид, цвет, d], …] — вид 0 — тонкая линия, 1 — заливка
              (тексты, SOLID), 2 — толстая линия (вес ≥ 0,5 мм); соседние
              линии одного слоя, вида и цвета склеены в один путь
    size_mm   [ширина, высота] габарита в миллиметрах — по слоям,
              включённым в файле (как viewbox)
    units     {code, label, assumed} — $INSUNITS словами; assumed — единицы
              в файле не заданы, считаем миллиметрами
    layout    'Model' или имя листа, если модель пуста
    notes     оговорки словами (кодировка, починка, пропущенное, …)
    skipped   {total, by_label: [[подпись, число], …]} — не показано
    stats     {entities, items, chars, seconds}
    cache     можно ли запомнить ответ надолго (отказ по времени — нельзя)
    slow      отказ по времени или пределу процесса: models/drawing.py
              запоминает его на сутки, а не на месяц
"""

import io
import json
import math
import re
import sys
import time

# Версия договора ответа. Кэш (models/drawing.py) сбрасывается и без неё —
# при любой правке этого файла (контрольная сумма исходника в версии кэша).
PAYLOAD_VERSION = 2

# ═══════════════════════════════════════════════════════════════════════════
# ПРЕДЕЛЫ
# ═══════════════════════════════════════════════════════════════════════════
# Замер на стенде 06.10.2026 (ezdxf 1.4.2, один поток): 50 000 объектов —
# файл 6,9 МБ, разбор 5,7 с, отрисовка 6,1 с, ответ 10,8 МБ, пик памяти
# 547 МБ; 100 000 — 13,8 МБ, 24 с, 21,7 МБ. Настоящие развёртки вентзонтов —
# 128–178 объектов, 0,1 с.
MAX_FILE_BYTES = 30 * 1024 * 1024
# Сколько объектов в файле — считаем ДО разбора, по группам «0» (у каждого
# объекта, записи таблицы и служебного объекта она одна).
MAX_ZERO_TAGS = 150_000
# Сколько объектов рисуем, считая содержимое блоков: блок на 1000 линий,
# вставленный 1000 раз, — миллион линий при файле в сотню килобайт.
MAX_ENTITIES = 300_000
# Путей в ответе (после склейки соседних линий) и объём строк путей.
MAX_ITEMS = 150_000
MAX_OUTPUT_CHARS = 16_000_000
# Срок отрисовки внутри процесса; снаружи процесс убивается чуть позже
# (models/drawing.py, RENDER_TIMEOUT), если застрял в разборе.
SOFT_DEADLINE = 40.0
# Память и процессор отдельного процесса (_limit_resources).
MEMORY_LIMIT = 1024 * 1024 * 1024
CPU_LIMIT = 50

DEFAULT_LIMITS = {
    'file_bytes': MAX_FILE_BYTES,
    'zero_tags': MAX_ZERO_TAGS,
    'entities': MAX_ENTITIES,
    'items': MAX_ITEMS,
    'chars': MAX_OUTPUT_CHARS,
    'deadline': SOFT_DEADLINE,
}

# Линия толще этого (мм) — «толстая» в окне. Вес по умолчанию 0,25 мм.
THICK_MM = 0.5
# Склеенный путь не длиннее этого: гигантский путь браузер рисует целиком при
# каждом сдвиге, даже если на экране его кусочек.
MERGE_MAX_CHARS = 256 * 1024

BINARY_SIGNATURE = b"AutoCAD Binary DXF\r\n\x1a\x00"

UNAVAILABLE = ("Просмотр DXF недоступен: на сервере нет библиотеки чертежей "
               "ezdxf. Файл можно скачать и открыть у себя.")
NOT_DXF = "Это не чертёж DXF — внутри нет его разметки."
BROKEN = ("Файл повреждён и не читается как чертёж DXF. Его можно скачать и "
          "открыть в своей программе — она, возможно, справится.")
EMPTY = "В чертеже нет ни одной линии — показывать нечего."
TRUNCATED = ("Файл обрезан или повреждён: чертежа в нём не нашлось. Попросите "
             "прислать его заново.")
BAD_SIZE = ("Размеры чертежа в файле повреждены: координаты за пределами разумного. "
            "Файл можно скачать и открыть у себя.")
SLOW = ("Чертёж рисуется слишком долго — показать его не получится. Файл можно "
        "скачать и открыть у себя.")

# $INSUNITS -> подпись. Множитель в миллиметры берёт ezdxf
# (ezdxf.units.conversion_factor); таблица ниже — подписи и запас на случай,
# если код библиотеке незнаком.
UNIT_LABELS = {
    0: ('не заданы', 1.0), 1: ('дюймы', 25.4), 2: ('футы', 304.8),
    3: ('мили', 1609344.0), 4: ('мм', 1.0), 5: ('см', 10.0), 6: ('м', 1000.0),
    7: ('км', 1e6), 8: ('микродюймы', 25.4e-6), 9: ('милы', 0.0254),
    10: ('ярды', 914.4), 11: ('ангстремы', 1e-7), 12: ('нанометры', 1e-6),
    13: ('микроны', 1e-3), 14: ('дециметры', 100.0), 15: ('декаметры', 1e4),
    16: ('гектометры', 1e5), 17: ('гигаметры', 1e12),
    21: ('футы США', 304.8006096), 22: ('дюймы США', 25.4000508),
}

# Что не нарисовалось — по-русски. Ключ — тип объекта DXF.
SKIPPED_LABELS = {
    '3DSOLID': 'тело 3D', 'BODY': 'тело 3D', 'REGION': 'область',
    'SURFACE': 'поверхность', 'EXTRUDEDSURFACE': 'поверхность',
    'LOFTEDSURFACE': 'поверхность', 'REVOLVEDSURFACE': 'поверхность',
    'SWEPTSURFACE': 'поверхность', 'PLANESURFACE': 'поверхность',
    'NURBSURFACE': 'поверхность', 'MESH': 'сеть', 'OLE2FRAME': 'вставка OLE',
    'OLEFRAME': 'вставка OLE', 'ACAD_PROXY_ENTITY': 'объект другой программы',
    'PDFUNDERLAY': 'подложка PDF', 'DWFUNDERLAY': 'подложка DWF',
    'DGNUNDERLAY': 'подложка DGN', 'IMAGE': 'картинка', 'WIPEOUT': 'маска',
    'TEXT': 'текст не в плоскости чертежа',
    'MTEXT': 'текст не в плоскости чертежа',
    'ATTRIB': 'текст не в плоскости чертежа',
}
OTHER_LABEL = 'прочие объекты'
# Объект, на котором ezdxf упал (вырожденный сплайн, вставка с нулевым
# масштабом…): пропускаем его, а не весь чертёж.
BROKEN_LABEL = 'объект с ошибкой'

# Объекты, которые ezdxf рисует своим блоком, но не как вставку (см.
# CountingFrontend.draw_composite_entity).
COMPOSITE_AS_BLOCK = ('DIMENSION', 'ARC_DIMENSION', 'LARGE_RADIAL_DIMENSION')

# Типы линий, которые штрихуются. Остальное (CONTINUOUS, ByLayer, ByBlock) —
# сплошное.
SOLID_LINETYPES = ('', 'CONTINUOUS', 'BYLAYER', 'BYBLOCK')


class Refusal(Exception):
    """Показать чертёж нельзя — причина словами.

    cache: можно ли запомнить отказ. Отказ по размеру или порче повторится
    на тех же байтах; отказ по времени — нет (сервер мог быть занят).
    """

    def __init__(self, reason, cache=True):
        super().__init__(reason)
        self.reason = reason
        self.cache = cache


class _Abort(Exception):
    """Отрисовка встала на пределе: what — 'time', 'entities', 'items', 'chars'."""

    def __init__(self, what):
        super().__init__(what)
        self.what = what


def _mb(size):
    return ("%.1f МБ" % (size / 1024.0 / 1024.0)).replace('.', ',')


def _num(value):
    """Число с пробелами между разрядами: 150 000; четырёхзначные слитно."""
    value = int(value)
    if abs(value) < 10000:
        return str(value)
    return '{:,}'.format(value).replace(',', ' ')


# ═══════════════════════════════════════════════════════════════════════════
# 1. ДО РАЗБОРА: ЧТО ЗА ФАЙЛ И СКОЛЬКО В НЁМ ОБЪЕКТОВ
# ═══════════════════════════════════════════════════════════════════════════
def sniff(blob):
    """'binary', 'ascii' или None — по первым байтам, без разбора."""
    if blob.startswith(BINARY_SIGNATURE):
        return 'binary'
    head = blob[:8192]
    if b'\x00' in head:
        return None
    if head.startswith(b'\xef\xbb\xbf'):
        head = head[3:]
    lines = []
    for raw in head.splitlines():
        line = raw.strip()
        if line:
            lines.append(line)
        if len(lines) >= 40:
            break
    # Перед SECTION бывают комментарии группы 999.
    while len(lines) >= 2 and lines[0] == b'999':
        lines = lines[2:]
    if lines[:2] == [b'0', b'SECTION'] or b'$ACADVER' in head:
        return 'ascii'
    return None


# Группа «0» (начало объекта, записи таблицы, раздела) — строка «0», за которой
# имя типа. Значение «0» у других групп тоже бывает строкой «0», но за ним
# идёт номер группы — одни цифры («100», «  8»), поэтому имя типа обязано
# начинаться с буквы или с цифры, за которой буква (3DFACE, 3DSOLID).
_ZERO_TAG = re.compile(rb'\n[ \t]*0[ \t]*\r?\n(?:[A-Za-z_]|[0-9][A-Za-z])')


def count_zero_tags(blob, stop_after=None):
    """Сколько в текстовом DXF групп «0». stop_after — хватит считать."""
    count = 0
    for _match in _ZERO_TAG.finditer(blob):
        count += 1
        if stop_after is not None and count > stop_after:
            break
    return count


_ACADVER = re.compile(rb'\$ACADVER[ \t]*\r?\n[ \t]*1[ \t]*\r?\n([^\r\n]*)')
_CODEPAGE = re.compile(rb'\$DWGCODEPAGE[ \t]*\r?\n[ \t]*3[ \t]*\r?\n([^\r\n]*)')
# Русский текст в cp1251: А–я лежат в C0–FF, и в словах они идут подряд.
_CP1251_RUN = re.compile(rb'[\xc0-\xff]{3,}')
_NON_ASCII = re.compile('[^\x00-\x7f]')
CODEPAGE_NOTE = "Кодировка текста в файле не указана или указана неверно — прочитали %s."
_HEADER_SCAN = 2 * 1024 * 1024


def _escape_unicode(match):
    code = ord(match.group())
    # \U+XXXX — штатная запись DXF для знаков вне кодовой страницы; ezdxf
    # раскодирует её сам в любой строке. Знаков вне BMP в чертежах нет.
    return '\\U+%04X' % code if code <= 0xFFFF else '?'


def _as_escaped(text):
    """Текст -> байты ASCII, где всё не-ASCII записано как \\U+XXXX."""
    return _NON_ASCII.sub(_escape_unicode, text).encode('ascii')


def fix_codepage(blob):
    """Чинит неверно указанную кодировку текстового DXF. -> (байты, оговорка).

    ezdxf берёт кодировку из заголовка: $DWGCODEPAGE до версии R2007 и UTF-8
    начиная с неё — и только если в заголовке есть и версия, и кодовая
    страница; иначе cp1252. Русский чертёж из старой программы сплошь и рядом
    подписан «ANSI_1252» или вовсе без кодовой страницы — и вместо «Деталь»
    выходит «Äåòàëü». Бывает и UTF-8 в файле старой версии (так пишут часть
    станочных программ).

    Чиним не правкой заголовка, а переводом текста: читаем байты в верной
    кодировке и записываем всё не-ASCII штатной записью DXF «\\U+0414».
    ezdxf раскодирует её в любой строке при любой кодировке заголовка — то
    есть исправление не зависит от того, что и где в заголовке написано.
    """
    region = blob[:_HEADER_SCAN]
    end = region.find(b'ENDSEC')
    if end > 0:
        region = region[:end]
    version_match = _ACADVER.search(region)
    codepage_match = _CODEPAGE.search(region)
    version = version_match.group(1).strip().upper() if version_match else b''
    codepage = codepage_match.group(1).strip().upper() if codepage_match else b''

    if not re.search(rb'[\x80-\xff]', blob):
        return blob, ''                    # чистый ASCII — кодировка не важна

    modern = version >= b'AC1021'
    # Какой кодировкой прочтёт ezdxf (recover.detect_encoding).
    if version and codepage:
        effective = 'utf8' if modern else _toencoding(codepage)
    else:
        effective = 'cp1252'

    try:
        as_utf8 = blob.decode('utf-8')
    except UnicodeDecodeError:
        as_utf8 = None

    if as_utf8 is not None:
        if effective == 'utf8':
            return blob, ''
        return _as_escaped(as_utf8), CODEPAGE_NOTE % 'как UTF-8'
    if effective == 'cp1251':
        return blob, ''
    # Признак русского текста в cp1251 — буквы C0–FF подряд, хотя бы четыре
    # в сумме («КОНТУР» в имени слоя — уже шесть). В западном тексте cp1252
    # три таких знака подряд не встречаются: «Größe» — два.
    runs = _CP1251_RUN.findall(blob, 0, 4 * 1024 * 1024)
    if effective in ('cp1252', 'utf8') and sum(len(run) for run in runs) >= 4:
        text = blob.decode('cp1251', 'replace')
        return _as_escaped(text), CODEPAGE_NOTE % 'как русскую (cp1251)'
    return blob, ''


def _toencoding(codepage):
    for number, encoding in (('1251', 'cp1251'), ('1252', 'cp1252'), ('1250', 'cp1250'),
                             ('1253', 'cp1253'), ('1254', 'cp1254'), ('1255', 'cp1255'),
                             ('1256', 'cp1256'), ('1257', 'cp1257'), ('1258', 'cp1258'),
                             ('874', 'cp874'), ('932', 'cp932'), ('936', 'gbk'),
                             ('949', 'cp949'), ('950', 'cp950')):
        if codepage.endswith(number.encode()):
            return encoding
    return 'cp1252'


# ═══════════════════════════════════════════════════════════════════════════
# 2. РАЗБОР — ezdxf
# ═══════════════════════════════════════════════════════════════════════════
def load(blob):
    """(документ ezdxf, оговорки, обрезан ли файл). Отказ — Refusal."""
    from ezdxf.lldxf.const import DXFError

    notes = []
    kind = sniff(blob)
    if kind is None:
        raise Refusal(NOT_DXF)
    # Текстовый DXF кончается строкой EOF. Нет её — файл оборван (недокачан,
    # обрезан почтой), и recover молча покажет только начало. Старые
    # программы дописывают после EOF нули или Ctrl-Z (0x1A) — это не обрыв.
    truncated = kind == 'ascii' and not blob.rstrip(b' \t\r\n\x00\x1a').endswith(b'EOF')
    if truncated:
        notes.append("Файл, похоже, обрезан — показано то, что в нём успело записаться.")
    if kind == 'binary':
        # recover.read двоичный DXF не читает («Invalid group code AutoCAD
        # Binary DXF») — нужен загрузчик двоичных групп ezdxf.
        from ezdxf.document import Drawing
        from ezdxf.lldxf.tagger import binary_tags_loader
        try:
            doc = Drawing.load(binary_tags_loader(blob, errors='surrogateescape'))
            auditor = doc.audit()
        except (DXFError, ValueError, IndexError, KeyError, TypeError,
                AttributeError, EOFError, UnicodeDecodeError) as exc:
            raise Refusal(BROKEN) from exc
    else:
        from ezdxf import recover
        blob, note = fix_codepage(blob)
        if note:
            notes.append(note)
        try:
            doc, auditor = recover.read(io.BytesIO(blob))
        except (DXFError, ValueError, IndexError, KeyError, TypeError,
                AttributeError, EOFError, UnicodeDecodeError) as exc:
            raise Refusal(TRUNCATED if truncated else BROKEN) from exc
    # Исправления (fixes) recover делает и в исправных файлах чужих программ
    # (пропущенные указатели, порядок записей) — говорить про них «повреждён»
    # значило бы пугать на каждом втором чертеже. Ошибки (errors) — это то,
    # что починить не вышло и что выброшено.
    if getattr(auditor, 'has_errors', False) and not truncated:
        notes.append("Файл был повреждён — показано то, что удалось восстановить.")
    return doc, notes, truncated


# ═══════════════════════════════════════════════════════════════════════════
# 3. ОТРИСОВКА — ezdxf.addons.drawing, пути раскладываем по слоям сами
# ═══════════════════════════════════════════════════════════════════════════
class _Sink:
    """Куда SVG-бэкенд ezdxf складывает готовые пути: по слоям, без XML."""

    def __init__(self, layer_of_handle, limits, deadline):
        self.layer_of_handle = layer_of_handle
        self.limits = limits
        self.deadline = deadline
        self.layer_index = {}
        self.layer_names = []
        self.color_index = {}
        self.colors = []
        self.items = []
        self.chars = 0
        self.calls = 0

    def _layer(self, name):
        # Имена слоёв в DXF без учёта регистра: «Контур» у объекта и «КОНТУР»
        # в таблице слоёв — один слой и одна галочка.
        key = name.lower()
        index = self.layer_index.get(key)
        if index is None:
            index = self.layer_index[key] = len(self.layer_names)
            self.layer_names.append(name)
        return index

    def _color(self, color):
        index = self.color_index.get(color)
        if index is None:
            index = self.color_index[color] = len(self.colors)
            self.colors.append(color)
        return index

    def layer_of(self, properties):
        """Слой пути. Части размера (выносные, размерная линия) приходят
        слоем «0» — так они лежат в блоке размера. Сам размер — на своём
        слое; без переноса галочка «Размеры» гасила бы стрелки и текст, а
        линии оставались. Содержимое блоков со слоя «0» ezdxf переносит на
        слой вставки сам."""
        layer = properties.layer or '0'
        if layer == '0' and properties.handle:
            layer = self.layer_of_handle.get(properties.handle, layer)
        return layer

    def add(self, d, properties, fill):
        self.calls += 1
        if self.calls % 1024 == 0 and time.monotonic() > self.deadline:
            raise _Abort('time')
        layer = self.layer_of(properties)
        color = (properties.color or '#000000')[:7].lower()
        if fill:
            kind = 1
        else:
            kind = 2 if (properties.lineweight or 0) >= THICK_MM else 0
        layer_id = self._layer(layer)
        color_id = self._color(color)
        last = self.items[-1] if self.items else None
        # Заливки не склеиваем: два наложенных текста или SOLID в одном пути
        # с правилом evenodd вырезали бы друг в друге дыры.
        if (kind != 1 and last is not None and last[0] == layer_id and last[1] == kind
                and last[2] == color_id and last[4] < MERGE_MAX_CHARS):
            last[3].append(d)
            last[4] += len(d) + 1
        else:
            if len(self.items) >= self.limits['items']:
                raise _Abort('items')
            self.items.append([layer_id, kind, color_id, [d], len(d)])
        self.chars += len(d) + 1
        if self.chars > self.limits['chars']:
            raise _Abort('chars')


def _make_backend_classes():
    """Наследники SVG-бэкенда ezdxf: те же строки путей, но в _Sink, а не в XML."""
    from ezdxf.addons.drawing import svg

    class CollectingRender(svg.SVGRenderBackend):
        sink = None

        def add_strokes(self, d, properties):
            if d:
                self.sink.add(d, properties, False)

        def add_filling(self, d, properties):
            if d:
                self.sink.add(d, properties, True)

    class CollectingSVG(svg.SVGBackend):
        def __init__(self, sink):
            super().__init__()
            self.sink = sink

        def make_backend(self, page, settings):
            backend = CollectingRender(page, settings)
            backend.sink = self.sink
            return backend

    return CollectingSVG


def _make_frontend_class():
    from ezdxf.addons.drawing import Frontend

    class CountingFrontend(Frontend):
        """Frontend ezdxf со сроком, пределом и счётом пропущенного."""

        deadline = 0.0
        max_entities = MAX_ENTITIES
        drawn = 0
        skipped = None

        def draw_entity(self, entity, properties):
            self.drawn += 1
            if self.drawn > self.max_entities:
                raise _Abort('entities')
            if self.drawn % 256 == 0 and time.monotonic() > self.deadline:
                raise _Abort('time')
            # Один объект, на котором ezdxf падает (сплайн с повтором точки —
            # деление на ноль, вставка с масштабом 1e-300, …), не должен
            # ронять весь чертёж: recover такие объекты не убирает, а у ezdxf
            # вокруг отрисовки объекта try нет. Пропускаем его и считаем в
            # «не показано». Стек состояния вставок и рамок обрезки ezdxf
            # открывает без finally — возвращаем как было, иначе соседи
            # нарисовались бы свойствами упавшей вставки.
            state = self._save_state()
            try:
                super().draw_entity(entity, properties)
            except (_Abort, MemoryError, RecursionError):
                raise
            except Exception:
                self._restore_state(state)
                self.skipped[BROKEN_LABEL] = self.skipped.get(BROKEN_LABEL, 0) + 1

        def _save_state(self):
            saved = getattr(self.ctx, '_saved_states', None)
            portal = getattr(getattr(self, 'pipeline', None), 'clipping_portal', None)
            stages = getattr(portal, '_stages', None)
            return (
                len(saved) if isinstance(saved, list) else None,
                getattr(self.ctx, 'current_block_reference_properties', None),
                len(stages) if isinstance(stages, list) else None,
            )

        def _restore_state(self, state):
            saved_depth, current, stages_depth = state
            saved = getattr(self.ctx, '_saved_states', None)
            if saved_depth is not None and isinstance(saved, list):
                del saved[saved_depth:]
            if hasattr(self.ctx, 'current_block_reference_properties'):
                self.ctx.current_block_reference_properties = current
            portal = getattr(getattr(self, 'pipeline', None), 'clipping_portal', None)
            stages = getattr(portal, '_stages', None)
            if stages_depth is not None and isinstance(stages, list):
                del stages[stages_depth:]

        def draw_composite_entity(self, entity, properties):
            # Размер рисуется своим блоком, но ezdxf обходит его не как
            # вставку: цвет «по блоку» (так в блоке размера лежат выносные и
            # размерная линия) уходил в чёрный, а слой «0» не становился слоем
            # размера. В AutoCAD блок размера ведёт себя как вставка — так и
            # рисуем: свойства размера на время его блока.
            if entity.dxftype() in COMPOSITE_AS_BLOCK:
                self.ctx.push_state(properties)
                try:
                    super().draw_composite_entity(entity, properties)
                finally:
                    self.ctx.pop_state()
            else:
                super().draw_composite_entity(entity, properties)

        def skip_entity(self, entity, msg):
            # «invisible» — выключенное в самом файле (невидимый объект),
            # это не «не смогли показать».
            if msg == 'invisible':
                return
            try:
                dxftype = entity.dxftype()
            except Exception:
                dxftype = '?'
            if msg.startswith('3D'):
                label = 'текст не в плоскости чертежа'
            else:
                label = SKIPPED_LABELS.get(dxftype, OTHER_LABEL)
            self.skipped[label] = self.skipped.get(label, 0) + 1

    return CountingFrontend


def _configuration(solid_lines, min_dash_length=0.1):
    from ezdxf.addons.drawing.config import (
        BackgroundPolicy, ColorPolicy, Configuration, HatchPolicy, ImagePolicy,
        LinePolicy, ProxyGraphicPolicy,
    )
    return Configuration(
        # Штрих короче этого (в единицах чертежа) ezdxf удлиняет до него.
        # По умолчанию 0,1 — и осевая с мелким масштабом типа линии на метр
        # длины давала тысячи кусочков: 3000 таких линий рисовались 20 с.
        min_dash_length=min_dash_length,
        # Белый лист: ACI 7 становится чёрным, остальное — цветом файла.
        background_policy=BackgroundPolicy.WHITE,
        color_policy=ColorPolicy.COLOR,
        # Штриховка — контуром: узор на тысячи линий и сплошная заливка
        # закрыли бы деталь, а смотрят чертёж ради контура.
        hatch_policy=HatchPolicy.SHOW_OUTLINE,
        hatching_timeout=2.0,
        # Картинка — рамкой. DISPLAY открыл бы файл с диска сервера по пути,
        # записанному в чужом чертеже.
        image_policy=ImagePolicy.RECT,
        proxy_graphic_policy=ProxyGraphicPolicy.SHOW,
        line_policy=LinePolicy.SOLID if solid_lines else LinePolicy.ACCURATE,
    )


def _draw(doc, layout, limits, deadline, solid_lines, min_dash_length=0.1):
    """Нарисовать один лист. -> dict с путями или None, если на листе пусто."""
    from ezdxf.addons.drawing import RenderContext, layout as page_layout
    from ezdxf.math import BoundingBox2d, Vec2

    ctx = RenderContext(doc)
    # Ключ слоя — имя в нижнем регистре (как у ezdxf): включён ли слой в
    # файле и как он назван в таблице слоёв.
    original = {}
    table_names = {}

    def open_layers(layer_properties):
        # Выключенные и замороженные слои рисуем — человек включит их
        # галочкой. В окне они стоят снятыми, как в файле. Defpoints — нет:
        # это служебные точки размеров, AutoCAD их не печатает.
        for item in layer_properties:
            key = item.layer.lower()
            original.setdefault(key, bool(item.is_visible))
            table_names.setdefault(key, item.layer)
            if key != 'defpoints':
                item.is_visible = True

    ctx.set_layer_properties_override(open_layers)

    layer_of_handle = {}
    for entity in layout:
        try:
            layer_of_handle[entity.dxf.handle] = entity.dxf.layer
        except Exception:
            continue

    sink = _Sink(layer_of_handle, limits, deadline)
    backend = _make_backend_classes()(sink)
    frontend = _make_frontend_class()(
        ctx, backend, config=_configuration(solid_lines, min_dash_length))
    frontend.deadline = deadline
    frontend.max_entities = limits['entities']
    frontend.skipped = {}
    frontend.draw_layout(layout, finalize=True)

    # Габарит и рамка листа — по слоям, включённым в файле: выключенный или
    # замороженный слой со старым мусором в ста метрах сбоку иначе делал
    # видимый чертёж точкой в углу, а габарит — «100 010 × 100 000 мм».
    # Так считает и AutoCAD («Показать до границ»). Все слои выключены —
    # по всем.
    boxes = _layer_boxes(backend.player(), sink.layer_of)
    box = _union(item for key, item in boxes.items() if original.get(key, True))
    if not box.has_data:
        box = _union(boxes.values())
    if not box.has_data:
        return None
    width, height = box.size.x, box.size.y
    if not (_finite(box.extmin) and _finite(box.extmax)
            and math.isfinite(width) and math.isfinite(height)):
        raise Refusal(BAD_SIZE)
    # Линия без высоты (или ширины) дала бы пустой лист: ezdxf округляет
    # размер листа до 0,1 мм. Добираем меньшую сторону до тысячной доли
    # большей. Одна точка — рамка в единицу чертежа.
    side = max(width, height)
    least = side / 1000.0 if side > 0 else 1.0
    pad_x = max(0.0, least - width) / 2.0
    pad_y = max(0.0, least - height) / 2.0
    render_box = BoundingBox2d([
        Vec2(box.extmin.x - pad_x, box.extmin.y - pad_y),
        Vec2(box.extmax.x + pad_x, box.extmax.y + pad_y),
    ])
    # Масштаб листа — чтобы большая сторона была около метра: ezdxf округляет
    # лист до 0,1 мм, и у чертежа в метрах (деталь 0,04 м) без этого
    # получился бы лист нулевой ширины.
    settings = page_layout.Settings(scale=1000.0 / max(render_box.size.x, render_box.size.y))
    root = backend.get_xml_root_element(
        page_layout.Page(0, 0, page_layout.Units.mm, margins=page_layout.Margins.all(0)),
        settings=settings, render_box=render_box,
    )
    view_box = (root.get('viewBox') or '').split()
    if len(view_box) != 4 or not sink.items:
        return None

    # Рамки слоёв — уже в координатах путей: get_xml_root_element перевёл
    # записи ezdxf на месте (player() отдаёт те же записи).
    out_boxes = _layer_boxes(backend.player(), sink.layer_of)
    layers = []
    for name in sink.layer_names:
        key = name.lower()
        layer = {
            'name': table_names.get(key, name),
            'color': _layer_color(ctx, name),
            'on': original.get(key, True),
        }
        frame = _box_list(out_boxes.get(key))
        if frame:
            layer['box'] = frame
        layers.append(layer)
    return {
        'viewbox': [int(float(view_box[2])), int(float(view_box[3]))],
        'layers': layers,
        'palette': sink.colors,
        'items': [[item[0], item[1], item[2], ' '.join(item[3])] for item in sink.items],
        'extent': [box.size.x, box.size.y],
        'skipped': frontend.skipped,
        'entities': frontend.drawn,
        'chars': sink.chars,
        'hidden_layers': sorted(layer['name'] for layer in layers if not layer['on']),
    }


def _layer_boxes(player, layer_of):
    """{слой в нижнем регистре: BoundingBox2d} — рамка нарисованного по слоям.

    Слой — как у путей в окне (_Sink.layer_of): части размера — слоем
    размера. Одним проходом по записям ezdxf — тем же, каким он сам считает
    общую рамку (Player.update_bbox).
    """
    from ezdxf.math import BoundingBox2d
    boxes = {}
    for record, properties in player.recordings():
        frame = record.bbox()
        if not frame.has_data:
            continue
        key = layer_of(properties).lower()
        target = boxes.get(key)
        if target is None:
            target = boxes[key] = BoundingBox2d()
        target.extend(frame)
    return boxes


def _union(frames):
    from ezdxf.math import BoundingBox2d
    total = BoundingBox2d()
    for frame in frames:
        if frame.has_data:
            total.extend(frame)
    return total


def _finite(vector):
    return math.isfinite(vector.x) and math.isfinite(vector.y)


def _box_list(frame):
    """Рамка -> [x0, y0, x1, y1] целыми наружу; бесконечная — None."""
    if frame is None or not frame.has_data:
        return None
    if not (_finite(frame.extmin) and _finite(frame.extmax)):
        return None
    return [math.floor(frame.extmin.x), math.floor(frame.extmin.y),
            math.ceil(frame.extmax.x), math.ceil(frame.extmax.y)]


def _layer_color(ctx, name):
    """Цвет слоя для образца в списке: как у его линий на белом листе."""
    from ezdxf.addons.drawing.properties import layer_key
    props = ctx.layers.get(layer_key(name))
    if props is None:
        return '#000000'
    if getattr(props, 'has_aci_color_7', False):
        return '#000000'
    color = (props.color or '#000000')[:7].lower()
    return color if re.match(r'^#[0-9a-f]{6}$', color) else '#000000'


def _is_model(layout):
    return (getattr(layout, 'name', '') or '').lower() == 'model'


def _units(doc, layout):
    """{code, label, assumed, factor} — единицы листа и множитель в мм.

    Модель — $INSUNITS заголовка (единицы записи блока модели, layout.units,
    ezdxf честно называет непонятными, и они почти всегда пусты). Лист —
    единицы бумаги его настройки печати: мм или дюймы.
    """
    code = 0
    try:
        if _is_model(layout):
            code = int(doc.header.get('$INSUNITS', 0) or 0)
        else:
            paper = layout.dxf_layout.dxf.get('plot_paper_units', 1)
            code = 1 if paper == 0 else 4
    except Exception:
        code = 0
    label, fallback = UNIT_LABELS.get(code, ('код %d' % code, 1.0))
    factor = fallback
    if code:
        try:
            from ezdxf.units import conversion_factor
            factor = float(conversion_factor(code, 4))
        except Exception:
            factor = fallback
    return {'code': code, 'label': label, 'assumed': code == 0, 'factor': factor}


def _layouts(doc):
    """Модель, затем непустые листы по порядку вкладок."""
    yield doc.modelspace()
    try:
        names = doc.layouts.names_in_taborder()
    except Exception:
        names = []
    for name in names:
        if name.lower() == 'model':
            continue
        try:
            sheet = doc.layouts.get(name)
        except Exception:
            continue
        if len(sheet):
            yield sheet


def _dashed_in_use(doc, layout):
    """Есть ли на листе штриховые линии — по слоям и объектам листа."""
    try:
        for layer in doc.layers:
            if str(layer.dxf.linetype).upper() not in SOLID_LINETYPES:
                return True
        for entity in layout:
            linetype = entity.dxf.get('linetype', 'BYLAYER')
            if str(linetype).upper() not in SOLID_LINETYPES:
                return True
    except Exception:
        return True
    return False


def _min_dash_length(doc, layout):
    """Самый короткий штрих — тысячная доля диагонали чертежа.

    Короче его штрих на вписанном чертеже меньше точки экрана, а кусочков
    ezdxf нарезает тем больше, чем он короче. Габарит — из заголовка
    ($EXTMIN/$EXTMAX, его пишет AutoCAD), а если там пусто — счётом ezdxf.
    """
    size = None
    try:
        if _is_model(layout):
            low, high = doc.header.get('$EXTMIN'), doc.header.get('$EXTMAX')
            if low is not None and high is not None:
                dx, dy = high[0] - low[0], high[1] - low[1]
                if 0 < dx < 1e15 and 0 < dy < 1e15:
                    size = (dx * dx + dy * dy) ** 0.5
        if size is None:
            from ezdxf import bbox
            box = bbox.extents(layout, fast=True)
            if box.has_data:
                size = (box.size.x ** 2 + box.size.y ** 2) ** 0.5
    except Exception:
        size = None
    return max(0.1, (size or 0.0) / 1000.0)


def _render_layout(doc, layout, limits, started, deadline):
    """Лист — в пути. Штриховые линии, не уложившиеся в пределы, — сплошными.

    Первый заход рисует как в файле. Если штриховые линии раздули ответ или
    съели время — второй заход рисует их сплошными. Чтобы на него осталось
    время, первому заходу при штриховых линиях дано 60 % срока.
    """
    dashed = _dashed_in_use(doc, layout)
    if not dashed:
        result = _draw(doc, layout, limits, deadline, solid_lines=False)
        if result is not None:
            result['solid'] = False
        return result
    first_deadline = started + (deadline - started) * 0.6
    try:
        result = _draw(doc, layout, limits, first_deadline, solid_lines=False,
                       min_dash_length=_min_dash_length(doc, layout))
        if result is not None:
            result['solid'] = False
        return result
    except _Abort as exc:
        if exc.what not in ('time', 'items', 'chars'):
            raise
    result = _draw(doc, layout, limits, deadline, solid_lines=True)
    if result is not None:
        result['solid'] = True
    return result


def _skipped_summary(skipped):
    total = sum(skipped.values())
    by_label = sorted(skipped.items(), key=lambda pair: (-pair[1], pair[0]))
    return {'total': total, 'by_label': [[label, count] for label, count in by_label]}


def _refusal(reason, cache=True):
    return {'ok': False, 'reason': reason, 'cache': cache, 'version': PAYLOAD_VERSION}


def _slow_refusal(reason):
    """Отказ по времени: надолго не запоминается (сервер мог быть занят), но
    и каждое открытие не должно снова занимать процесс на 40 с — models/
    drawing.py помнит его сутки (признак slow)."""
    result = _refusal(reason, cache=False)
    result['slow'] = True
    return result


def render(blob, limits=None):
    """Байты DXF -> ответ окну просмотра (см. шапку файла)."""
    started = time.monotonic()
    limits = dict(DEFAULT_LIMITS, **(limits or {}))
    deadline = started + limits['deadline']
    try:
        if not blob:
            raise Refusal("Файл пустой.")
        if len(blob) > limits['file_bytes']:
            raise Refusal("Чертёж весит %s — больше предела просмотра (%s). Файл можно "
                          "скачать и открыть у себя." % (_mb(len(blob)), _mb(limits['file_bytes'])))
        kind = sniff(blob)
        if kind is None:
            raise Refusal(NOT_DXF)
        if kind == 'ascii':
            objects = count_zero_tags(blob, stop_after=limits['zero_tags'])
            if objects > limits['zero_tags']:
                raise Refusal("В чертеже больше %s объектов — для просмотра в браузере "
                              "это слишком много. Файл можно скачать и открыть у себя."
                              % _num(limits['zero_tags']))
        try:
            import ezdxf  # noqa: F401
            from ezdxf.addons import drawing  # noqa: F401
        except ImportError:
            raise Refusal(UNAVAILABLE, cache=False) from None
        import logging
        # ezdxf пишет в журнал каждую мелочь разбора — в stderr процесса.
        logging.getLogger('ezdxf').setLevel(logging.ERROR)

        doc, notes, truncated = load(blob)
        result = None
        for layout in _layouts(doc):
            result = _render_layout(doc, layout, limits, started, deadline)
            if result is not None:
                result['layout'] = layout.name
                result['units'] = _units(doc, layout)
                break
        if result is None:
            raise Refusal(TRUNCATED if truncated else EMPTY)

        if result.pop('solid'):
            notes.append("Чертёж очень подробный: штриховые линии показаны сплошными.")
        if result['layout'].lower() != 'model':
            notes.append("В модели пусто — показан лист «%s»." % result['layout'])
        units = result.pop('units')
        factor = units.pop('factor')
        if units['assumed']:
            notes.append("Единицы в файле не заданы — размеры показаны как миллиметры.")
        hidden = result.pop('hidden_layers')
        if hidden:
            notes.append("Слоёв выключено в самом файле: %d — они не показаны, включить "
                         "можно в списке слоёв." % len(hidden))
        skipped = _skipped_summary(result.pop('skipped'))
        if skipped['total']:
            notes.append("Не показано объектов: %s (%s)." % (
                _num(skipped['total']),
                ', '.join('%s — %s' % (label, _num(count)) for label, count in skipped['by_label'])))
        extent = result.pop('extent')
        entities = result.pop('entities')
        chars = result.pop('chars')
        # Переполнение габарита в мм (координаты 1e300 в км) дало бы
        # Infinity — недопустимый JSON, и окно ответило бы «Connection lost».
        size_mm = [round(extent[0] * factor, 3), round(extent[1] * factor, 3)]
        if not all(math.isfinite(value) for value in size_mm):
            raise Refusal(BAD_SIZE)
        result.update({
            'ok': True,
            'version': PAYLOAD_VERSION,
            'size_mm': size_mm,
            'units': units,
            'notes': notes,
            'skipped': skipped,
            'stats': {'entities': entities, 'items': len(result['items']), 'chars': chars,
                      'seconds': round(time.monotonic() - started, 2)},
            'cache': True,
        })
        return result
    except Refusal as exc:
        return _refusal(exc.reason, exc.cache)
    except _Abort as exc:
        if exc.what == 'time':
            return _slow_refusal(SLOW)
        if exc.what == 'entities':
            return _refusal("В чертеже больше %s объектов вместе с содержимым блоков — для "
                            "просмотра в браузере это слишком много. Файл можно скачать."
                            % _num(limits['entities']))
        return _refusal("Чертёж слишком подробный для просмотра в браузере. Файл можно "
                        "скачать и открыть у себя.")
    except RecursionError:
        return _refusal("Блок в чертеже вставлен сам в себя — нарисовать его нельзя. "
                        "Файл можно скачать.")
    except MemoryError:
        return _refusal("Чертёж слишком большой: на его разбор не хватило памяти. "
                        "Файл можно скачать и открыть у себя.")


# ═══════════════════════════════════════════════════════════════════════════
# 4. ЗАПУСК ОТДЕЛЬНЫМ ПРОЦЕССОМ
# ═══════════════════════════════════════════════════════════════════════════
def _limit_resources():
    """Предел памяти и процессора — первым делом, до чтения файла."""
    try:
        import resource
    except ImportError:                                      # pragma: no cover
        return
    for limit, value in ((resource.RLIMIT_AS, MEMORY_LIMIT), (resource.RLIMIT_CPU, CPU_LIMIT)):
        try:
            soft, hard = resource.getrlimit(limit)
            if hard != resource.RLIM_INFINITY:
                value = min(value, hard)
            if soft == resource.RLIM_INFINITY or soft > value:
                resource.setrlimit(limit, (value, hard))
        except (ValueError, OSError):
            pass


def main():
    _limit_resources()
    blob = sys.stdin.buffer.read()
    out = sys.stdout.buffer
    # ezdxf печатает часть ошибок прокси-графики в stdout (print) — это
    # испортило бы ответ. Всё печатное — в stderr, ответ — только наш.
    sys.stdout = sys.stderr
    try:
        result = render(blob)
    except MemoryError:
        result = _refusal("Чертёж слишком большой: на его разбор не хватило памяти. "
                          "Файл можно скачать и открыть у себя.")
    except Exception as exc:                                  # чужой файл — что угодно
        # Не запоминаем: сбой мог быть нашим, и после исправления
        # рисовальщика тот же файл должен открыться сразу.
        result = _refusal(BROKEN, cache=False)
        result['detail'] = repr(exc)[:300]
    out.write(dump(result))
    out.flush()


def dump(result):
    """Ответ -> байты JSON. Бесконечность и NaN JSON не допускает (браузер
    не разберёт ответ и покажет «Connection lost») — тогда отказ словами."""
    try:
        text = json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    except ValueError:
        text = json.dumps(_refusal(BAD_SIZE), ensure_ascii=False, separators=(',', ':'))
    return text.encode('utf-8')


if __name__ == '__main__':
    main()
