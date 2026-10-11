# -*- coding: utf-8 -*-
"""Лид из письма: телефон из подписи и ИНН из текста (шаг З-14, 10.10.2026).

ЗАЧЕМ. Письмо Кытмановой (09.10) подписано «Тел.: +7 (924) 916-84-62», а
в лид попал общий телефон филиала из карточки компании: подпись никто не
читал. Здесь — правила, модель (models/mail_client_message.py,
_pmk_create_lead) зовёт их сама:
  • own_lines — видимый текст письма по строкам БЕЗ цитаты: свёрнутое
    «···» (tools/quote_fold.py) и всё, что ниже строки-шапки цитаты
    («-----Original Message-----», «… пишет:», «From:/От:»). В цитате
    ответа — наша же подпись, и её телефон клиенту не принадлежит;
  • signature_phone — российский номер в последних строках своей части:
    +7/8, скобки, пробелы, дефисы; ровно 11 цифр. Мобильный (9xx) главнее
    городского: подпись человека обычно с мобильным, а городской — общий
    номер компании. 8-800, строки реквизитов (ИНН, ОГРН, р/с…) и свои
    телефоны завода не берём;
  • ИНН ищет tools-функция pmk_partner (partner_keys.inns_in) — здесь только
    текст для неё.

ЧИСТЫЕ ФУНКЦИИ БЕЗ ODOO, как lead_text:

    python3 experiments/odoo/addons/pmk_mail_ui/tests/test_signature_rules.py
"""
import html
import re

from lxml import etree
from lxml import html as lxml_html

from . import quote_fold

# Строки, после которых в письме — цитата прежней переписки.
_QUOTE_START = re.compile(
    r"^\s*(?:-{2,}\s*(?:Original Message|Исходное сообщение|Исходное письмо"
    r"|Пересылаемое сообщение|Forwarded message)"
    r"|(?:From|От кого|От)\s*:.*@"
    r"|.*(?:wrote|пишет|писал\(а\)|написал\(а\)|написала?)\s*:\s*$"
    r"|>)",
    re.IGNORECASE)
# Шапка цитаты без «пишет:» в одной короткой строке с адресом:
#   • Mail.ru — дата И время: «24.09.2026, 15:00, Владимир Голубенко
#     <pmkpark@mail.ru>» (письмо Метпрома 24.09);
#   • Gmail — время и двоеточие в конце: «пн, 5 окт. 2026 г. в 10:00, Завод
#     <zakaz@pmkpark.ru>:».
# Строка подписи или текста с адресом и датой шапкой НЕ считается: «E-mail:
# 6574@x.ru, пн–пт 9:00–18:00» (есть слово-подпись), «Ответ просим до
# 15.10.2026 на snab@x.ru» (дата без времени) — иначе подпись с телефоном и
# ИНН ниже неё отрезалась бы вместе с цитатой.
_ADDRESS = re.compile(r"[^\s@<>()]+@[^\s@<>()]+\.[^\s@<>()]+")
_DATE = re.compile(r"\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{4}-\d{2}-\d{2}")
_TIME = re.compile(r"(?<![\d:])\d{1,2}:\d{2}(?![\d:])")
_SIGNATURE_WORDS = re.compile(
    r"\b(?:тел|телефон|моб|мобильный|факс|e-?mail|почта|сайт|режим|график"
    r"|пн|вт|ср|чт|пт|сб|вс|phone|tel|fax|site|web)\b",
    re.IGNORECASE)
_HEADER_MAX = 250
_BLOCKS = frozenset({
    "p", "div", "br", "tr", "li", "ul", "ol", "table", "h1", "h2", "h3", "h4",
    "h5", "h6", "blockquote", "pre", "hr", "section", "article", "header",
    "footer", "address", "dd", "dt",
})
_CELLS = frozenset({"td", "th"})
_INVISIBLE = ".//style|.//script|.//head|.//title"
_FOLDED = ('.//details[contains(concat(" ", normalize-space(@class), " "), " %s ")]'
           % quote_fold.FOLD_CLASS)
