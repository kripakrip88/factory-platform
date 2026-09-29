# -*- coding: utf-8 -*-
"""Картинки по адресу без «http» (разбор UX, Г13, 29.09.2026).

Модуль почты глушит в письме только «http(s)://…» (его mail_client_message.py,
_RE_REMOTE_ATTR и _RE_REMOTE_CSS_URL). Мимо проходили два сорта адресов:

  «//tracker/p.gif» — браузер достраивает до https://tracker/p.gif, и
    отправитель узнаёт, что письмо открыто, без «Показать картинки»;
  «/web/session/logout», «../web/…», «web/…» — путь без адреса браузер
    достраивает до НАШЕГО сервера. В чате лида и в окне ответа письмо стоит
    прямо на странице Odoo — запрос уходит с сессией в любом браузере, и одна
    такая «картинка» разлогинивает каждого, кто откроет лид
    (/web/session/logout отвечает на GET). В окне письма (рамка без
    allow-same-origin) Chrome ходит туда без входа, но у cookie session_id
    нет SameSite, и Firefox её, скорее всего, отдаёт.
    С шага 17 (29.09.2026) у рамки письма allow-same-origin (без него окно
    почты не видит высоту письма): запрос из окна письма теперь уходит с
    сессией в любом браузере, и для окна письма эта глушилка — единственная
    защита. Ослаблять её нельзя.

Поэтому правило обратное вендорскому: не «что запретить», а «что оставить».
  своё  — data: и cid: (части самого письма, сеть не трогают) — оставляем;
  чужое — https://…, //… — глушим до «Показать картинки»;
  к нам — всё прочее: путь, относительный путь, наш сервер по полному адресу,
          about:, blob:, пустой адрес — глушим ВСЕГДА, кнопка их не
          возвращает. Письмо со стороны не может сослаться на что-то полезное
          у нас — только на то, что у нас что-то сделает.

РАЗБИРАЕМ РАЗМЕТКУ, КАК БРАУЗЕР, А НЕ ИЩЕМ ТЕГИ РЕГУЛЯРКОЙ. Первая версия
искала «<имя …>» без «<» и «>» внутри, полагаясь на то, что html_sanitize
пишет их в значениях как &lt; &gt;. Это неверно: libxml2 оставляет как есть
«<!--…-->» внутри значения атрибута (правило для server side include в
xmlEncodeEntitiesInternal; проверено на 2.9.14 сервера, 29.09.2026).
<img alt="<!--x-->" src="/web/session/logout"> проходил санитайзер целиком,
регулярка тега не находила, и src оставался живым — в окне письма, в чате
лида и в цитате ответа. А на строке «<aaaa…» без «>» та регулярка работала
за квадрат длины: письмо в 100 КБ вешало воркер.

Учесть кавычки в той же регулярке мало: санитайзер сохраняет комментарии
как есть, и непарная кавычка в <!-- <a title="x --> растягивала «тег» до
кавычки в следующем комментарии, пряча между ними настоящий <img src=…>
(проверено: такое письмо санитайзер сервера тоже пропускает). Поэтому идём
слева направо по правилам HTML (раздел «Tokenization»):
  <!--…-->            комментарий: до первого «-->» или «--!>», «<!-->» и
                      «<!--->» — пустые, без конца — до конца текста;
  <!…>, <?…>, </…>    служебное: до первого «>» (так их читает браузер —
                      DOCTYPE, ложный комментарий, <?php …?>, который
                      санитайзер тоже сохраняет);
  <буква, </буква     тег: имя, потом атрибуты (см. ниже) до «>» вне кавычек;
  прочее «<»          просто текст.
Внутри комментария браузер ничего не грузит, но теги там тоже глушим —
про запас: если где-то (другой разборщик, будущая правка санитайзера)
комментарий прочтут иначе, живого адреса в нём не окажется. Разбор линейный:
каждый знак читается не больше двух раз.

АТРИБУТЫ — ПО ПОРЯДКУ, КАК ИХ ЧИТАЕТ БРАУЗЕР. Прототип искал «src=» поиском
по тексту тега, и значение соседнего атрибута могло его обмануть:
<img title="x src='" src="//t/p.gif" alt="'"> — поиск принимал
«src='" src="//t/p.gif" alt="'» за один атрибут в одинарных кавычках и глушил
его, а браузер видел живой src="//t/p.gif". Здесь тег разбирается слева
направо по правилам HTML (имя, «=», значение в кавычках или без), и то, что
мы считаем атрибутом, совпадает с тем, что считает браузер. Все атрибуты тега
проходят за один заход — ловушки вендора «глушится только первый атрибут в
теге» тоже нет.

ЧИСТЫЕ ФУНКЦИИ, БЕЗ ODOO: правила проверяются голым питоном ещё до деплоя —

    python3 experiments/odoo/addons/pmk_mail_ui/tests/test_asset_rules.py
"""
import html
import re
from urllib.parse import unquote

