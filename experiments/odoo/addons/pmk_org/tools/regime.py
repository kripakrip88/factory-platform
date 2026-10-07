# -*- coding: utf-8 -*-
"""Налоговые режимы организации — без базы (разбор UX, шаг 58).

Чистые функции: их гоняет голый питон
(python3 addons/pmk_org/tests/test_step58_regime.py), модели только зовут.
"""

# Режимы — как их называет завод. Порядок — порядок в выпадающем списке.
REGIMES = [
    ("vat22", "НДС 22%"),
    ("usn0", "УСН без НДС"),
    ("usn5", "УСН с НДС 5%"),
    ("usn7", "УСН с НДС 7%"),
]
REGIME_LABELS = dict(REGIMES)

# Ставка режима. Печать берёт ставку из налога (account.tax.amount), эта
# таблица — для заведения налогов при установке и на случай, если налог
# режима кто-то удалил: КП не должно остаться без строки налога.
RATES = {"vat22": 22.0, "usn0": 0.0, "usn5": 5.0, "usn7": 7.0}

# Налог продаж режима: (название налога, подпись в счёте, группа налогов).
# Названия уникальны в пределах компании (ограничение account.tax).
TAXES = {
    "vat22": ("НДС 22% (продажа)", "НДС 22%", "НДС 22%"),
    "usn0": ("Без НДС (продажа)", "Без НДС", "Без НДС"),
    "usn5": ("НДС 5% (продажа)", "НДС 5%", "НДС 5%"),
    "usn7": ("НДС 7% (продажа)", "НДС 7%", "НДС 7%"),
}


def is_usn(regime):
    """Упрощёнка — любой из режимов УСН."""
    return bool(regime) and regime.startswith("usn")


def regime_at(rows, day):
    """Строка режима, действующая на дату.

    rows — пары (дата начала, значение). Действует строка с наибольшей датой
    начала не позже day. Документ датирован раньше первой строки — берём
    самую раннюю: документ задним числом не остаётся без налога (решение по
    умолчанию шага 58). Строк нет — None.
    """
    rows = sorted((r for r in rows if r[0]), key=lambda r: r[0])
    if not rows:
        return None
    if not day:
        return rows[-1][1]
    current = rows[0][1]
    for date_from, value in rows:
        if date_from <= day:
            current = value
        else:
            break
    return current


def today_label(rows, today):
    """«Режим сегодня» словами — без запасного «самая ранняя строка».

    rows — пары (дата начала, код режима). Печать документа, датированного
    раньше первой строки, берёт самую раннюю (regime_at), но сказать
    «сегодня действует УСН», когда строка «будет» с 01.01.2027, — неправда:
    «не задан (с 01.01.2027 — УСН без НДС)». Строк нет — пусто.
    """
    rows = sorted((r for r in rows if r[0]), key=lambda r: r[0])
    if not rows:
        return ""
    first_from, first = rows[0]
    if today and today < first_from:
        return "не задан (с %s — %s)" % (
            first_from.strftime("%d.%m.%Y"), REGIME_LABELS.get(first, first))
    return REGIME_LABELS.get(regime_at(rows, today), "")


def state_of(date_from, next_from, today):
    """Состояние строки режима словом: «действует», «прошёл», «будет».

    next_from — дата начала следующей строки (или None).
    """
    if date_from and date_from > today:
        return "future"
    if next_from and next_from <= today:
        return "past"
    return "current"


def signer_from_name(name):
    """ФИО предпринимателя из названия: «ИП Чулков В. В.» → «Чулков В. В.»."""
    name = " ".join((name or "").split())
    for prefix in ("Индивидуальный предприниматель ", "ИП "):
        if name.lower().startswith(prefix.lower()):
            return name[len(prefix):].strip()
    return name
