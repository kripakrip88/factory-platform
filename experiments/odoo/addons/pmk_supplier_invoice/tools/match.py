# -*- coding: utf-8 -*-
"""Строка счёта поставщика → позиция справочника и цена в единице карточки.

Сопоставляет тот же разборщик, что и прайсы (pmk_bridge/tools/vendor/match.py), но
по названию, которое ассистент уже привёл к виду справочника («Труба профильная
квадратная 40x40x3»). Ассистент может ошибиться, поэтому каждое сопоставление
проверяют правила — без них «квадрат 40х3» разборщик сам по себе читает как
круглую трубу 40×3:

  • вид — слово из ИСХОДНОЙ строки счёта (труб+квадрат → профильная квадратная,
    угл → уголок, лист → лист…) обязано совпасть с видом найденной позиции;
  • размер — числа размера исходной строки обязаны быть среди чисел позиции;
  • масса — если в счёте есть и тонны, и метры (Прим. «26шт x 12м = 312п.м»),
    масса метра счёта сверяется со справочником (допуск 10 %, как у прайсов).

Цена в базе — С НДС, как в бумаге поставщика (load_prices.py, решение 24.09.2026):
руб за метр = руб/т / 1000 × кг в метре. Масса — из счёта (поставщик считает по
своей), без неё — из справочника.
"""
import re

from odoo.addons.pmk_bridge.tools.grades import map_grade, normalise_grade
from odoo.addons.pmk_bridge.tools.vendor.match import Matcher

MASS_TOLERANCE_PCT = 10.0

# (условие на исходную строку, ожидаемое начало вида позиции, по-человечески)
KIND_RULES = [
    (lambda t: "труб" in t and re.search(r"квадр|\bкв\b", t), "Труба профильная квадратная", "квадратная труба"),
    (lambda t: "труб" in t and "прямоуг" in t, "Труба профильная прямоугольная", "прямоугольная труба"),
    (lambda t: "труб" in t and re.search(r"вгп|водогаз", t), "Труба ВГП", "труба ВГП"),
    (lambda t: "труб" in t, "Труба", "труба"),
    (lambda t: re.search(r"\bугол|\bугл|уголок", t) and re.search(r"неравн|н/п", t), "Уголок неравнополочный",
     "неравнополочный уголок"),
    (lambda t: re.search(r"\bугол|\bугл|уголок", t), "Уголок", "уголок"),
    (lambda t: "швел" in t and "гнут" in t, "Швеллер гнутый", "гнутый швеллер"),
    (lambda t: "швел" in t, "Швеллер", "швеллер"),
    (lambda t: re.search(r"балк|двутавр", t), "Двутавр", "двутавр"),
    (lambda t: re.search(r"\bарм", t), "Арматура", "арматура"),
    (lambda t: "лист" in t, "Лист", "лист"),
    (lambda t: "полос" in t, "Полоса", "полоса"),
    (lambda t: "шестигр" in t, "Шестигранник", "шестигранник"),
    (lambda t: re.search(r"\bкруг", t), "Круг", "круг"),
    (lambda t: re.search(r"\bквадрат", t), "Квадрат", "квадрат"),
]

SIZE_RE = re.compile(r"\d+(?:[.,]\d+)?(?:\s*[xх×*]\s*\d+(?:[.,]\d+)?)+", re.I)
LENGTH_RE = re.compile(r"(?:дл\.?|длин\w*)\s*(\d+(?:[.,]\d+)?)\s*(м\b|мм\b)?", re.I)
METRES_RE = re.compile(r"=\s*(\d+(?:[.,]\d+)?)\s*п\.?\s*м", re.I)


# Крашеный лист («Лист гладкий 0.65 (RAL 3005, Красное вино)», «полиэстер», «ПЭ») — это
# оцинковка с полимерным покрытием: в доборах и вентзонтах он — «Лист Оцинкованный 0,65»
# + цвет из «Цвета доборки (RAL)». Своего вида в справочнике у крашеного нет (26.10.2026).
PAINTED_RE = re.compile(r"\bral\b|\bрал\b|окраш|полиэст|\bпэ\b|\bpe\b|полимер|пурал|printech", re.I)


def painted_sheet(raw, catalog_name):
    """Название для разборщика: крашеный лист → «Лист оцинкованный …» (толщина и габарит —
    из названия ассистента). Не крашеный — как было."""
    text = "%s %s" % (raw or "", catalog_name or "")
    if "лист" not in text.lower() or not PAINTED_RE.search(text) or "оцинк" in (catalog_name or "").lower():
        return catalog_name
    size = SIZE_RE.search(catalog_name or "") or SIZE_RE.search(raw or "")
    th = re.search(r"\b(\d+[.,]\d+)\b", raw or "")
    if size and "x" in size.group(0).lower().replace("х", "x").replace("×", "x"):
        return "Лист оцинкованный %s" % size.group(0)
    return "Лист оцинкованный %s" % (th.group(1) if th else "")


class MatchError(Exception):
    def __init__(self, kind, detail=""):
        super().__init__(kind)
        self.kind, self.detail = kind, detail


