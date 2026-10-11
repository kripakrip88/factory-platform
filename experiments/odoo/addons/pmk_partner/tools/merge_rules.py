# -*- coding: utf-8 -*-
"""Объединение клиентов: сравнить и не потерять (шаг З-17, 11.10.2026) — правила.

ЗАЧЕМ. Антон 11.10, окно «Объединить контакты» с группой «А ГРУПП»
(карточки 9, 20, 44): «по идее нужно сопоставлять какие-то живые данные —
ИНН, телефон и т. д., и либо объединять, например, телефоны, либо принимать
какой-то ИНН как истинно верный». Мастер ядра (base/wizard/
base_partner_merge.py, _update_values) оставляет у карточки назначения её
значения, пустые заполняет из исходных, а всё остальное теряет молча: у
«А ГРУПП» ушли бы два примечания из трёх и адрес для прайса info@ag.market.

Здесь — чистые правила без Odoo:
  • inn_key / inn_conflict — разные непустые ИНН среди выбранных карточек:
    это разные юрлица, объединять нельзя;
  • pick_destination — какая карточка останется: с ИНН → больше документов →
    активная → заведена раньше (меньший номер);
  • final_values — что окажется в карточке после ядра (для предпросмотра);
  • carry_plan — что у исходных карточек отличается от итога и потерялось
    бы: телефоны и почты (→ контактное лицо внутри компании), сайт, адрес для
    прайса, КПП, адреса и примечание (→ строкой в примечание и в ленту).

ЧИСТЫЕ ФУНКЦИИ БЕЗ ODOO: их гоняет голый питон до всякой выкладки

    python3 experiments/odoo/addons/pmk_partner/tests/test_merge_rules.py

Модель (models/partner_merge.py) зовёт их сама.
"""
import html
import re

from . import partner_keys

# Телефон и почта — в контактное лицо внутри компании: их набирают и им
# пишут, место им среди контактов, а не в примечании. У физлица и ИП
# контактных лиц нет — туда они идут строкой примечания.
CONTACT_FIELDS = (("phone", "Телефон"), ("email", "Эл. почта"))

# Остальное, что жалко потерять, — строкой в примечание. Поле берётся, только
# если оно есть у модели: pmk_purchase (адрес для прайса) и pmk_dadata
# (адреса) в зависимостях pmk_partner нет.
NOTE_FIELDS = (
    ("website", "Сайт"),
    ("pmk_price_email", "Адрес для запроса прайса"),
    ("kpp", "КПП"),
    ("pmk_legal_address", "Юридический адрес"),
    ("pmk_actual_address", "Фактический адрес"),
)
COMMENT_FIELD = "comment"

REASONS = ("inn", "docs", "active", "oldest")


# ----------------------------------------------------------------------
# ИНН
# ----------------------------------------------------------------------
def inn_key(vat):
    """Ключ ИНН для сравнения: «RU7717625418» и «7717 625 418» →
    «7717625418». Не 10 и не 12 цифр (иностранный номер) — сам текст без
    пробелов в верхнем регистре. Пусто — пусто."""
    text = (vat or "").strip()
    if not text:
        return ""
    return partner_keys.inn_of(text) or re.sub(r"\s+", "", text).upper()


def inn_conflict(rows):
    """Разные непустые ИНН среди карточек.

    rows — [{"id", "name", "vat"}]. Возвращает [(ИНН, [названия])] по
    порядку первого появления, когда разных непустых ИНН два и больше; иначе
    пустой список. Одинаковый ИНН или ИНН только у одной — не конфликт."""
    by_key = {}
    for row in rows:
        key = inn_key(row.get("vat"))
        if key:
            by_key.setdefault(key, []).append(row.get("name") or "")
    if len(by_key) < 2:
        return []
    return list(by_key.items())


# ----------------------------------------------------------------------
# какая карточка останется
# ----------------------------------------------------------------------
def _rank_key(row):
    return (bool(row.get("inn")), row.get("docs") or 0, bool(row.get("active")), -row["id"])


def pick_destination(rows):
    """Карточка назначения по умолчанию.

    rows — [{"id", "inn", "docs", "active"}]: inn — ключ ИНН или пусто,
    docs — сколько документов привязано (лиды и сделки, заказы, расчёты,
    закупки). Порядок: с ИНН → больше документов → активная → заведена
    раньше (меньший id). Возвращает {"dst", "reason", "runner"}: reason —
    первый признак, по которому оставшаяся отличается от второго места
    ('inn' | 'docs' | 'active' | 'oldest'), runner — id второго места. Пусто
    — dst=False; одна карточка — reason и runner пустые."""
    if not rows:
        return {"dst": False, "reason": "", "runner": False}
    ordered = sorted(rows, key=_rank_key, reverse=True)
    best = ordered[0]
    if len(ordered) == 1:
        return {"dst": best["id"], "reason": "", "runner": False}
    runner = ordered[1]
    reason = "oldest"
    for name, a, b in zip(REASONS, _rank_key(best), _rank_key(runner)):
        if a != b:
            reason = name
            break
    return {"dst": best["id"], "reason": reason, "runner": runner["id"]}


