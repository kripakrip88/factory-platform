# -*- coding: utf-8 -*-
"""Справочники опор — по стандарту на файл (Антон 25.10.2026: «чтобы разные справочники можно
было править отдельно»). Модели работают только через этот диспетчер: он по типу опоры
отдаёт вызов модулю своего стандарта.

Новый стандарт: файл tools/<стандарт>.py с тем же набором функций (TYPES, STANDARD, diameters,
executions, check, check_height, standard_h, body, parts, ost_mass, designation, name, short,
split_exe, history_patterns; по желанию catalog_only) + строка в STANDARDS + docs/<стандарт>.md.
"""
from . import ost36_146, ost36_94

STANDARDS = (ost36_146, ost36_94)
TYPES = {k: v for m in STANDARDS for k, v in m.TYPES.items()}
STEELS = ost36_146.STEELS
_BY_KIND = {k: m for m in STANDARDS for k in m.TYPES}


def std(kind):
    return _BY_KIND[kind]


def norm_dn(dn):
    """Дн из поля Float: 219.0 → 219, 21.3 → 21.3 — в названиях без «.0»."""
    dn = float(dn or 0)
    return int(dn) if dn.is_integer() else dn


def check(kind, dn, exe):
    if kind not in _BY_KIND:
        return "Тип опоры не понят"
    return std(kind).check(kind, norm_dn(dn), exe)


def diameters(kind):
    return std(kind).diameters(kind)


def executions(kind, dn):
    return std(kind).executions(kind, dn)


def split_exe(kind, exe):
    return std(kind).split_exe(exe)


def check_height(kind, dn, exe, h):
    return std(kind).check_height(kind, norm_dn(dn), exe, h)


def standard_h(kind, dn, exe):
    return std(kind).standard_h(kind, norm_dn(dn), exe)


def body(kind, dn, exe, h=None):
    return std(kind).body(kind, norm_dn(dn), exe, h)


def parts(kind, dn, exe, h=None):
    return std(kind).parts(kind, norm_dn(dn), exe, h)


def mass(kind, dn, exe, h=None):
    return round(sum(p["qty"] * p["unit_mass"] for p in parts(kind, dn, exe, h)), 2)


def ost_mass(kind, dn, exe):
    return std(kind).ost_mass(kind, norm_dn(dn), exe)


def designation(kind, dn, exe, steel=None):
    return std(kind).designation(kind, norm_dn(dn), exe, steel)


def name(kind, dn, exe, steel, h=None):
    return std(kind).name(kind, norm_dn(dn), exe, steel, h)


def short(kind, dn, exe, steel, h=None):
    return std(kind).short(kind, norm_dn(dn), exe, steel, h)


def history_patterns(kind, dn, exe):
    return std(kind).history_patterns(kind, norm_dn(dn), exe)


def catalog_only():
    """Марки без состава по всем стандартам: (стандарт, марка, семейство, подпись, масса ОСТ)."""
    rows = []
    for m in STANDARDS:
        for row in getattr(m, "catalog_only", lambda: [])():
            rows.append((m.STANDARD,) + tuple(row))
    return rows
