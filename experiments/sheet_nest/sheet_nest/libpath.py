# -*- coding: utf-8 -*-
"""Доступ к пакету раскроя зонтов (сборщик .lxds, расшифровщик, растровый раскрой v1).

Пакет лежит в модуле Odoo: experiments/odoo/addons/pmk_vent_nest/lib/vent_nesting. Путь по умолчанию — от этого
файла по дереву репозитория; переопределить — переменной окружения VENT_NESTING_LIB (каталог, где лежит vent_nesting/).
    from sheet_nest.libpath import vn        # vn.spec_rebuild, vn.lxds_reader, vn.nest, vn.contours …
"""
import os, sys, importlib

LIB = os.environ.get("VENT_NESTING_LIB") or os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "odoo", "addons", "pmk_vent_nest", "lib"))
if not os.path.isdir(os.path.join(LIB, "vent_nesting")):
    raise ImportError("пакет vent_nesting не найден в %s (переменная VENT_NESTING_LIB)" % LIB)
if LIB not in sys.path:
    sys.path.insert(0, LIB)


class _NS:
    def __getattr__(self, name):
        mod = importlib.import_module("vent_nesting.cypcut." + name if name.startswith(("spec_", "xml_")) else "vent_nesting." + name)
        setattr(self, name, mod)
        return mod


vn = _NS()
