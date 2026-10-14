# -*- coding: utf-8 -*-
"""Реквизиты и контакт из письма — правилами, без ИИ (14.10.2026, «Создать
контрагента» в карточке справа от письма).

Чистые функции, без Odoo: тесты гоняются голым питоном
(tests/test_requisites_rules.py).

- Текст вложения: PDF с текстовым слоем (pdfminer, иначе PyPDF2), Word .docx,
  Excel .xlsx, обычный текст. Скан и фото без текстового слоя текста не
  дают — такое вложение просто ничего не добавит (распознавания нет).
- Реквизиты рядом со своими словами: «ИНН», «КПП», «ОГРН», «БИК», «р/с»,
  «к/с». ИНН — только с верными контрольными цифрами.
- Контакт: имя — из «Имя <адрес>», если похоже на человека, иначе строка
  подписи вида «Фамилия Имя [Отчество]» или «Фамилия И.О.»; должность —
  короткая строка подписи со словом должности.
"""

import io
import re
import zipfile

# ----------------------------------------------------------------------
# текст вложения
# ----------------------------------------------------------------------
TEXT_TYPES = {
    "pdf": "pdf",
    "docx": "docx",
    "xlsx": "xlsx",
    "txt": "txt",
    "csv": "txt",
}
MAX_BYTES = 8 * 1024 * 1024


def file_kind(name, mimetype=""):
    """pdf / docx / xlsx / txt — или пусто (не читаем)."""
    ext = (name or "").rsplit(".", 1)[-1].lower() if "." in (name or "") else ""
    if ext in TEXT_TYPES:
        return TEXT_TYPES[ext]
    mimetype = (mimetype or "").lower()
    if mimetype == "application/pdf":
        return "pdf"
    if "wordprocessingml" in mimetype:
        return "docx"
    if "spreadsheetml" in mimetype:
        return "xlsx"
    if mimetype.startswith("text/plain"):
        return "txt"
    return ""


def _pdf_text(data):
    try:
        from pdfminer.high_level import extract_text
        return extract_text(io.BytesIO(data)) or ""
    except Exception:  # noqa: BLE001 — битый или зашифрованный PDF
        pass
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:10])
    except Exception:  # noqa: BLE001
        return ""