KEEP, REMOTE, LOCAL = "keep", "remote", "local"

# Атрибуты, по которым браузер сам что-то грузит. lowsrc/dynsrc браузеры не
# понимают, <object data>, <embed>, <link>, <iframe> вырезает санитайзер.
URL_ATTRS = ("src", "srcset", "background", "poster")
# Атрибуты-текст и ссылки: «url(» в них — просто слова, браузер по ним ничего
# не грузит. Остальные проверяются на url() по содержимому (см. attribute()).
TEXT_ATTRS = ("href", "alt", "title")

# Пробел в разметке HTML — только эти пять знаков. «\s» питона шире (он
# считает пробелом и неразрывный), и разбор разошёлся бы с браузером: там, где
# браузер видит одно значение без кавычек, мы увидели бы два атрибута.
_WS = "\t\n\f\r "
# Где начинается разметка: комментарий, тег (открывающий или закрывающий) или
# служебное «<!», «<?», «</» без буквы. Одинокое «<» пропускает сам поиск.
_MARKUP = re.compile(r"<(?:(!--)|(/?[A-Za-z])|[!?/])")
# Внутри комментария — только теги.
_MARKUP_TAG = re.compile(r"</?[A-Za-z]")
# Конец комментария («--!>» браузер тоже принимает).
_COMMENT_CLOSE = re.compile(r"--!?>")
# Имя тега — до пробела, «/» или «>» (прочие знаки, и «<» тоже, браузер
# считает частью имени).
_TAG_NAME = re.compile(r"</?[A-Za-z][^%s/>]*" % _WS)
# Между атрибутами — пробелы и «/» (<img/src=…> браузер читает как <img src=…>).
_ATTR_GAP = re.compile(r"[%s/]*" % _WS)
# Атрибут по правилам HTML: имя — до пробела, «/», «>» или «=» (сам «=» бывает
# только первой буквой имени); значение — в двойных кавычках, в одинарных или
# без кавычек до пробела. Кавычки и «=» внутри значения без кавычек браузер
# тоже считает значением.
_ATTR = re.compile(
    r"""(=?[^%(ws)s/>=]+|=)(?:([%(ws)s]*=[%(ws)s]*)("[^"]*"|'[^']*'|[^%(ws)s>]*))?"""
    % {"ws": _WS})

