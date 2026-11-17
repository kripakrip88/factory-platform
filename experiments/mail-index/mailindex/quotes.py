"""Разделение текста письма: новое / цитата / подпись.

Цитату режем только как ДУБЛЬ: цитируемое письмо у нас есть отдельно (входящие/отправленные), цепочка
собирается по Message-ID. Поэтому здесь цитата не выбрасывается, а откладывается в поле quote — сборщик
цепочки сам решит, показывать ли её (если оригинала в архиве нет — показывает).
Виды:
  quote   — обычная цитата под ответом;
  inline  — ответ вписан внутрь цитаты по пунктам → весь текст остаётся новым, ничего не режем;
  forward — пересланное письмо → его содержимое больше нигде нет, тоже не режем.
"""
import re

_DAYS = r"(понедельник|вторник|среда|четверг|пятница|суббота|воскресенье|пн|вт|ср|чт|пт|сб|вс|mon|tue|wed|thu|fri|sat|sun)[a-z]*"

QUOTE_HEADERS = [
    # mail.ru: «Понедельник, 17 ноября 2026, 10:14 +10:00 от Иван <ivan@x.ru>:»
    re.compile(r"^\s*" + _DAYS + r",\s+\d{1,2}\s+\S+\s+\d{4},?\s+\d{1,2}:\d{2}.*\bот\b.*:\s*$", re.I),
    # Gmail ru: «пн, 17 нояб. 2026 г. в 10:14, Иван <ivan@x.ru>:»
    re.compile(r"^\s*" + _DAYS + r",?\s+\d{1,2}\s+\S+\s+\d{4}\s*г\.?\s*в\s+\d{1,2}:\d{2}.*:\s*$", re.I),
    # «17.11.2026, 10:14, "Иван" <ivan@x.ru>:» / «17.11.2026 10:14, Иван пишет:»
    re.compile(r"^\s*\d{1,2}[./]\d{1,2}[./]\d{2,4},?\s+(в\s+)?\d{1,2}:\d{2}.*(<[^>\s]+@[^>\s]+>|пишет|написал|wrote).*:\s*$", re.I),
    # Thunderbird/iOS: «17.11.2026 10:14, Иван пишет:», «Иван написал(а):», «On Mon, ... wrote:»
    re.compile(r"^.{0,250}\b(пишет|написал\(а\)|написала?|wrote)\s*:\s*$", re.I),
    re.compile(r"^\s*-{2,}\s*(original message|исходное сообщение)\s*-{2,}\s*$", re.I),
    # Яндекс: «02:55, 17 ноября 2026 г., "Владимир" <pmkpark@mail.ru>:»
    re.compile(r"^\s*\d{1,2}:\d{2},\s+\d{1,2}\s+\S+\s+\d{4}\s*г\.?,?\s+.*:\s*$", re.I),
]
OUTLOOK_FROM = re.compile(r"^\s*[*_]{0,2}(от кого|от|from|отправитель)\s*:[*_]{0,2}\s*\S", re.I)
OUTLOOK_NEXT = re.compile(r"^\s*[*_]{0,2}(отправлено|sent|дата|date|кому|to)\s*:", re.I)
# строки-шапки перед заголовком цитаты (Яндекс кладёт «Кому:/Тема:» над «время, дата, кто:»)
META = re.compile(r"^\s*([*_]{0,2}(кому|тема|копия|от кого|от|дата|отправлено|to|subject|cc|date|sent|from)"
                  r"\s*:.*|-{5,}|_{5,})\s*$", re.I)
FORWARD = re.compile(
    r"(-{2,}\s*(пересылаемое сообщение|пересланное сообщение|forwarded message|перенаправленное сообщение|"
    r"переадресованное сообщение)\s*-{0,})|^\s*(начало переадресованного сообщения|begin forwarded message)\s*:",
    re.I)
SIG_DASH = re.compile(r"^\\?--\s*$")      # html2text экранирует «--» как «\--»
SIG_GREETING = re.compile(
    r"^\s*(с уважением|с наилучшими пожеланиями|всего доброго|best regards|kind regards|regards)\b[,.!]?",
    re.I)
MOBILE = re.compile(
    r"^\s*(отправлено (из|с) .{0,60}|sent from my .{0,40}|получено с помощью .{0,60}|"
    r"отправлено из мобильной почты mail\.ru|mail\.ru для (android|ios)|--\s*отправлено из .{0,60})\s*$", re.I)


