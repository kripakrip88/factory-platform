# -*- coding: utf-8 -*-
"""Свёрнутые цитаты в окне письма («···», шаг 20 плана, В2, 30.09.2026).

Ответ клиента почти всегда тащит за собой всю прежнюю переписку: письмо в
пять строк и под ним экраны цитат. Mail.ru прячет цитату под кнопку «···» —
делаем так же: цитату оборачиваем в

    <details class="pmk-quote" data-pmk-rule="…"><summary>···</summary>…</details>

<details> раскрывается без скриптов: работает в рамке письма без
allow-scripts и в запасном режиме шага 17 без allow-same-origin. Ctrl+F в
Chrome находит текст и в закрытом <details> и раскрывает его.

ТОЛЬКО ДЛЯ ПОКАЗА. Хранимое письмо (body_html), лид и цитата в ответе
(_quoted_body) берут исходник — свёрнутого там нет.

КАК ИЩЕМ. Идём по документу по порядку и берём ПЕРВЫЙ кандидат — он же
самый внешний. Если он вызывает сомнение, не сворачиваем НИЧЕГО: во
внутренние кандидаты отброшенного не спускаемся и дальше не ищем.
Кандидаты (правило пишется в data-pmk-rule):
  mailru      — mail.ru, веб: элемент с классом mail-quote-collapse*
                (при пересылке mail.ru приписывает к классам «_mr_css_attr»);
  mailru_app  — mail.ru, приложение: blockquote#mail-app-auto-quote; если
                обёртка #composeWebView_previouse_content больше ничего не
                держит — вместе с ней. Шапка голым текстом остаётся видна;
  gmail       — div.gmail_quote / div.gmail_quote_container;
  cite        — Thunderbird и Apple: blockquote[type=cite] вместе со
                строкой-шапкой перед ним (div.moz-cite-prefix, «… пишет:»);
  owa         — Outlook в браузере: div#divRplyFwdMsg (с <hr> перед ним) и
                всё после него;
  outlook     — Outlook настольный: шапка «From:/От:» с «Sent:/Отправлено:/
                To:/Кому:» в div с border-top:solid #E1E1E1 (#B5C4DF), через
                обёртки с единственным ребёнком, и всё после неё;
  separator   — строка «-----Original Message-----» / «Исходное сообщение» и
                всё после неё;
  header      — голый blockquote, перед которым строка-шапка: в конце «:», и
                в ней «пишет / wrote / написал(а)» или адрес ВМЕСТЕ с датой
                либо временем (+ до 4 строк «Кому:/Тема:/От:/-----» над ней,
                так пишет Яндекс). Одной даты, одного времени или одного
                адреса мало: «Прошу рассчитать по КМД от 12.09.2026:» перед
                отступом — это сама заявка, а не цитата (разбор 30.09.2026).

ПРИ СОМНЕНИИ — НЕ СВОРАЧИВАТЬ:
  - тема письма начинается с «Fwd:/Fw:» или перед цитатой (или в её начале)
    стоит признак пересылки: пересланное письмо — это и есть содержание;
  - вне цитаты нет видимого текста (письмо — сплошная цитата);
  - после цитаты видимый текст, а за ним снова цитата — ответы между
    цитатами. Подпись или ответ ПОСЛЕ единственной цитаты свёртке не мешают;
  - голый blockquote без шапки — это отступ (Word, Gmail), не цитата;
  - родитель цитаты — не блочный контейнер (p, span, a, table, tr…):
    <details> там недопустим, браузер переставил бы разметку по-своему;
  - письмо больше 1 МБ, ошибка разбора, уже свёрнуто (повтор ничего не
    меняет) или после свёртки видимый текст не совпал с исходным (разборщик
    потерял часть письма — например, упёрся в предел вложенности).
«Отправлено из мобильной Почты Mail.ru» — подпись, не цитата.
Метки Odoo data-o-mail-quote не используем вовсе: санитайзер ставит их и на
подписи с телефонами, и на любой blockquote.

БАЙТ В БАЙТ. Если сворачивать нечего, возвращается исходная строка без
изменений. Пересборка через lxml меняет разметку письма только при свёртке —
поэтому после свёртки окно письма глушит загрузку из сети ещё раз
(pmk_mail_ui/models/mail_client_message.py, Г13).

ЧИСТАЯ ФУНКЦИЯ, БЕЗ ODOO — правила проверяются голым питоном:

    python3 experiments/odoo/addons/pmk_mail_ui/tests/test_quote_rules.py
"""
import html
import re

