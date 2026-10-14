# -*- coding: utf-8 -*-
"""Короткое название организации (Антон 14.10.2026: «чтоб организации
записывались как ООО, а не общество с ограниченной ответственностью, а ИП —
как ИП Чулков В.В., без полного имени отчества»).

  ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ "ПРОЦЕСС" → ООО «ПРОЦЕСС»
  Индивидуальный предприниматель Чулков Владислав Витальевич → ИП Чулков В.В.
  ИП ЧУЛКОВ ВЛАДИСЛАВ ВИТАЛЬЕВИЧ → ИП Чулков В.В.

Полное наименование остаётся в поле «Полное наименование» (pmk_legal_name):
оно для договоров и печати.
"""

import re

# Порядок важен: длинные формы раньше «акционерного общества».
FORMS = (
    (r"общество\s+с\s+ограниченной\s+ответственностью", "ООО"),
    (r"публичное\s+акционерное\s+общество", "ПАО"),
    (r"непубличное\s+акционерное\s+общество", "АО"),
    (r"закрытое\s+акционерное\s+общество", "ЗАО"),
    (r"открытое\s+акционерное\s+общество", "ОАО"),
    (r"акционерное\s+общество", "АО"),
    (r"индивидуальный\s+предприниматель", "ИП"),
)
_WORD = r"[А-ЯЁа-яё]+(?:-[А-ЯЁа-яё]+)?"
_IP = re.compile(r"^ИП\s+(%s)\s+(%s)(?:\s+(%s))?$" % (_WORD, _WORD, _WORD))
_QUOTED = re.compile(r'^(ООО|ПАО|АО|ЗАО|ОАО)\s+"([^"]+)"$')


def _surname(word):
    # «ЧУЛКОВ» → «Чулков», «Римский-Корсаков» — как есть; инициалы «А.В.» —
    # как есть (иначе «А.в.»).
    if word.isupper() and word.replace("-", "").isalpha():
        return "-".join(part.capitalize() for part in word.split("-"))
    return word


def legal_form_and_rest(name):
    """('ИП', 'Чулков Владислав Витальевич') — форма сокращением и остальное;
    (None, имя) — формы в начале нет."""
    text = " ".join((name or "").split())
    for pattern, abbr in FORMS:
        match = re.match(pattern + r"(?=\s|\"|«|$)\s*", text, re.IGNORECASE)
        if match:
            return abbr, text[match.end():]
    match = re.match(r"^(ООО|ПАО|АО|ЗАО|ОАО|ИП)\s+", text)
    if match:
        return match.group(1), text[match.end():]
    return None, text


def short_name(name):
    """Короткое название; не организация — как было."""
    if not name:
        return name
    form, rest = legal_form_and_rest(name)
    if not form or not rest:
        return name
    text = "%s %s" % (form, rest)
    match = _QUOTED.match(text)
    if match:
        text = "%s «%s»" % (match.group(1), match.group(2))
    match = _IP.match(text)
    if match:
        surname, first, middle = match.groups()
        text = "ИП %s %s." % (_surname(surname), first[0].upper())
        if middle:
            text += "%s." % middle[0].upper()
    return text


def ip_full_print_name(full_name):
    """«ИП Фамилия Имя Отчество» для печати из полного наименования
    («Индивидуальный предприниматель …» или «ИП …»); None — не ИП."""
    form, rest = legal_form_and_rest(full_name)
    if form != "ИП" or len(rest.split()) < 2:
        return None
    return "ИП " + " ".join(_surname(w) for w in rest.split())
