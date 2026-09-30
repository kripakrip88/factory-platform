# -*- coding: utf-8 -*-
"""Подписи формы расчёта одной строкой (разбор UX, шаг 32).

Строки, которые раньше были либо значком, либо четырьмя полями, либо голым
числом:

    В КП не попадут без цены: 1 изделие — «тест»
    есть прайс от 21.09                    (был красный «!» в шапке)
    С 16.06: +276 198 ₽ (+8,8 %)           (был блок из четырёх полей)
    ≥ 2 807,72 · без 3 поз.                («Металл, ₽» изделия без оговорки)

ПОЧЕМУ ЧИСТЫЕ ФУНКЦИИ БЕЗ odoo. Формат проверяется тестом без базы
(python3 addons/pmk_bridge/tests/test_spec_text.py), а модель только
подставляет в него свои поля — как tools/money_text.py в pmk_deal.

ПЕРЕНОСЫ. Внутри числа и между числом и единицей — неразрывный пробел: в
узкой шапке строка переносится по словам, но «276» не отрывается от «198 ₽».
"""

from decimal import ROUND_HALF_UP, Decimal

NBSP = " "
MINUS = "−"

# Сколько названий изделий перечислять в сигнале КП. Больше трёх в шапке
# документа — уже абзац; остальное — «и ещё N».
KP_SKIP_NAMES = 3


def _round(value, digits):
    """Округление как у человека (0,5 → 1), а не к чётному, как round()."""
    step = Decimal(1).scaleb(-digits)
    return Decimal(repr(float(value or 0.0))).quantize(step, rounding=ROUND_HALF_UP)


def plural(number, one, few, many):
    """1 изделие, 2 изделия, 5 изделий."""
    number = abs(int(number))
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return few
    return many


def rub_whole(amount):
    """Рубли целыми, без знака: 276198,4 → «276 198 ₽»."""
    whole = abs(int(_round(amount, 0)))
    return "%s%s₽" % ("{:,}".format(whole).replace(",", NBSP), NBSP)


def pct1(value):
    """Процент с одним знаком, без знака и без «,0»: 8,83 → «8,8 %», 10 → «10 %»."""
    text = str(abs(_round(value, 1)))
    if text.endswith(".0"):
        text = text[:-2]
    return "%s%s%%" % (text.replace(".", ","), NBSP)


def short_date(value, base_year=None):
    """Дата без года, если год тот же, что у расчёта: «16.06», иначе «16.06.2025»."""
    if not value:
        return ""
    if base_year and value.year != base_year:
        return value.strftime("%d.%m.%Y")
    return value.strftime("%d.%m")


def sign(value):
    """«+» или «−» (типографский минус, не дефис)."""
    return "+" if value > 0 else MINUS


def compare_later(since, price_date):
    """Прайс сравнения НОВЕЕ цен расчёта: «а что, если взять свежий прайс».

    Обычно сравнивают со старым прайсом — «что изменилось с июня». Но расчёт
    на старых ценах сравнивают и со свежим: насколько подорожает, если его
    взять. Тогда «было» — цены расчёта, «стало» — прайс сравнения: сравнение
    всегда идёт по времени, от раннего к позднему (доводка шага 32).
    """
    return bool(since and price_date and since > price_date)


