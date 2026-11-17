"""Разбор сырого письма: шапка, текст (plain, иначе HTML → текст), вложения."""
import email
import re
from email import policy
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

try:
    import html2text as _h2t
except ImportError:  # pragma: no cover
    _h2t = None

PARSED_VERSION = 2


class _Text(HTMLParser):
    """Запасной HTML → текст, если нет html2text. blockquote → '> '."""
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.quote = [], 0, 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head"):
            self.skip += 1
        elif tag == "blockquote":
            self.quote += 1
            self.out.append("\n")
        elif tag in self.BLOCK:
            self.out.append("\n")
        elif tag == "td":
            self.out.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag == "blockquote":
            self.quote = max(0, self.quote - 1)
            self.out.append("\n")
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self.skip:
            return
        if self.quote:
            data = "\n".join(("> " * self.quote) + l if l.strip() else l for l in data.split("\n"))
        self.out.append(data)


HTML_MAX = 1500000   # огромные HTML-рассылки: дальше 1,5 МБ текста нет, только вёрстка


def html_to_text(html):
    html = html[:HTML_MAX]
    if _h2t:
        h = _h2t.HTML2Text()
        h.body_width = 0
        h.ignore_images = True
        h.ignore_emphasis = True
        h.ignore_links = False
        h.inline_links = False
        h.protect_links = False
        h.unicode_snob = True
        text = h.handle(html)
        # html2text даёт ссылки сносками [1] … — сноски на картинки/трекинг выкидываем
        text = re.sub(r"^\s*\[\d+\]: \S+.*$", "", text, flags=re.M)
        return text
    p = _Text()
    p.feed(html)
    return "".join(p.out)


def _addrs(value):
    pairs = getaddresses([str(value)]) if value else []
    return [(n.strip(), a.strip().lower()) for n, a in pairs if a and "@" in a]


def _payload_text(part):
    try:
        return part.get_content()
    except Exception:
        raw = part.get_payload(decode=True) or b""
        cs = part.get_content_charset() or "utf-8"
        for enc in (cs, "cp1251", "koi8-r", "utf-8"):
            try:
                return raw.decode(enc)
            except (LookupError, UnicodeDecodeError):
                continue
        return raw.decode("utf-8", "replace")


def _is_attachment(part):
    if part.is_multipart():
        return False
    disp = (part.get("Content-Disposition") or "").lower()
    fname = part.get_filename()
    ctype = part.get_content_type()
    if "attachment" in disp or (fname and ctype not in ("text/plain", "text/html")):
        # картинки подписей/логотипов внутри HTML (inline с Content-ID, мелкие) — не вложения
        if ctype.startswith("image/") and part.get("Content-ID") and "attachment" not in disp:
            return False
        return True
    return ctype not in ("text/plain", "text/html") and not ctype.startswith("multipart/") \
        and not ctype.startswith("image/") and ctype != "message/delivery-status"


def parse(raw, own, tz):
    msg = email.message_from_bytes(raw, policy=policy.default)
    zone = ZoneInfo(tz) if ZoneInfo else None
    try:
        dt = parsedate_to_datetime(str(msg["Date"]))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=zone)
        dt = dt.astimezone(zone) if zone else dt
        date = dt.isoformat(timespec="minutes")
    except Exception:
        date = ""

    frm = _addrs(msg["From"])
    to = _addrs(msg["To"])
    cc = _addrs(msg["Cc"])
    from_name, from_addr = frm[0] if frm else ("", "")
    out = from_addr in own
    if out:
        others = [a for _, a in to + cc if a not in own]
        counterpart = others[0] if others else (to[0][1] if to else "")
    else:
        counterpart = from_addr

    plain, html, atts = None, None, []
    for part in msg.walk():
        if part.is_multipart():
            continue
        if _is_attachment(part):
            atts.append(part)
            continue
        ctype = part.get_content_type()
        if ctype == "text/plain" and plain is None:
            plain = _payload_text(part)
        elif ctype == "text/html" and html is None:
            html = _payload_text(part)
    body = plain if plain and plain.strip() else (html_to_text(html) if html else "")
    # mail.ru иногда кладёт в text/plain тот же HTML
    if body and re.match(r"\s*<(!doctype|html|div|p|table)\b", body, re.I):
        body = html_to_text(body)

    refs = " ".join(re.findall(r"<([^>]+)>", str(msg["References"] or ""))).lower()
    irt = re.findall(r"<([^>]+)>", str(msg["In-Reply-To"] or ""))
    return {
        "message_id": str(msg["Message-ID"] or "").strip(),
        "in_reply_to": irt[0].lower() if irt else "",
        "refs": refs,
        "date": date,
        "from_addr": from_addr, "from_name": from_name,
        "to_addrs": ", ".join(a for _, a in to), "cc_addrs": ", ".join(a for _, a in cc),
        "subject": str(msg["Subject"] or "").strip(),
        "direction": "out" if out else "in",
        "counterpart": counterpart,
        "body": body,
        "attachments": atts,
        "truncated": bool(msg["X-Mail-Index-Truncated"]),
    }