# Аргумент url() — до первой «)». Если «)» есть в самом адресе, хвост
# останется после url(about:blank) мусором, объявление станет неверным и
# браузер его выбросит: решение принимается по началу адреса. Незакрытый
# url( в конце стиля браузер тоже грузит — ловим и его.
_CSS_URL = re.compile(r"url\(([^)]*)(?:\)|\Z)", re.IGNORECASE)
# image-set("…" 1x) грузит картинку без url(). В письмах не встречается —
# ломаем всегда. Проверка «(?<![\w-])» — чтобы повтор не дописал приставку дважды.
_CSS_IMAGE_SET = re.compile(r"(?<![\w-])((?:-webkit-)?image-set)(\s*\()", re.IGNORECASE)
# Как браузер чистит адрес: пробелы и управляющие знаки по краям, табуляцию и
# перевод строки — везде; «\» для http(s) — то же, что «/». В background,
# poster и srcset санитайзер их не экранирует: «/\n/t» и «\\t» — это «//t».
_URL_EDGE = re.compile(r"^[\x00-\x20]+|[\x00-\x20]+$")
_URL_TAB_NL = re.compile(r"[\t\n\r]")
_AUTHORITY = re.compile(r"^(?:https?:)?/{2,}([^/?#]*)")
# srcset: разделители между кандидатами и адрес кандидата (см. _srcset_urls).
_SRCSET_GAP = re.compile(r"[%s,]*" % _WS)
_SRCSET_URL = re.compile(r"[^%s]+" % _WS)
_CSS_ESCAPE = re.compile(r"\\(?:([0-9a-fA-F]{1,6})\s?|(.))", re.DOTALL)
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
# Наш сервер по полному адресу — «к нам», кроме картинок, которые Odoo сам
# кладёт в свои исходящие (логотип, /web/image с токеном): клиент возвращает
# их в цитате. Они только читают — отдаём их кнопке, как чужие. «..» и «%2e»
# браузер схлопывает («/web/image/../session/logout») — такие не пускаем.
OWN_SAFE_PATHS = ("/web/image/", "/web/content/", "/logo.png")


def _unquote(value):
    """(кавычка, значение) атрибута. Незакрытая кавычка — не кавычка: такое
    значение браузер читает целиком, вместе с ней."""
    if len(value) >= 2 and value[0] in ("\"", "'") and value[-1] == value[0]:
        return value[0], value[1:-1]
    return "", value


def _host(authority):
    """Хост так, как его поймёт браузер: без логина и порта, с раскрытыми %xx
    и IDNA («ｅｒｐｐａｒｋ。ru» — тоже erppark.ru). Не разобрать — None."""
    host = unquote(authority.rsplit("@", 1)[-1])
    if host.startswith("["):
        return host
    try:
        host = host.split(":", 1)[0].encode("idna").decode("ascii")
    except UnicodeError:
        return None
    return host.rstrip(".").lower()


def url_kind(raw, own_hosts, css=False):
    """KEEP, REMOTE или LOCAL для одного адреса (значение атрибута или
    аргумент url() — как есть в тексте письма, с &quot; и прочим)."""
    url = html.unescape(raw)
    if css:
        url = url.strip(" \t\n\r\f\"'")
        # Экранирование внутри адреса («\2f\2f t/p.gif» = «//t/p.gif»)
        # честному письму не нужно.
        if "\\" in url:
            return LOCAL
    url = _URL_TAB_NL.sub("", _URL_EDGE.sub("", url)).replace("\\", "/")
    low = url.lower()
    if low.startswith(("data:", "cid:")):
        return KEEP
    # В CSS «#f» — ссылка на фильтр внутри документа, about:blank — наша же
    # заглушка (так глушит и вендор): сети нет.
    if css and (low.startswith("#") or low == "about:blank"):
        return KEEP
    authority = _AUTHORITY.match(low)
    if not authority:
        return LOCAL
    host = _host(authority.group(1))
    if host is None:
        return LOCAL
    if any(host == own or host.endswith("." + own) for own in own_hosts):
        path = low[authority.end():]
        if (path.startswith(OWN_SAFE_PATHS)
                and "/." not in path and "%2e" not in path):
            return REMOTE
        return LOCAL
    return REMOTE