def _num(text):
    try:
        return float(str(text).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def expected_kind(raw):
    low = (raw or "").lower().replace("ё", "е")
    for cond, kind, human in KIND_RULES:
        if cond(low):
            return kind, human
    return None, None


def size_numbers(raw):
    """Числа размера исходной строки: «квадрат 40х3 ГОСТ дл.6000» → {40, 3}."""
    text = re.sub(r"гост\s*[\dр\s.\-]+", " ", (raw or "").lower())
    text = LENGTH_RE.sub(" ", text)
    m = SIZE_RE.search(text)
    if not m:
        return set()
    return {float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", m.group(0))}


def bar_length_mm(raw):
    """Длина хлыста из «дл.6000», «дл 6м», «дл.12000» — в мм."""
    m = LENGTH_RE.search(raw or "")
    if not m:
        return 0.0
    value = _num(m.group(1)) or 0.0
    unit = (m.group(2) or "").lower()
    if unit == "м" or (not unit and value <= 20):
        value *= 1000
    return value


def metres_from_note(note):
    """«26шт x 12м = 312п.м пп» → 312."""
    m = METRES_RE.search(note or "")
    return _num(m.group(1)) if m else None


def reference(env):
    """Справочник для разборщика — те же ключи, что у загрузчика прайсов
    (load_prices.reference_from_db): карточка — pmk_bridge.product_<ключ>."""
    profiles, sheets = [], []
    recs = env["pmk.metal.profile"].sudo().search([], order="id")
    ext = recs.get_external_id()
    for rec in recs:
        xmlid = ext.get(rec.id)
        if xmlid:
            profiles.append({"id": xmlid.split(".", 1)[1], "type": rec.profile_type, "size": rec.size_label,
                             "gost": rec.gost, "mass": rec.mass_per_meter, "rid": rec.id})
    recs = env["pmk.metal.sheet"].sudo().search([], order="id")
    ext = recs.get_external_id()
    for rec in recs:
        xmlid = ext.get(rec.id)
        if xmlid:
            sheets.append({"id": xmlid.split(".", 1)[1], "type": rec.sheet_type, "th": rec.thickness_mm,
                           "gost": rec.gost, "mass": rec.mass_per_sqm, "rid": rec.id})
    return {"profiles": profiles, "sheets": sheets}


def matcher(env):
    return Matcher(reference(env))


def match_line(env, m, raw, catalog_name, grade_text=""):
    """→ dict(item, kind, tmpl, is_sheet, grade) или MatchError с причиной."""
    exp_kind, human = expected_kind(raw)
    if not exp_kind:
        raise MatchError("вид проката не опознан", "в строке счёта нет слова вида (труба, уголок, лист…)")
    catalog_name = painted_sheet(raw, catalog_name)
    res = m.match(catalog_name or raw)
    if res["status"] != "совпало":
        raise MatchError("позиция не найдена", "%s: «%s»" % (res["status"], catalog_name or raw))
    item = res["matches"][0]
    kind = str(res.get("type") or "")
    is_sheet = kind.startswith("Лист")
    found_kind = ("Лист " + item["type"]) if is_sheet else item["type"]
    if not found_kind.startswith(exp_kind):
        raise MatchError("вид не сходится", "в счёте — %s, а найдено «%s %s»" % (
            human, found_kind, item.get("size", "")))
    nums = size_numbers(raw)
    have = {float(x) for x in res.get("nums") or []}
    if is_sheet:
        have |= {float(item.get("th") or 0)}
    if is_sheet and nums and min(nums) not in have:
        # Лист: толщина — в любом месте строки («Лист гладкий 0.65 (RAL 3005) (710х1250)»:
        # размер-группа там габарит заготовки, а толщина стоит отдельно).
        th = float((res.get("nums") or [0])[0])
        loose = {float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", raw or "")}
        if th in loose:
            nums = {th}
    if nums and not nums <= have and not (is_sheet and min(nums) in have):
        raise MatchError("размер не сходится", "в счёте %s, у позиции %s" % (
            "×".join("%g" % x for x in sorted(nums)), "×".join("%g" % x for x in sorted(have))))
    tmpl = env.ref("pmk_bridge.product_%s" % item["id"], raise_if_not_found=False)
    if not tmpl:
        raise MatchError("нет карточки под позицию справочника", "pmk_bridge.product_%s" % item["id"])
    grade = map_grade(grade_text or res.get("grade") or "")
    return {"item": item, "tmpl": tmpl, "is_sheet": is_sheet, "grade": grade,
            "grade_text": normalise_grade(grade_text or res.get("grade") or "")}


def check_mass(mass_invoice, mass_ref, what="кг/м"):
    """Масса счёта против справочника; больше допуска — ошибка счёта или не та позиция."""
    if not (mass_invoice and mass_ref):
        return 0.0
    dev = abs(mass_invoice - mass_ref) / mass_ref * 100.0
    if dev > MASS_TOLERANCE_PCT:
        raise MatchError("масса не сходится со справочником", "%.3f %s против %.3f (%.0f %%)" % (
            mass_invoice, what, mass_ref, dev))
    return dev
