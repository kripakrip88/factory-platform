# -*- coding: utf-8 -*-
"""Деньги и вес расчёта одной строкой — для сделки и карточки воронки.

Разбор UX, шаг 31 (30.09.2026). Под названием сделки стояло «Ожидаемый доход
0,00 руб в Вероятность 91,67 %»: доход не заполнялся, вероятность считал
автомат без истории. Теперь там строка из расчёта:

    СМ-00024 · 50,9 т · цена 9 500 000 ₽ · металл 3 429 022 ₽ · маржа 63,9 %

а на карточке воронки короче: «50,9 т · 9,5 млн ₽ · маржа 64 %».

ПОЧЕМУ ЧИСТЫЕ ФУНКЦИИ БЕЗ odoo. Формат проверяется тестом без базы
(python3 addons/pmk_deal/tests/test_money_text.py), а модель только
подставляет в него поля расчёта.

ПЕРЕНОСЫ. Внутри числа и между числом и единицей — неразрывный пробел: строка
на узкой карточке переносится только по « · », и ни «9 500» с «000 ₽», ни
номер СМ- с весом не разъезжаются по строкам.
"""

from decimal import ROUND_HALF_UP, Decimal

NBSP = " "
SEP = " · "


def _round(value, digits):
    """Округление как у человека (0,5 → 1), а не к чётному, как round()."""
    step = Decimal(1).scaleb(-digits)
    return Decimal(repr(float(value or 0.0))).quantize(step, rounding=ROUND_HALF_UP)


def _decimal(value, digits):
    """Число по-русски, без лишнего нуля после запятой:
    12,0 → «12», 9,5 → «9,5», 63,86 → «63,9»."""
    text = str(_round(value, digits))
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("-0", ""):
        text = "0"
    return text.replace(".", ",")


def grouped(value):
    """9500000 → «9 500 000» (разряды — неразрывным пробелом)."""
    whole = int(_round(value, 0))
    return "{:,}".format(whole).replace(",", NBSP)


def rub(amount):
    """Сумма в рублях без копеек: 3429021,97 → «3 429 022 ₽»."""
    return "%s%s₽" % (grouped(amount), NBSP)


def rub_short(amount):
    """Сумма для карточки: 9500000 → «9,5 млн ₽», 54000 → «54 тыс ₽».

    Разряд выбирается ПОСЛЕ округления: 999 500 — это «1 млн ₽», а не
    «1000 тыс ₽», 999,6 — «1 тыс ₽», а не «1 000 ₽».
    """
    amount = amount or 0.0
    if abs(_round(amount, 0)) < 1000:
        return rub(amount)
    units = ((1e3, "тыс"), (1e6, "млн"), (1e9, "млрд"))
    for scale, unit in units:
        value = amount / scale
        # «123,4 млн» читается хуже, чем «123 млн»: от сотни — целыми.
        digits = 0 if abs(value) >= 100 else 1
        if abs(_round(value, digits)) >= 1000 and unit != units[-1][1]:
            continue
        return "%s%s%s%s₽" % (_decimal(value, digits), NBSP, unit, NBSP)


def pct(value, digits=1):
    """63,86 → «63,9 %» (digits=1) или «64 %» (digits=0)."""
    return "%s%s%%" % (_decimal(value, digits), NBSP)


def weight(kg):
    """Вес так же, как в расчёте (pmk_bridge, _pmk_weight_label):
    50938 кг → «50,9 т», 442 кг → «442 кг», 0,4 кг → «0,4 кг».
    Пустой расчёт — «0 кг», а не «0,0 кг». Граница — по округлённому
    числу: 999,6 кг — «1,0 т», а не «1000 кг»; 9,96 кг — «10 кг», а не
    «10,0 кг»."""
    kg = kg or 0.0
    if not kg:
        return "0%sкг" % NBSP
    if _round(kg, 0) >= 1000:
        return "%s%sт" % (("%.1f" % (kg / 1000.0)).replace(".", ","), NBSP)
    if _round(kg, 1) >= 10:
        return "%d%sкг" % (round(kg), NBSP)
    return "%s%sкг" % (("%.1f" % kg).replace(".", ","), NBSP)


def spec_line(name, weight_kg, price, metal, margin_pct):
    """Строка под названием сделки:
    «СМ-00024 · 50,9 т · цена 9 500 000 ₽ · металл 3 429 022 ₽ · маржа 63,9 %».

    Маржа — только при назначенной цене: без цены клиенту «маржа 0 %» была
    бы не правдой, а пустотой.
    """
    parts = [name or "", weight(weight_kg)]
    parts.append("цена " + rub(price) if price else "цена не назначена")
    parts.append("металл " + rub(metal))
    if price:
        parts.append("маржа " + pct(margin_pct, 1))
    return SEP.join(p for p in parts if p)


def card_line(weight_kg, price, margin_pct):
    """Карточка воронки: «50,9 т · 9,5 млн ₽ · маржа 64 %»."""
    parts = [weight(weight_kg)]
    if price:
        parts.append(rub_short(price))
        parts.append("маржа " + pct(margin_pct, 0))
    else:
        parts.append("цена не назначена")
    return SEP.join(parts)


def no_price_label(count):
    """«без цены: 1» — или пусто, когда у всех позиций цена есть."""
    return "без цены: %d" % count if count else ""


# ─── Карточки денег на сделке (приёмка 01.10.2026, R1) ─────────────────────
#
# Строка «СМ-00024 · 50,9 т · цена 9 500 000 ₽ · металл 3 429 022 ₽ · маржа
# 63,9 % · без цены: 1» сливалась в один большой текст (владелец: «не
# читаемо кроме красной подсветки без цены»). Теперь ряд карточек «подпись
# серым над значением», как карточки денег в форме расчёта. Подписи стоят в
# виде, здесь — только значения: вес — weight(), металл — rub().

def kpi_price(price):
    """Карточка «Цена клиенту»: «9 500 000 ₽»; цены нет — «не назначена»."""
    return rub(price) if price else "не назначена"


def kpi_margin(price, margin_pct, incomplete=False):
    """Карточка «Маржа»: «63,9 %».

    Неполный расчёт (у части позиций нет цены закупки, металл занижен) —
    «≤ 63,9 %»: это верхняя граница, как у полоски маржи в списках. Без цены
    клиенту маржи нет — «—», а не «0 %».
    """
    if not price:
        return "—"
    text = pct(margin_pct, 1)
    return "≤" + NBSP + text if incomplete else text
