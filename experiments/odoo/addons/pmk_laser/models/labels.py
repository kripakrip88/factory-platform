# -*- coding: utf-8 -*-
"""Подписи задания лазеру одной строкой (разбор UX, шаг 36).

Строки, которые раньше были четырьмя полями, голым числом или длинным
названием:

    CypCut 6.3 · сохранил XE · 08.09.2026 14:34 · 65 контуров   (блок «Файл раскроя»)
    27 % · много                                                («Лом, кг» без доли)
    72 914 ₽/т · АО «Металлсервис», филиал Хабаровск · прайс от 16.06.2026
    6 кВт                                                       («Лазер №2» в списке)
    Снято с очереди — ждут: 3 листа                             (доводка шага 36)

ПОЧЕМУ ЧИСТЫЕ ФУНКЦИИ БЕЗ odoo. Как money.py и timing.py: формат проверяется
без базы, а модель только подставляет в него свои поля.

ПЕРЕНОСЫ. Между числом и единицей — неразрывный пробел: в узкой карточке строка
переносится по словам, но «72 914» не отрывается от «₽/т».
"""

import re
from decimal import ROUND_HALF_UP, Decimal

from ..tools.lxds import _parse_save_time, _plural
from .money import is_scrap_high, scrap_pct

NBSP = "\u00a0"


def _round(value, digits):
    """Округление как у человека (0,5 → 1), а не к чётному, как round()."""
    step = Decimal(1).scaleb(-digits)
    return Decimal(repr(float(value or 0.0))).quantize(step, rounding=ROUND_HALF_UP)


def num(value, digits=0):
    """Число по-русски: «72 914», «28,6». Разряды — неразрывным пробелом."""
    rounded = _round(value, digits)
    sign = "-" if rounded < 0 else ""
    text = "{:,.{d}f}".format(abs(rounded), d=digits)
    return sign + text.replace(",", NBSP).replace(".", ",")


def pct(value):
    """Процент с одним знаком и без «,0»: 27,0 → «27 %», 16,94 → «16,9 %»."""
    text = num(value, 1)
    if text.endswith(",0"):
        text = text[:-2]
    return "%s%s%%" % (text, NBSP)


def plural(count, one, few, many):
    """1 лист, 2 листа, 8 листов — то же правило, что в отчёте разбора файла."""
    return _plural(abs(int(count or 0)), one, few, many)


def scrap_signal(share_pct, sheets_kg, broken=False):
    """Лом словом и признак «много» — одной парой: («27 % · много», True).

    ОДНО РЕШЕНИЕ НА ТРИ МЕСТА (доводка шага 36). Подпись, жёлтая плашка
    (scrap_high) и фильтр «Много лома» решают по одной и той же хранимой
    доле с одним знаком — так, как её показывает экран: 20,04 % — это «20 %»,
    и «много» у него не бывает. Порог читается при каждом вызове
    (money.SCRAP_HIGH_PCT): сменили — подпись, плашка и фильтр согласны сразу.

    Баланс не сходится (лом отрицательный) — процент бессмыслен, вместо него
    слово, и это не «много». Металла не списано (файл не разобран) — пусто:
    «0 %» читалось бы как идеальная раскладка.
    """
    if broken:
        return "не сходится", False
    if not sheets_kg or sheets_kg <= 0:
        return "", False
    shown = float(_round(share_pct, 1))
    text = pct(shown)
    if is_scrap_high(shown):
        return "%s · много" % text, True
    return text, False


def scrap_label(scrap_kg, sheets_kg, broken=False):
    """Лом словом по килограммам: «27 % · много», «16,9 %», «не сходится» или
    пусто — то же правило, что scrap_signal."""
    share = scrap_pct(scrap_kg, sheets_kg) if sheets_kg and sheets_kg > 0 else 0.0
    return scrap_signal(share, sheets_kg, broken)[0]


def price_note(price_ton, supplier, price_date, source=None):
    """«72 914 ₽/т · АО «Металлсервис», филиал Хабаровск · прайс от 16.06.2026».

    source — откуда взята цена, последним словом: «из расчёта», когда цена —
    снимок строки расчёта, а не выбор строки прайса заново (доводка шага 36).
    """
    parts = ["%s%s₽/т" % (num(price_ton), NBSP)]
    if supplier:
        parts.append(supplier)
    if price_date:
        parts.append("прайс от %s" % price_date.strftime("%d.%m.%Y"))
    if source:
        parts.append(source)
    return " · ".join(parts)


def short_version(app):
    """«CypCut 6.3.907.8» → «CypCut 6.3»: номер сборки технологу ни к чему."""
    text = (app or "").strip()
    match = re.search(r"(\d+)\.(\d+)(?:\.\d+)+$", text)
    if match:
        text = text[:match.start()] + "%s.%s" % (match.group(1), match.group(2))
    return text


def saved_text(raw):
    """Время сохранения файла как его записал CypCut: «08.09.2026 14:34».

    Без сдвига поясов — суффикс Z у CypCut декоративный, время местное (см.
    tools/lxds.py, _parse_save_time). Не разобралось — исходный текст.
    """
    moment = _parse_save_time(raw or "")
    if moment:
        return moment.strftime("%d.%m.%Y %H:%M")
    return (raw or "").strip()


def file_info_line(app, operator, saved_raw, contours):
    """Четыре служебных поля файла одной серой строкой.

    («CypCut 6.3.907.8», «XE», «2026-09-08T14:34:05Z», 65) →
    «CypCut 6.3 · сохранил XE · 08.09.2026 14:34 · 65 контуров».
    Пустые части пропускаются; всё пусто (файл не разобран) — пусто.
    """
    parts = []
    if app:
        parts.append(short_version(app))
    if operator:
        parts.append("сохранил %s" % operator.strip())
    stamp = saved_text(saved_raw)
    if stamp:
        parts.append(stamp)
    if contours:
        parts.append("%s%s%s" % (contours, NBSP, plural(contours, "контур", "контура", "контуров")))
    return " · ".join(parts)


def sheets_note(count):
    """«1 лист», «2 листа», «8 листов»; листов нет — пусто."""
    if not count:
        return ""
    return "%s%s%s" % (count, NBSP, plural(count, "лист", "листа", "листов"))


def queue_closed_note(waiting):
    """Сигнал задания, снятого с «Очереди листов»: «Снято с очереди — ждут:
    3 листа». Считаются только ждущие листы — те, что ушли из очереди; лист,
    который режется, в ней остаётся. Ждущих нет — пусто: сигнал ни о чём бы
    не говорил. «Ждут:» — подписью, как фильтр очереди «Ждут», чтобы глагол
    не согласовывать с числом («ждёт 21 лист»)."""
    if not waiting:
        return ""
    return "Снято с очереди — ждут: %s" % sheets_note(waiting)


def power_label(power_kw):
    """Мощность станка подписью: 6 → «6 кВт», 2,5 → «2,5 кВт»; не задана — пусто."""
    if not power_kw or power_kw <= 0:
        return ""
    text = num(power_kw, 1)
    if text.endswith(",0"):
        text = text[:-2]
    return "%s%sкВт" % (text, NBSP)


def search_key(text):
    """Ключ сравнения подписи с набранным в поиске (доводка шага 36).

    Колонка показывает «6 кВт» с неразрывным пробелом, а человек наберёт
    «6 кВт», «6кВт», «6 квт» или «2.5 кВт»: пробелы любые убираем, регистр
    и десятичную точку приводим к виду подписи. «6 кВт» → «6квт».
    """
    return "".join((text or "").split()).lower().replace(".", ",")
