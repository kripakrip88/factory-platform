# -*- coding: utf-8 -*-
"""Клиент из письма: не плодить дубли (шаг З-14, 10.10.2026) — правила.

ЗАЧЕМ. Прогон Кытмановой 09.10: письмо пришло с 6574@truboproduct.ru, а
клиент «ООО ПО «Трубное решение», филиал Хабаровск» (контрагент 18) в базе
уже был — с сайтом hab.truboproduct.ru и почтой для прайсов
hbr@truboproduct.ru. Почтовый модуль сравнивает только поле «Эл. почта»
целиком, поэтому лид вышел без клиента, мастер «В сделку» предложил
«Создать нового клиента», а рядом уже лежал дубль «ТРУБНОЕ РЕШЕНИЕ» (159)
из переноса таблицы заказов 08.10: перенос сравнивал названия буквально.

Здесь — три ключа, по которым две карточки скорее всего одна компания:
  • домен адреса — truboproduct.ru у почты, сайта и почты для прайсов,
    кроме общих почтовых служб (mail.ru, gmail.com…): на них сидят тысячи
    чужих людей;
  • ИНН — только с верными контрольными цифрами (опечатка не связывает);
  • ключ названия — без ООО/АО/ИП/ПО, кавычек, регистра, ё/е и хвоста
    «, филиал Хабаровск»: «ТРУБНОЕ РЕШЕНИЕ» и «ООО ПО «Трубное решение»,
    филиал Хабаровск» дают одно и то же «трубное решение».

ЧИСТЫЕ ФУНКЦИИ БЕЗ ODOO: их гоняет голый питон до всякой выкладки

    python3 experiments/odoo/addons/pmk_partner/tests/test_partner_keys_rules.py

Модель (models/partner_match.py) зовёт их сама.
"""
import re

# Домены второго уровня, где «зарегистрированное имя» — три метки:
# shop.com.ru, а не com.ru. Список короткий намеренно — только то, что
# встречается у российских компаний; прочее режется по двум меткам.
SECOND_LEVEL_SUFFIXES = frozenset({
    "com.ru", "net.ru", "org.ru", "pp.ru", "msk.ru", "spb.ru", "khv.ru",
    "msk.su", "spb.su", "co.uk", "com.cn", "com.kz", "org.kz",
})

# Общие почтовые службы: адрес на них ничего не говорит о компании.
# redcom.ru — хабаровский провайдер почты (dmk@mail.redcom.ru): без него все
# отправители с redcom.ru привязались бы к «ДМК-Снаб» (разбор боевой базы
# 10.10.2026). Дописать свои — системный параметр
# pmk_partner.public_mail_domains (через запятую), без выкладки.
PUBLIC_MAIL_DOMAINS = frozenset({
    "mail.ru", "bk.ru", "list.ru", "inbox.ru", "internet.ru", "xmail.ru",
    "gmail.com", "googlemail.com",
    "yandex.ru", "yandex.com", "yandex.by", "yandex.kz", "yandex.ua", "ya.ru",
    "narod.ru",
    "rambler.ru", "ro.ru", "autorambler.ru", "myrambler.ru", "lenta.ru",
    "icloud.com", "me.com", "mac.com",
    "outlook.com", "hotmail.com", "live.com", "live.ru", "msn.com",
    "yahoo.com", "mail.com", "aol.com", "gmx.com", "gmx.de",
    "vk.com", "proton.me", "protonmail.com", "tutanota.com",
    "ngs.ru", "e1.ru", "redcom.ru", "qip.ru", "pochta.ru",
})

_ADDRESS = re.compile(r"[\w.+'-]+@([\w-]+(?:\.[\w-]+)+)")
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://")
_HOST_OK = re.compile(r"^[\w-]+(?:\.[\w-]+)+$")


def registrable_domain(host):
    """«mail.redcom.ru» → «redcom.ru», «hab.truboproduct.ru» →
    «truboproduct.ru», «shop.com.ru» → «shop.com.ru». Пусто — не домен."""
    host = (host or "").strip().lower().strip(".")
    labels = [label for label in host.split(".") if label]
    if len(labels) < 2:
        return ""
    tail = ".".join(labels[-2:])
    if tail in SECOND_LEVEL_SUFFIXES:
        return ".".join(labels[-3:]) if len(labels) >= 3 else ""
    return tail