def _srcset_urls(value):
    """Адреса кандидатов srcset — по алгоритму браузера (HTML, «parse a
    srcset attribute»), а не «кандидат начинается после запятой».

    Запятая бывает и внутри адреса: в «data:image/gif;base64,R0lGOD, //t/x 2x»
    первый адрес — «data:…R0lGOD,», и прежний разбор принимал его запятую за
    разделитель, а «//t/x» после пробела не видел вовсе: srcset оставался
    живым, плашки «Показать картинки» не было, а экран 2x (ноутбук Retina,
    телефон) грузил трекер при открытии письма. Браузер делает так: адрес —
    всё до пробела; кончается запятыми — срезать их, это кандидат без
    описания; иначе описание («2x», «100w») идёт до запятой, но не внутри
    скобок. Кандидат, которого браузер потом отбросит за неверное описание,
    мы всё равно проверяем: лишняя проверка ничего не грузит.
    """
    urls, pos, end = [], 0, len(value)
    while True:
        pos = _SRCSET_GAP.match(value, pos).end()
        if pos >= end:
            return urls
        found = _SRCSET_URL.match(value, pos)
        url, pos = found.group(0), found.end()
        if url.endswith(","):
            urls.append(url.rstrip(","))
            continue
        urls.append(url)
        in_parens = False
        while pos < end:
            char = value[pos]
            pos += 1
            if in_parens:
                in_parens = char != ")"
            elif char == "(":
                in_parens = True
            elif char == ",":
                break


def srcset_kind(raw, own_hosts):
    """Худший из адресов набора: какой грузить, браузер решает сам."""
    kinds = {url_kind(url, own_hosts) for url in _srcset_urls(html.unescape(raw))}
    for kind in (LOCAL, REMOTE):
        if kind in kinds:
            return kind
    return KEEP if kinds else LOCAL


def css_unescape(text):
    """CSS так, как его прочтёт браузер: без комментариев, с раскрытыми
    «\\75» и «\\r». Нужно, чтобы увидеть url(), спрятанный экранированием."""
    def one(match):
        if match.group(1):
            code = int(match.group(1), 16)
            ok = 0 < code <= 0x10FFFF and not 0xD800 <= code <= 0xDFFF
            return chr(code) if ok else "\ufffd"
        return "" if match.group(2) == "\n" else match.group(2)
    return _CSS_ESCAPE.sub(one, _CSS_COMMENT.sub("", text))


def block_assets(html_text, own_hosts, allow_remote):
    """Заглушить всё, что грузится из сети, кроме частей самого письма.

    own_hosts — имена нашего сервера (поддомены — тоже наши).
    allow_remote — «Показать картинки» нажата: чужие адреса оставляем,
    адреса «к нам» глушим всё равно. Повторный проход ничего не меняет:
    заглушённый атрибут называется data-blocked-…, а url(about:blank) — своё.
    """
    if not html_text:
        return html_text

    def keep(kind):
        return kind == KEEP or (allow_remote and kind == REMOTE)

    def css_url(match):
        kind = url_kind(match.group(1), own_hosts, css=True)
        return match.group(0) if keep(kind) else "url(about:blank)"

    def style_value(value):
        """Новое значение style или None — «глушить весь стиль»."""
        value = _CSS_IMAGE_SET.sub(r"pmk-blocked-\1\2", _CSS_URL.sub(css_url, value))
        # «u\rl(…)», «\75 rl(…)» — тот же url(), спрятанный экранированием;
        # «&#117;rl(» — сущностью. Смотрим на стиль глазами браузера, и если
        # там остался url() не из «можно» или image-set — весь стиль уходит в
        # data-blocked-style: разбирать такой стиль по частям не стоит
        # (китайский «\5B8B\4F53» без url() цел).
        decoded = css_unescape(html.unescape(value)).lower()
        if _CSS_IMAGE_SET.search(decoded) or not all(
                keep(url_kind(u.group(1), own_hosts, css=True))
                for u in _CSS_URL.finditer(decoded)):
            return None
        return value

    def attribute(match):
        name, equals, raw = match.group(1), match.group(2), match.group(3)
        if equals is None:
            return match.group(0)       # атрибут без значения ничего не грузит
        lname = name.lower()
        quote, value = _unquote(raw)
        if lname in URL_ATTRS:
            kind = (srcset_kind(value, own_hosts) if lname == "srcset"
                    else url_kind(value, own_hosts))
            return match.group(0) if keep(kind) else "data-blocked-" + match.group(0)
        if lname == "style":
            value = style_value(value)
            if value is None:
                return "data-blocked-" + match.group(0)
            return "%s%s%s%s%s" % (name, equals, quote, value, quote)
        if lname not in TEXT_ATTRS and not lname.startswith("data-"):
            # Презентационные атрибуты SVG — mask, clip-path, fill, stroke,
            # marker-*, cursor, filter — берут url(), как CSS, и санитайзер их
            # оставляет. Chrome грузит mask="url(//трекер/x#m)" при открытии
            # письма (повторная проверка 29.09). Не списком имён, а по
            # содержимому: url() не из «можно» или image-set — атрибут глушим
            # целиком, как стиль.
            decoded = css_unescape(html.unescape(value)).lower()
            if "url(" in decoded or "image-set" in decoded:
                if _CSS_IMAGE_SET.search(decoded) or not all(
                        keep(url_kind(u.group(1), own_hosts, css=True))
                        for u in _CSS_URL.finditer(decoded)):
                    return "data-blocked-" + match.group(0)
        return match.group(0)

    return _markup(str(html_text), attribute)