# ----------------------------------------------------------------------
# что окажется в карточке и что потерялось бы
# ----------------------------------------------------------------------
def final_values(dst, srcs, fields):
    """Как _update_values ядра: значение назначения, если оно не пустое,
    иначе последнее непустое из исходных (ядро обходит chain(src, dst), и
    побеждает последнее непустое)."""
    result = {}
    for field in fields:
        value = False
        for item in list(srcs) + [dst]:
            if item.get(field):
                value = item[field]
        result[field] = value
    return result


_TAGS = re.compile(r"<[^>]+>")
_BREAKS = re.compile(r"<\s*(?:br|/p|/div|/li|/h\d)\s*/?>", re.I)
_SPACES = re.compile(r"\s+")


def plain_text(value):
    """Примечание (html) → текст одной строкой без разметки."""
    text = _BREAKS.sub(" ", value or "")
    text = html.unescape(_TAGS.sub(" ", text))
    return _SPACES.sub(" ", text).strip()


def value_key(field, value):
    """Ключ сравнения значений одного поля: «8 (800) 302-07-07» и
    «+78003020707» — один телефон; почта и сайт — без регистра, сайт ещё и
    без схемы, www и косой в конце; примечание — текстом без разметки."""
    if not value:
        return ""
    if field == COMMENT_FIELD:
        return plain_text(value).lower()
    text = str(value).strip()
    if field == "phone":
        digits = re.sub(r"\D", "", text)
        if len(digits) >= 10:
            return digits[-10:]
        return digits or text.lower()
    if field in ("email", "pmk_price_email"):
        parts = [part for part in re.split(r"[\s,;]+", text.lower()) if part]
        return ",".join(sorted(parts))
    if field == "website":
        text = re.sub(r"^[a-z][a-z0-9+.-]*://", "", text.lower())
        if text.startswith("www."):
            text = text[4:]
        return text.rstrip("/")
    return _SPACES.sub(" ", text).lower()


def carry_plan(dst_final, srcs, children=(), fields=None, company=True):
    """Что у исходных карточек отличается от итога и без нас потерялось бы.

    dst_final — значения карточки назначения ПОСЛЕ ядра (словарь поле →
    значение); srcs — исходные карточки [{"id", "name", поля…}] в порядке
    ядра; children — контактные лица назначения (с переехавшими от исходных)
    [{"phone", "email"}]: телефон или почта, уже записанные у кого-то из них,
    не теряются. fields — поля примечания [(поле, подпись)], по умолчанию
    NOTE_FIELDS. company — назначение организация: телефон и почта идут в
    контактное лицо; иначе — строкой в примечание.

    Значение, уже перенесённое от предыдущей исходной карточки, второй раз не
    переносится. Возвращает [{"id", "name", "contact": {поле: значение},
    "note": [(подпись, значение)], "comment": html}] — только по карточкам,
    у которых что-то осталось."""
    note_fields = list(NOTE_FIELDS if fields is None else fields)
    contact_names = [name for name, _label in CONTACT_FIELDS]
    known = {}
    for name in contact_names + [name for name, _label in note_fields]:
        known[name] = {value_key(name, dst_final.get(name))} - {""}
    for child in children or ():
        for name in contact_names:
            key = value_key(name, child.get(name))
            if key:
                known[name].add(key)
    dst_comment = value_key(COMMENT_FIELD, dst_final.get(COMMENT_FIELD))
    seen_comments = []

    plan = []
    for src in srcs:
        contact, note, comment = {}, [], ""
        for name, label in CONTACT_FIELDS:
            key = value_key(name, src.get(name))
            if not key or key in known[name]:
                continue
            known[name].add(key)
            if company:
                contact[name] = src[name]
            else:
                note.append((label, src[name]))
        for name, label in note_fields:
            key = value_key(name, src.get(name))
            if not key or key in known[name]:
                continue
            known[name].add(key)
            note.append((label, src[name]))
        key = value_key(COMMENT_FIELD, src.get(COMMENT_FIELD))
        if key and key not in dst_comment and key not in seen_comments:
            seen_comments.append(key)
            comment = src[COMMENT_FIELD]
        if contact or note or comment:
            plan.append({"id": src["id"], "name": src.get("name") or "",
                         "contact": contact, "note": note, "comment": comment})
    return plan