from lxml import etree
from lxml import html as lxml_html

FOLD_CLASS = "pmk-quote"
SUMMARY_TEXT = "···"  # «···»
SUMMARY_TITLE = "Показать или скрыть цитату"

# Больше — не трогаем: разбор и повторное глушение Г13 на каждое открытие.
MAX_CHARS = 1024 * 1024

# Дешёвый отсев: без этих слов в письме кандидатов не бывает.
_HINTS = re.compile(
    r"blockquote|mail-quote-collapse|gmail_quote|divRplyFwdMsg|border-top"
    r"|Original Message|Исходное (?:сообщение|письмо)", re.IGNORECASE)

_FWD_SUBJECT = re.compile(r"^\s*(?:fwd?|fw|пересл)\s*(?:\[\d+\]|\(\d+\))?\s*:", re.IGNORECASE)
_FWD_TEXT = re.compile(
    r"Пересылаемое сообщение|Пересланное сообщение|Forwarded message"
    r"|Begin forwarded message|Начало переадресованного сообщения"
    r"|Переадресованное сообщение|-{2,}\s*Переслано", re.IGNORECASE)
# Строки шапки цитаты.
_HDR_LINE = re.compile(
    r"^\s*(?:From|От кого|От|Sent|Отправлено|To|Кому|Cc|Копия|Subject|Тема|Date|Дата)\s*:",
    re.IGNORECASE)
_SEP_LINE = re.compile(r"^\s*[-_=]{5,}\s*$")
_OUTLOOK_BORDER = re.compile(r"border-top\s*:\s*solid\s+#(?:e1e1e1|b5c4df)", re.IGNORECASE)
_OUTLOOK_FROM = re.compile(r"^\s*(?:From|От кого|От)\s*:", re.IGNORECASE)
_OUTLOOK_MORE = re.compile(r"(?:Sent|Date|Отправлено|Дата|To|Кому)\s*:", re.IGNORECASE)
_SEPARATOR = re.compile(
    r"^\s*-{2,}\s*(?:Original Message|Исходное сообщение|Исходное письмо)\s*-{2,}",
    re.IGNORECASE)
_WROTE = re.compile(r"(?:wrote|пишет|писал\(а\)|написал\(а\)|написала?)\s*:\s*$", re.IGNORECASE)
_DATE = re.compile(r"\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}:\d{2}")
_EMAIL = re.compile(r"[^\s@<>()]+@[^\s@<>()]+\.[^\s@<>()]+")
_WORD = re.compile(r"\w")
_WORDS = re.compile(r"\w+")
_TAG = re.compile(r"<[^>]*>")
_SPACES = re.compile(r"\s+")

# Внутри чего <details> встаёт по правилам HTML. Прочее (p, span, a, font,
# table, tbody, tr…) — сомнение: браузер разобрал бы свёрнутое по-своему.
_BLOCK_PARENTS = frozenset({
    "div", "blockquote", "td", "th", "li", "dd", "section", "article", "main",
    "header", "footer", "aside", "center", "body", "form", "fieldset", "details",
})
# Пустые строки между шапкой и цитатой: <br>, <div><br></div>.
_BLANK_TAGS = frozenset({"br", "div", "p"})


def fold_quotes(html_text, subject=None):
    """Свернуть цитату письма. -> (html, правило | None).

    Ничего не свернули — возвращается исходная строка (тот же объект).
    subject — тема письма: «Fwd:/Fw:» в начале значит пересылку.
    """
    if not html_text or len(html_text) > MAX_CHARS:
        return html_text, None
    text = str(html_text)
    if FOLD_CLASS in text or not _HINTS.search(text):
        return html_text, None
    if subject and _FWD_SUBJECT.match(subject):
        return html_text, None
    try:
        return _fold(html_text, text)
    except (etree.LxmlError, ValueError, TypeError, RecursionError):
        return html_text, None