_SPACES = re.compile(r"[ \t\r\f\v   ]+")
MAX_CHARS = 1024 * 1024


def visible_lines(html_text, drop_folded=True):
    """Видимый текст разметки по строкам, без пустых."""
    text = str(html_text or "")
    if not text.strip() or len(text) > MAX_CHARS:
        return []
    try:
        root = lxml_html.fragment_fromstring(text, create_parent="div")
    except (etree.LxmlError, ValueError, TypeError):
        return []
    for el in root.xpath(_INVISIBLE + ("|" + _FOLDED if drop_folded else "")):
        el.drop_tree()
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        if el.tag in _BLOCKS:
            el.tail = "\n" + (el.tail or "")
            if el.tag != "br":
                el.text = "\n" + (el.text or "")
        elif el.tag in _CELLS:
            el.tail = " " + (el.tail or "")
    raw = html.unescape(root.text_content())
    lines = []
    for line in raw.split("\n"):
        line = _SPACES.sub(" ", line).strip()
        if line:
            lines.append(line)
    return lines


def own_lines(html_text, subject=None):
    """Строки письма без цитаты прежней переписки (см. описание модуля).
    Пересылка («Fwd:») — содержание целиком: её quote_fold не сворачивает."""
    folded, _rule = quote_fold.fold_quotes(html_text, subject)
    lines = visible_lines(folded)
    for index, line in enumerate(lines):
        if index and _is_quote_start(line):
            return lines[:index]
    return lines


def _is_quote_start(line):
    if _QUOTE_START.match(line):
        return True
    if len(line) > _HEADER_MAX or not _ADDRESS.search(line) or not _TIME.search(line):
        return False
    if line.rstrip().endswith(":"):
        return True
    if _SIGNATURE_WORDS.search(_ADDRESS.sub(" ", line)):
        return False
    return bool(_DATE.search(line))


# ----------------------------------------------------------------------
# телефон
# ----------------------------------------------------------------------
_DASH = r"[\s\-‐‑–—.]*"
_PHONE = re.compile(
    r"(?<![\d+])(?:\+\s*7|8)" + _DASH + r"\(?\s*\d{3,5}\s*\)?" + _DASH
    + r"\d{1,3}" + _DASH + r"\d{2}" + _DASH + r"\d{2}(?!\d)")
_REQUISITES = re.compile(
    r"\b(?:ИНН|КПП|ОГРН|ОГРНИП|ОКПО|ОКВЭД|БИК|ОКТМО)\b|р\s*/\s*с|к\s*/\s*с"
    r"|расч[её]тн|корр?\.?\s*сч|сч[её]т\s*№", re.IGNORECASE)
TAIL_LINES = 15


def phone_digits(text):
    """Номер как 10 цифр без кода страны — для сравнения: «+7 (924)
    916-84-62», «8-924-916-84-62» и «89249168462» → «9249168462»."""
    digits = re.sub(r"\D", "", text or "")
    if len(digits) == 11 and digits[0] in "78":
        return digits[1:]
    return digits[-10:] if len(digits) >= 10 else ""


def _clean(found):
    return re.sub(r"\s+", " ", found).strip()


def signature_phone(lines, own_phones=()):
    """Телефон из подписи: последние TAIL_LINES строк своей части письма.
    Мобильный главнее городского; иначе — первый сверху. Ничего — пусто."""
    own = {phone_digits(phone) for phone in own_phones or ()}
    own.discard("")
    first = ""
    for line in list(lines or ())[-TAIL_LINES:]:
        if _REQUISITES.search(line):
            continue
        for match in _PHONE.finditer(line):
            found = match.group(0)
            digits = phone_digits(found)
            if len(re.sub(r"\D", "", found)) != 11 or not digits:
                continue
            if digits.startswith("800") or digits in own:
                continue
            if digits.startswith("9"):
                return _clean(found)
            first = first or _clean(found)
    return first


def letter_text(lines):
    """Строки одним текстом — для поиска ИНН."""
    return "\n".join(lines or ())