def _is_header(lines, i):
    line = lines[i]
    nxt = lines[i + 1] if i + 1 < len(lines) else ""
    for k, rx in enumerate(QUOTE_HEADERS):
        if rx.match(line):
            return True
        # заголовки с датой Gmail/mail.ru переносят адрес на следующую строку
        if k < 3 and nxt and rx.match(line + " " + nxt.strip()):
            return True
    if OUTLOOK_FROM.match(line.lstrip("> ")):
        window = [l.lstrip("> ") for l in lines[i + 1:i + 6]]
        if sum(1 for l in window if OUTLOOK_NEXT.match(l)) >= 1:
            return True
    return False


def _inline(lines, start):
    """После начала цитаты есть свой текст между блоками '>'? — значит отвечали внутри цитаты."""
    blocks, prev = [], None
    for l in lines[start:]:
        if not l.strip():
            continue
        q = l.lstrip().startswith(">")
        if q != prev:
            blocks.append(q)
            prev = q
    # quoted, own, quoted (минимум) — признак ответа по пунктам
    for k in range(len(blocks) - 2):
        if blocks[k] and not blocks[k + 1] and blocks[k + 2]:
            return True
    return False


def _squeeze(text):
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split(text):
    """→ dict(new, quote, kind, signature)."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    lines = [l for l in text.split("\n") if not MOBILE.match(l)]
    res = {"new": "", "quote": "", "kind": "", "signature": ""}

    # 1. пересылка — ничего не режем, только помечаем
    for i, l in enumerate(lines):
        if FORWARD.search(l):
            own = lines[:i]
            res.update(kind="forward")
            own_text, sig = _cut_signature(own)
            res["new"] = _squeeze("\n".join(own_text + [""] + lines[i:]))
            res["signature"] = sig
            return res

    # 2. начало цитаты: заголовок «… пишет:» или первая строка с '>'
    start = None
    for i, l in enumerate(lines):
        if _is_header(lines, i):
            start = i
            break
        if l.lstrip().startswith(">") and any(x.strip() for x in lines[:i]):
            start = i
            break
    if start is None:
        own, sig = _cut_signature(lines)
        res.update(new=_squeeze("\n".join(own)), signature=sig)
        return res

    if _inline(lines, start):
        res.update(new=_squeeze("\n".join(lines)), kind="inline")
        return res
    # подтянуть в цитату шапку над заголовком («Кому: …», «Тема: …», «-----») и пустые строки
    while start > 0 and (META.match(lines[start - 1]) or not lines[start - 1].strip()):
        start -= 1

    own, sig = _cut_signature(lines[:start])
    res.update(new=_squeeze("\n".join(own)), quote=_squeeze("\n".join(lines[start:])),
               kind="quote", signature=sig)
    return res


def _cut_signature(lines):
    """Подпись: после '-- ' целиком; от «С уважением» до конца (имя, должность, телефоны, реквизиты, баннеры) —
    если это не больше 25 строк. Кто писал, видно в заголовке письма; подпись хранится в поле signature."""
    for i, l in enumerate(lines):
        if SIG_DASH.match(l):
            return lines[:i], _squeeze("\n".join(lines[i + 1:]))
    for i in range(len(lines) - 1, -1, -1):
        if SIG_GREETING.match(lines[i].strip("*_ ")):
            tail = lines[i:]
            if len([l for l in tail if l.strip()]) > 25:
                break
            return lines[:i], _squeeze("\n".join(tail))
    return lines, ""


def first_level(quote):
    """Из цитаты — только ближайшее письмо (первый уровень '>'), без подписи; глубже — более старая переписка."""
    out, deeper = [], 0
    for l in (quote or "").split("\n"):
        s2 = re.sub(r"^\s*>\s?", "", l)
        if s2.lstrip().startswith(">") and s2.strip() not in (">", ">:"):
            deeper += 1
            continue
        out.append(s2 if s2.strip() not in (">", ">:") else "")
    # шапка цитаты сверху («Пятница, …, от X <a@b», «От кого:», «Кому:», «Дата:») — не текст письма
    while out and (not out[0].strip() or META.match(out[0]) or _is_header(out, 0)
                   or ("@" in out[0] and re.search(r"\d{1,2}:\d{2}", out[0]))):
        out.pop(0)
    text = split("\n".join(out))
    body = text["new"] if text["kind"] != "inline" else "\n".join(out)
    return _squeeze(body), deeper > 0