def compare_summary(delta, pct, since, lost=0, base_year=None, later=False):
    """Итог вкладки «Цены» одной строкой.

    «С 16.06: +276 198 ₽ (+8,8 %)». Разница меньше полтинника — «без
    изменений»: копейки округления не повод для сигнала. Позиции, выпавшие из
    прайса, дописываются: без них удешевление читалось бы как настоящее, а
    металл всё равно придётся купить.
    Даты сравнения нет — строки нет: рядом с полем уже сказано «сравнивать
    не с чем».

    later — прайс сравнения новее цен расчёта (compare_later). «С 21.09»
    тогда было бы неправдой — «с 21.09 подешевело», хотя свежий прайс дороже.
    Пишем, что будет, если его взять: «По прайсу от 21.09 стало бы: +X ₽».
    Знак и процент модель уже считает по времени (от цен расчёта к прайсу).
    """
    if not since:
        return False
    if later:
        text = "По прайсу от %s" % short_date(since, base_year)
    else:
        text = "С %s" % short_date(since, base_year)
    delta = float(delta or 0.0)
    if abs(delta) < 0.5:
        text += ": без изменений"
    else:
        if abs(_round(pct, 1)) >= Decimal("0.1"):
            share = "%s%s" % (sign(delta), pct1(pct))
        else:
            # Рубли заметные, а процент округляется в ноль: большой расчёт,
            # маленькая правка. «+0 %» рядом с «+450 ₽» читается как ошибка.
            share = "меньше 0,1%s%%" % NBSP
        text += "%s: %s%s (%s)" % (
            " стало бы" if later else "", sign(delta), rub_whole(delta), share)
    if lost:
        text += " · выпало из прайса: %s%sпоз." % (lost, NBSP)
    return text


def stale_label(latest, base):
    """Сигнал «есть прайс свежее» словами: «есть прайс от 21.09»."""
    if not latest:
        return False
    return "есть прайс от %s" % short_date(latest, base.year if base else None)


def kp_skip_text(names):
    """Какие изделия не попадут в КП, потому что у них нет цены клиенту.

    «В КП не попадут без цены: 1 изделие — «тест»». Не больше трёх
    названий, дальше «и ещё N». Пусто — строки нет.
    """
    names = [name or "без названия" for name in names]
    if not names:
        return False
    count = len(names)
    shown = ", ".join("«%s»" % name for name in names[:KP_SKIP_NAMES])
    rest = count - min(count, KP_SKIP_NAMES)
    if rest:
        shown += " и ещё %s" % rest
    return "В КП не попадут без цены: %s%s%s — %s" % (
        count, NBSP, plural(count, "изделие", "изделия", "изделий"), shown)


def money2(amount):
    """Сумма с копейками, без знака валюты: 2807.72 → «2 807,72»."""
    value = _round(amount, 2)
    text = "{:,.2f}".format(abs(value)).replace(",", NBSP).replace(".", ",")
    return (MINUS + text) if value < 0 else text


def metal_label(amount, missing):
    """«Металл, ₽» изделия — с оговоркой, если у части позиций нет цены.

    Доводка шага 32. Колонка стоит рядом с ценой за штуку, чтобы цену
    ставили, видя металл. У позиции без цены закупки (в городе её нет)
    стоимость нулевая, и голое число занижено — цена изделия могла уйти ниже
    себестоимости. Поэтому так же, как на карточке «Металл к закупке»:

        24 926,00                  — все позиции с ценой
        ≥ 2 807,72 · без 3 поз.    — не меньше этого, 3 позиции без цены
        нет в прайсах: 2 поз.      — ни у одной позиции нет цены (а не 0,00)
        —                          — считать нечего (состав пуст)

    Ноль в денежной колонке читался как «бесплатно»; прочерк — как в составе.
    """
    missing = int(missing or 0)
    amount = float(amount or 0.0)
    has_amount = abs(amount) >= 0.005
    if not missing:
        return money2(amount) if has_amount else "—"
    if not has_amount:
        return "нет в прайсах: %s%sпоз." % (missing, NBSP)
    return "≥%s%s · без %s%sпоз." % (NBSP, money2(amount), missing, NBSP)


def per_ton(price_unit, mass_unit_kg):
    """Цена за единицу → за тонну. Масса неизвестна (0) — ноль, без деления.

    ⚠️ Мина листа: второй вариант габарита обнулит вес карточки, и масса
    листа станет нулём. Деление здесь уронило бы всю вкладку «Цены».
    """
    if not price_unit or not mass_unit_kg:
        return 0.0
    return price_unit / mass_unit_kg * 1000.0