def email_domains(text):
    """Все домены адресов в строке (в поле бывает «a@x.ru; b@y.ru»)."""
    found = {registrable_domain(host) for host in _ADDRESS.findall((text or "").lower())}
    found.discard("")
    return found


def email_domain(email):
    """Домен первого адреса строки или пусто."""
    match = _ADDRESS.search((email or "").lower())
    return registrable_domain(match.group(1)) if match else ""


def site_domain(url):
    """Сайт → домен: без схемы, www, порта и пути. «https://hab.truboproduct.ru/»
    → «truboproduct.ru». В поле бывает несколько сайтов — берём первый."""
    text = (url or "").strip().lower()
    for token in re.split(r"[\s,;]+", text):
        if not token:
            continue
        host = _SCHEME.sub("", token)
        host = re.split(r"[/?#]", host, maxsplit=1)[0]
        host = host.rsplit("@", 1)[-1].split(":", 1)[0].strip(".")
        if host.startswith("www."):
            host = host[4:]
        if _HOST_OK.match(host):
            return registrable_domain(host)
        return ""
    return ""


def public_domains(extra=""):
    """Общие почтовые домены: встроенный список и дописанные через запятую."""
    added = {item.strip().lower() for item in re.split(r"[\s,;]+", extra or "") if item.strip()}
    return PUBLIC_MAIL_DOMAINS | added


# ----------------------------------------------------------------------
# ИНН
# ----------------------------------------------------------------------
_W10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_W11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_W12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _check(digits, weights):
    return sum(d * w for d, w in zip(digits, weights)) % 11 % 10


def inn_valid(value):
    """ИНН из 10 (организация) или 12 (ИП, физлицо) цифр с верными
    контрольными разрядами. Строка из одних нулей — не ИНН."""
    text = (value or "").strip()
    if not text.isdigit() or len(text) not in (10, 12) or not text.strip("0"):
        return False
    digits = [int(char) for char in text]
    if len(digits) == 10:
        return _check(digits, _W10) == digits[9]
    return _check(digits, _W11) == digits[10] and _check(digits, _W12) == digits[11]


def inn_of(vat):
    """ИНН из поля vat: «RU2721073821» и «2721 073 821» → «2721073821».
    Не 10 и не 12 цифр — пусто (иностранный номер или мусор)."""
    digits = re.sub(r"\D", "", vat or "")
    return digits if len(digits) in (10, 12) else ""


_INN_IN_TEXT = re.compile(
    r"ИНН(?:\s*/\s*КПП)?\s*[:№]?\s*(\d{10}|\d{12})(?!\d)", re.IGNORECASE)


def inns_in(text):
    """ИНН рядом со словом «ИНН» в тексте письма — только верные, по
    порядку, без повторов. «ИНН/КПП 2721073821/272101001» → 2721073821."""
    seen = []
    for inn in _INN_IN_TEXT.findall(text or ""):
        if inn_valid(inn) and inn not in seen:
            seen.append(inn)
    return seen


# ----------------------------------------------------------------------
# ключ названия
# ----------------------------------------------------------------------
_QUOTES = "«»\"'“”„‘’`"
_LEGAL_PHRASES = (
    "общество с ограниченной ответственностью",
    "непубличное акционерное общество",
    "публичное акционерное общество",
    "закрытое акционерное общество",
    "открытое акционерное общество",
    "акционерное общество",
    "индивидуальный предприниматель",
    "научно производственное объединение",
    "научно производственное предприятие",
    "производственное объединение",
    "производственная компания",
    "торговый дом",
    "группа компаний",
    "limited liability company",
)
_LEGAL_WORDS = frozenset({
    "ооо", "оао", "зао", "пао", "ао", "нао", "ип", "по", "нпо", "нпп", "нпк",
    "тд", "пк", "гк", "ук", "фгуп", "муп", "гуп", "ано", "ооо", "чп",
    "llc", "ltd", "inc", "gmbh",
})
_TAIL = re.compile(
    r"(?<=\S)\s+(?:филиал|представительство|обособленное\s+подразделение)\b.*$")