def _fold(original, text):
    root = lxml_html.fragment_fromstring(text, create_parent="div")
    found = _first_candidate(root)
    if not found:
        return original, None
    rule, first, last = found
    parent = first.getparent()
    if parent is None or (parent is not root and parent.tag not in _BLOCK_PARENTS):
        return original, None
    if last is None:
        last = first
        for node in first.itersiblings():
            last = node
    nodes = [first]
    node = first
    while node is not last:
        node = node.getnext()
        if node is None:  # не соседи — сомнение
            return original, None
        nodes.append(node)

    before, inside, after, interleaved = _split_text(root, first, last)
    if interleaved:
        return original, None
    if _FWD_TEXT.search(before[-600:]) or _FWD_TEXT.search(inside[:300]):
        return original, None
    if len(_WORD.findall(before + after)) < 2:
        return original, None

    details = etree.Element("details", {"class": FOLD_CLASS, "data-pmk-rule": rule})
    summary = etree.SubElement(details, "summary", {"title": SUMMARY_TITLE})
    summary.text = SUMMARY_TEXT
    tail, last.tail = last.tail, None
    parent.insert(parent.index(first), details)
    for node in nodes:
        details.append(node)  # вместе со своим хвостом — он внутри цитаты
    details.tail = tail

    out = etree.tostring(root, method="html", encoding="unicode")
    if not (out.startswith("<div>") and out.endswith("</div>")):
        return original, None
    out = out[len("<div>"):-len("</div>")]
    # Страховка от потерь: видимый текст (без «···») тот же, что в исходнике.
    if _words(_TAG.sub(" ", out).replace(SUMMARY_TEXT, " ")) != _words(_TAG.sub(" ", text)):
        return original, None
    return out, rule


def _words(markup_text):
    return _WORDS.findall(html.unescape(markup_text))


# ----------------------------------------------------------------------
# кандидаты
# ----------------------------------------------------------------------
def _first_candidate(root):
    for el in root.iter():
        if not isinstance(el.tag, str) or el is root:
            continue
        found = _candidate(el)
        if found:
            return found
    return None


def _candidate(el):
    """(правило, первый узел, последний узел | None = до конца родителя)."""
    tag = el.tag
    classes = (el.get("class") or "").split()
    if any(c.startswith("mail-quote-collapse") for c in classes):
        return "mailru", el, el
    if tag == "blockquote" and (el.get("id") or "").startswith("mail-app-auto-quote"):
        parent = el.getparent()
        if parent is not None and parent.get("id") == "composeWebView_previouse_content" \
                and _only_child(parent, el):
            return "mailru_app", parent, parent
        return "mailru_app", el, el
    if "gmail_quote" in classes or "gmail_quote_container" in classes:
        return "gmail", el, el
    if el.get("id") == "divRplyFwdMsg":
        prev = _prev_element(el)
        first = prev if prev is not None and prev.tag == "hr" and not _gap(prev) else el
        return "owa", first, None
    if tag == "blockquote" and (el.get("type") or "").lower() == "cite":
        start = _attribution_start(el, cite=True)
        return "cite", el if start is None else start, el
    if tag == "div" and _OUTLOOK_BORDER.search(el.get("style") or ""):
        head = _short_text(el, 600)
        if head and _OUTLOOK_FROM.match(head) and _OUTLOOK_MORE.search(head):
            return "outlook", _climb(el), None
    own = (el.text or "").strip()
    if own and _SEPARATOR.match(own):
        return "separator", _climb(el), None
    if tag == "br" and el.tail and _SEPARATOR.match(el.tail.strip()):
        return "separator", el, None
    if tag == "blockquote":
        start = _attribution_start(el, cite=False)
        if start is not None:
            return "header", start, el
    return None


def _attribution_start(quote, cite):
    """Начало шапки прямо перед цитатой или None, если шапки нет.

    Шапка голым текстом (хвост соседа) не свернуть — тогда цитата
    сворачивается одна, а шапка остаётся видна. Хвост после <br> —
    сворачиваем вместе с этим <br>.

    cite — blockquote type=cite: цитата и без шапки, шапка лишь уходит
    вместе с ней, поэтому годится и div.moz-cite-prefix, и строка с одной
    датой. Голый blockquote (cite=False) — чаще отступ, чем цитата: там
    шапка — только по строгому правилу (_is_attribution, strict).
    """
    strict = not cite
    node = quote  # левый край будущей свёртки
    for step in range(3):  # сама цитата и до двух пустых строк перед ней
        prev = _prev_element(node)
        between = (prev.tail if prev is not None else node.getparent().text) or ""
        if between.strip():
            # Шапка голым текстом: свернуть её нельзя, сворачиваем от node.
            line = between.strip().splitlines()[-1]
            return node if _is_attribution(line, strict) else None
        if prev is None:
            return None
        if step < 2 and _is_blank(prev):
            node = prev
            continue
        break
    else:
        return None
    head = _short_text(prev, 300)
    if not (head and ((cite and "moz-cite-prefix" in (prev.get("class") or ""))
                      or _is_attribution(head, strict))):
        return None
    start = prev
    # Над шапкой — до 4 строк «Кому:/Тема:/От:/-----» (Яндекс).
    for _ in range(4):
        above = _prev_element(start)
        if above is None or _gap(above):
            break
        line = _short_text(above, 300)
        if not line or not (_HDR_LINE.match(line) or _SEP_LINE.match(line)):
            break
        start = above
    return start