def _xml_text(xml):
    xml = re.sub(r"</w:p>|</w:tr>|<w:br/>|</row>|</si>", "\n", xml)
    xml = re.sub(r"</w:tc>|</c>", " \t ", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    return (text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
            .replace("&apos;", "'").replace("&amp;", "&"))


def _docx_text(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return _xml_text(archive.read("word/document.xml").decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return ""


def _xlsx_text(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            parts = [name for name in archive.namelist()
                     if name == "xl/sharedStrings.xml"
                     or (name.startswith("xl/worksheets/") and name.endswith(".xml"))]
            return "\n".join(_xml_text(archive.read(name).decode("utf-8", "replace"))
                             for name in parts)
    except Exception:  # noqa: BLE001
        return ""


def attachment_text(name, mimetype, data):
    kind = file_kind(name, mimetype)
    if not kind or not data or len(data) > MAX_BYTES:
        return ""
    if kind == "pdf":
        return _pdf_text(data)
    if kind == "docx":
        return _docx_text(data)
    if kind == "xlsx":
        return _xlsx_text(data)
    for encoding in ("utf-8", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return ""


# ----------------------------------------------------------------------
# реквизиты
# ----------------------------------------------------------------------
_W10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_W11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_W12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _check(digits, weights):
    return sum(d * w for d, w in zip(digits, weights)) % 11 % 10


def inn_valid(value):
    text = (value or "").strip()
    if not text.isdigit() or len(text) not in (10, 12) or not text.strip("0"):
        return False
    digits = [int(char) for char in text]
    if len(digits) == 10:
        return _check(digits, _W10) == digits[9]
    return _check(digits, _W11) == digits[10] and _check(digits, _W12) == digits[11]


_SEP = r"\s*(?:[:№#]|номер)?\s*"
_INN = re.compile(r"ИНН(?:\s*/\s*КПП)?" + _SEP + r"(\d{10}|\d{12})(?!\d)", re.I)
_KPP = re.compile(r"(?<!/)КПП" + _SEP + r"(\d{9})(?!\d)", re.I)
_INN_KPP = re.compile(r"ИНН\s*/\s*КПП" + _SEP + r"\d{10}\s*/\s*(\d{9})(?!\d)", re.I)
_OGRN = re.compile(r"ОГРН(?:ИП)?" + _SEP + r"(\d{13}|\d{15})(?!\d)", re.I)
_BIK = re.compile(r"БИК" + _SEP + r"(\d{9})(?!\d)", re.I)
_ACCOUNT = re.compile(
    r"(?:р\s*/\s*сч?|р\.\s*сч?\.?|расч[её]тный\s+сч[её]т)\.?" + _SEP + r"(\d{20})(?!\d)", re.I)
_CORR = re.compile(
    r"(?:к\s*/\s*сч?|к\.\s*сч?\.?|корр?\.?\s*сч[её]т|корреспондентский\s+сч[её]т)\.?"
    + _SEP + r"(\d{20})(?!\d)", re.I)


def _first(pattern, text):
    found = pattern.search(text or "")
    return found.group(1) if found else ""


def requisites(text, own_inns=()):
    """{"inns": [...], "kpp", "ogrn", "bik", "account", "corr"} — найденное в
    тексте; свои ИНН (организации завода) не в счёт."""
    text = re.sub(r"[   ]", " ", text or "")
    inns = []
    for inn in _INN.findall(text):
        if inn_valid(inn) and inn not in inns and inn not in own_inns:
            inns.append(inn)
    return {
        "inns": inns,
        "kpp": _first(_KPP, text) or _first(_INN_KPP, text),
        "ogrn": _first(_OGRN, text),
        "bik": _first(_BIK, text),
        "account": _first(_ACCOUNT, text),
        "corr": _first(_CORR, text),
    }


# ----------------------------------------------------------------------
# контакт
# ----------------------------------------------------------------------
_LEGAL = re.compile(
    r"\b(ООО|ОАО|ЗАО|ПАО|АО|ИП|НАО|АНО|ФГУП|МУП|ГУП|ТД|ГК|ПК|LLC|LTD)\b|[«»\"]", re.I)
_COMPANY_WORDS = re.compile(
    r"(?i)компани|завод|групп|отдел|служб|снабжени|бухгалтер|info|sales|zakaz|office|"
    r"торгов|магазин|склад|производств|строй|сервис|центр")
_PERSON_FULL = re.compile(r"^[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?(?:\s+[А-ЯЁ][а-яё]+){1,2}$")
_PERSON_SHORT = re.compile(r"^[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ]\.\s?[А-ЯЁ]\.?$")
_POSITION = re.compile(
    r"(?i)менеджер|специалист|директор|инженер|снабжен|закуп|бухгалтер|руководител|"
    r"начальник|главн|заместител|логист|прораб|технолог|конструктор|мастер|экономист|"
    r"юрист|секретар|ассистент|помощник|представител|координатор|сметчик")
_NOT_POSITION = re.compile(r"(?i)тел|моб|e-?mail|почт|@|www|http|сайт|адрес|г\.|ул\.|\d{3}")


def looks_like_person(name):
    name = (name or "").strip()
    if not name or "@" in name or _LEGAL.search(name) or _COMPANY_WORDS.search(name):
        return False
    return bool(_PERSON_FULL.match(name) or _PERSON_SHORT.match(name))


def person_from_lines(lines):
    """Первая строка подписи, похожая на ФИО."""
    for line in lines or ():
        line = re.sub(r"\s+", " ", (line or "").strip(" ,.;"))
        if len(line) <= 60 and looks_like_person(line):
            return line
    return ""


def position_from_lines(lines):
    """Самая короткая строка подписи со словом должности."""
    best = ""
    for line in lines or ():
        line = re.sub(r"\s+", " ", (line or "").strip(" ,.;"))
        if not line or len(line) > 60 or not _POSITION.search(line) or _NOT_POSITION.search(line):
            continue
        if re.match(r"(?i)^(с уважением|спасибо|добрый|здравствуйте)", line):
            continue
        if not best or len(line) < len(best):
            best = line
    return best[:1].upper() + best[1:] if best else ""


def company_from_sender(name):
    """«ООО Завод МашМетиз» в имени отправителя — название компании."""
    name = (name or "").strip().strip('"')
    return name if name and _LEGAL.search(name) else ""


# ----------------------------------------------------------------------
# название организации и телефон контакта (окно «Новый контрагент», 14.10)
# ----------------------------------------------------------------------
_LEGAL_NAME = re.compile(
    r"\b(ООО|АО|ПАО|ЗАО|ОАО|НАО|ИП)\s*[«\"“]\s*([^»\"”\n]{2,60}?)\s*[»\"”]")
_SPLIT = re.compile(r"\s*(?:\||•|·|—|–|,)\s*")


def legal_names_in(text, own=()):
    """«ООО «Альфамобиль»» и т. п. из текста — без повторов и без своих."""
    own = {name.lower() for name in own or ()}
    found = []
    for form, body in _LEGAL_NAME.findall(text or ""):
        name = "%s «%s»" % (form.upper(), re.sub(r"\s+", " ", body).strip())
        if name.lower() not in own and name not in found and body.lower() not in own:
            found.append(name)
    return found


def company_from_lines(lines, domain=""):
    """Название из подписи: строка с правовой формой или строка с доменом
    адреса («Альфа-Лизинг | alfaleasing.ru» → «Альфа-Лизинг»)."""
    domain = (domain or "").lower()
    stem = domain.split(".")[0] if domain else ""
    for line in reversed(list(lines or ())[-15:]):
        named = legal_names_in(line)
        if named:
            return named[0]
    for line in reversed(list(lines or ())[-15:]):
        low = (line or "").lower()
        if not domain or (domain not in low and not (stem and len(stem) > 3 and stem in low.replace("-", ""))):
            continue
        for piece in _SPLIT.split(line):
            piece = piece.strip(" .")
            if (piece and domain not in piece.lower() and "@" not in piece and "http" not in piece.lower()
                    and re.search(r"[A-Za-zА-Яа-яЁё]{3}", piece) and len(piece) <= 60
                    and not _NOT_POSITION.search(piece)):
                return piece
    return ""


_CONTACT_PHONE = re.compile(
    r"(?<![\d+])(?:\+\s*7|8)[\s\-.]*\(?\s*\d{3,5}\s*\)?[\s\-.]*\d{1,3}[\s\-.]*\d{2}[\s\-.]*\d{2}(?!\d)"
    r"(?:\s*,?\s*(?:доб\.?|добавочный|ext\.?)\s*\d{1,6})?", re.I)


def contact_phone(lines, own_digits=()):
    """Телефон из подписи вместе с добавочным; 8-800 тоже (у банков и
    лизинга другого часто нет). Мобильный — главнее."""
    first = ""
    for line in list(lines or ())[-15:]:
        if re.search(r"(?i)\b(ИНН|КПП|ОГРН|БИК)\b|р\s*/\s*с", line or ""):
            continue
        for match in _CONTACT_PHONE.finditer(line or ""):
            found = re.sub(r"\s+", " ", match.group(0)).strip()
            digits = re.sub(r"\D", "", found.split("доб")[0])[-10:]
            if digits in own_digits:
                continue
            if digits.startswith("9"):
                return found
            first = first or found
    return first