_PARENS = re.compile(r"\([^()]*\)")


def _cut_at_comma(text):
    """Всё до первой запятой вне кавычек: «…», филиал Хабаровск» → «…»»."""
    depth, straight = 0, False
    for index, char in enumerate(text):
        if char == "«":
            depth += 1
        elif char == "»":
            depth = max(depth - 1, 0)
        elif char == '"':
            straight = not straight
        elif char == "," and not depth and not straight:
            return text[:index]
    return text


def name_key(name):
    """Название → ключ для сравнения. «ООО ПО «Трубное решение», филиал
    Хабаровск» и «ТРУБНОЕ РЕШЕНИЕ» → «трубное решение». Пусто, если от
    названия ничего не осталось (одна форма собственности)."""
    text = (name or "").lower().replace("ё", "е")
    previous = None
    while previous != text:
        previous, text = text, _PARENS.sub(" ", text)
    text = _cut_at_comma(text)
    text = _TAIL.sub("", text)
    for char in _QUOTES:
        text = text.replace(char, " ")
    text = re.sub(r"[\W_]+", " ", text).strip()
    text = " %s " % text
    for phrase in _LEGAL_PHRASES:
        text = text.replace(" %s " % phrase, " ")
    words = [word for word in text.split() if word not in _LEGAL_WORDS]
    return " ".join(words)


# ----------------------------------------------------------------------
# группы возможных дублей
# ----------------------------------------------------------------------
def _reason(kind, value):
    if kind == "name":
        return "Название"
    if kind == "inn":
        return "ИНН %s" % value
    return "Домен %s" % value


def duplicate_groups(rows):
    """Группы похожих карточек.

    rows — [{"id", "name", "inn", "domains"}], где name — ключ названия,
    inn — ИНН или пусто, domains — множество корпоративных доменов (общие и
    свои уже убраны). Карточки с общим ключом попадают в одну группу; группы,
    сцепленные через третью карточку, склеиваются. Возвращает
    [(подпись, [(id, причина)])] — группы по порядку самой ранней карточки,
    внутри — по id. Подпись: общий ключ названия, иначе домен, иначе ИНН."""
    by_key = {}
    for row in rows:
        keys = set()
        if row.get("name"):
            keys.add(("name", row["name"]))
        if row.get("inn"):
            keys.add(("inn", row["inn"]))
        for domain in row.get("domains") or ():
            keys.add(("domain", domain))
        row["_keys"] = keys
        for key in keys:
            by_key.setdefault(key, []).append(row["id"])

    parent = {row["id"]: row["id"] for row in rows}

    def find(item):
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    shared = {key for key, ids in by_key.items() if len(set(ids)) > 1}
    for key in shared:
        ids = by_key[key]
        root = find(ids[0])
        for other in ids[1:]:
            other_root = find(other)
            if other_root != root:
                parent[other_root] = root

    members = {}
    for row in rows:
        if row["_keys"] & shared:
            members.setdefault(find(row["id"]), []).append(row)

    order = {"name": 0, "domain": 1, "inn": 2}
    groups = []
    for group in members.values():
        group.sort(key=lambda row: row["id"])
        counts = {}
        for row in group:
            for key in row["_keys"] & shared:
                counts[key] = counts.get(key, 0) + 1
        label_key = sorted(counts, key=lambda key: (order[key[0]], -counts[key], key[1]))[0]
        label = label_key[1] if label_key[0] != "inn" else "ИНН %s" % label_key[1]
        lines = []
        for row in group:
            keys = sorted(row["_keys"] & shared, key=lambda key: (order[key[0]], key[1]))
            lines.append((row["id"], ", ".join(_reason(*key) for key in keys)))
        groups.append((label, lines))
    groups.sort(key=lambda item: item[1][0][0])
    return groups