def _is_attribution(text, strict=False):
    """Строка-шапка цитаты: короткая, в конце «:».

    strict (перед голым blockquote) — «пишет / wrote / написал(а)» или адрес
    вместе с датой либо временем («23.07.2026, 03:56, "Владимир"
    <zakaz@…>:» — Яндекс). Одна дата, одно время или один адрес — это и
    строка самой заявки перед отступом («…по КМД от 12.09.2026:»,
    «Совещание завтра в 10:00, повестка:», «…присылайте на docs@…:»).
    """
    text = _SPACES.sub(" ", text).strip()
    if not text or len(text) >= 300 or not text.endswith(":"):
        return False
    if _WROTE.search(text):
        return True
    if strict:
        return bool(_EMAIL.search(text) and _DATE.search(text))
    return bool(_DATE.search(text) or _EMAIL.search(text))


def _is_blank(el):
    if el.tag not in _BLANK_TAGS:
        return False
    if el.tag == "br":
        return True
    if el.xpath("boolean(.//img|.//table)"):
        return False
    return not el.text_content().strip()


def _prev_element(el):
    """Предыдущий сосед-элемент (комментарии пропускаем)."""
    prev = el.getprevious()
    while prev is not None and not isinstance(prev.tag, str):
        prev = prev.getprevious()
    return prev


def _gap(prev):
    """Между prev и следующим за ним узлом стоит видимый текст."""
    return prev is not None and bool((prev.tail or "").strip())


def _only_child(parent, child):
    if (parent.text or "").strip() or (child.tail or "").strip():
        return False
    return all(node is child or not isinstance(node.tag, str) for node in parent)


def _climb(el):
    """Подняться через обёртки, у которых этот узел — единственное
    содержимое (Outlook заворачивает шапку в лишний <div>)."""
    while True:
        parent = el.getparent()
        if parent is None or parent.getparent() is None:
            return el
        if parent.tag not in _BLOCK_PARENTS and parent.tag not in ("p", "span", "font", "b", "strong"):
            return el
        if not _only_child(parent, el):
            return el
        el = parent


def _short_text(el, limit):
    """Видимый текст узла, если он короткий; иначе пусто (не шапка)."""
    total = 0
    parts = []
    for chunk in el.itertext():
        total += len(chunk)
        if total > limit * 4:
            return ""
        parts.append(chunk)
    text = _SPACES.sub(" ", "".join(parts)).strip()
    return text if len(text) <= limit else ""


# ----------------------------------------------------------------------
# текст вокруг кандидата
# ----------------------------------------------------------------------
def _is_quote_marker(el):
    if el.tag == "blockquote":
        return True
    classes = (el.get("class") or "").split()
    return any(c.startswith("mail-quote-collapse") or c.startswith("gmail_quote") for c in classes)


def _split_text(root, first, last):
    """Текст до кандидата, внутри, после — и «ответы между цитатами»: после
    кандидата видимый текст, а за ним снова цитата."""
    before, inside, after = [], [], []
    where = before
    seen_text = False
    interleaved = False
    for event, el in etree.iterwalk(root, events=("start", "end")):
        is_element = isinstance(el.tag, str)
        if event == "start":
            if el is first:
                where = inside
            if where is after and is_element and _is_quote_marker(el) and seen_text:
                interleaved = True
                break
            if is_element and el.text:
                where.append(el.text)
                if where is after and _WORD.search(el.text):
                    seen_text = True
        else:
            if el is last:
                where = after
            if el is not root and el.tail:
                where.append(el.tail)
                if where is after and _WORD.search(el.tail):
                    seen_text = True
    return "".join(before), "".join(inside), "".join(after), interleaved