def _markup(text, attribute, in_comment=False):
    """Текст, где каждый атрибут каждого тега прошёл через attribute(match).
    Слева направо, по правилам браузера (см. «РАЗБИРАЕМ РАЗМЕТКУ» вверху).
    in_comment — разбираем содержимое комментария: там только теги."""
    out, pos, end = [], 0, len(text)
    search = (_MARKUP_TAG if in_comment else _MARKUP).search
    while True:
        found = search(text, pos)
        if not found:
            break
        start = found.start()
        out.append(text[pos:start])
        if in_comment or found.group(2):
            pos = _tag(text, start, attribute, out)
        elif found.group(1):
            inside = start + 4
            inside_end, pos = _comment_bounds(text, inside)
            out.append(text[start:inside])
            out.append(_markup(text[inside:inside_end], attribute, in_comment=True))
            out.append(text[inside_end:pos])
        else:
            close = text.find(">", start + 1)
            pos = end if close < 0 else close + 1
            out.append(text[start:pos])
    out.append(text[pos:])
    return "".join(out)


def _comment_bounds(text, inside):
    """(конец содержимого, конец комментария) для «<!--», кончившегося на inside."""
    if text.startswith(">", inside):
        return inside, inside + 1               # <!-->
    if text.startswith("->", inside):
        return inside, inside + 2               # <!--->
    close = _COMMENT_CLOSE.search(text, inside)
    if not close:
        return len(text), len(text)             # без конца — до конца текста
    return close.start(), close.end()


def _tag(text, start, attribute, out):
    """Тег с позиции start (там «<буква» или «</буква») — в out; вернуть, где
    он кончился. Кончается на «>» вне значения в кавычках: значение в
    кавычках (и «<!--…-->» в нём) _ATTR берёт целиком."""
    name = _TAG_NAME.match(text, start)
    out.append(name.group(0))
    pos, end = name.end(), len(text)
    while pos < end:
        gap = _ATTR_GAP.match(text, pos)
        out.append(gap.group(0))
        pos = gap.end()
        if pos >= end:
            break
        if text[pos] == ">":
            out.append(">")
            return pos + 1
        # Совпадает всегда: здесь не пробел, не «/» и не «>», а имя атрибута —
        # любой другой знак.
        found = _ATTR.match(text, pos)
        out.append(attribute(found))
        pos = found.end()
    # Тег без «>» до конца текста браузер выбрасывает целиком — но атрибуты
    # мы уже проверили: другой разборщик (санитайзер чата лида) мог бы его
    # и закрыть.
    return end
